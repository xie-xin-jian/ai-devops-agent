"""Evaluation report viewing and triggering API routes.

Reports are read from the local ``eval/reports`` directory written by
``scripts/run_eval.py``. Report endpoints are read-only; ``POST /run``
spawns ``run_eval.py`` as a subprocess (this calls the model API and
costs money, hence the ACTION_APPROVE permission).
"""

import json
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from agent.platform.config import WORKDIR
from agent.platform.identity import ACTION_APPROVE, AUDIT_VIEW, Principal
from api.auth import require_permissions

router = APIRouter()

_BATCH_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
_LOG_TAIL_LINES = 40
_MAX_TRIALS = 20
_MAX_PARALLEL = 8
_SUMMARY_KEYS = (
    "batch_id",
    "label",
    "model_id",
    "started_at",
    "finished_at",
    "duration_ms",
    "trials",
    "completed",
    "passed",
    "failed",
    "pass_rate",
    "agent_cost_cny",
    "judge_cost_cny",
    "total_cost_cny",
    "by_category",
)


def _reports_dir() -> Path:
    return (WORKDIR / "eval" / "reports").resolve()


def _load_report(batch_id: str) -> dict:
    """Load one report by batch id, rejecting traversal-style ids."""
    if not _BATCH_ID_PATTERN.match(batch_id or ""):
        raise HTTPException(
            status_code=404,
            detail={"message": "Report not found"},
        )
    path = _reports_dir() / f"{batch_id}.json"
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail={"message": "Report not found"},
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail={"message": f"Invalid report file: {exc}"},
        ) from exc


@router.get("/batches")
async def list_eval_batches(
    _principal: Principal = Depends(require_permissions(AUDIT_VIEW)),
):
    """List report summaries, newest first, with Wilson CIs."""
    from agent.evaluation.baseline import wilson_ci

    batches = []
    for path in sorted(_reports_dir().glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        summary = {key: data.get(key) for key in _SUMMARY_KEYS}
        if not summary.get("batch_id"):
            summary["batch_id"] = path.stem
        completed = int(summary.get("completed") or 0)
        passed = int(summary.get("passed") or 0)
        summary["pass_rate_ci95"] = (
            wilson_ci(passed, completed) if completed else None
        )
        batches.append(summary)
    batches.sort(
        key=lambda item: float(item.get("started_at") or 0),
        reverse=True,
    )
    return {"batches": batches, "reports_dir": str(_reports_dir())}


@router.get("/reports/{batch_id}")
async def get_eval_report(
    batch_id: str,
    _principal: Principal = Depends(require_permissions(AUDIT_VIEW)),
):
    """Return the full report, including per-trial details."""
    return _load_report(batch_id)


@router.get("/compare")
async def compare_eval_reports(
    baseline: str,
    current: str,
    tolerance: float = 0.0,
    alpha: float = 0.05,
    _principal: Principal = Depends(require_permissions(AUDIT_VIEW)),
):
    """Significance-aware comparison of two batches."""
    from agent.evaluation.baseline import compare_reports

    baseline_report = _load_report(baseline)
    current_report = _load_report(current)
    return compare_reports(
        baseline_report,
        current_report,
        tolerance=max(0.0, tolerance),
        alpha=min(max(float(alpha), 0.0), 1.0),
    )


class EvalRunRequest(BaseModel):
    """Parameters for a UI-triggered evaluation run."""

    validate_only: bool = False
    cases: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    trials: int = 3
    parallel: int = 1
    judge: bool = False
    stop_on_failure: bool = False
    label: str = ""


class _UIRun:
    """Bookkeeping for one subprocess evaluation run."""

    def __init__(self, batch_id: str, args: list[str], log_path: Path,
                 proc: subprocess.Popen, request: EvalRunRequest):
        self.batch_id = batch_id
        self.args = args
        self.log_path = log_path
        self.proc = proc
        self.request = request
        self.started_at = time.time()

    def status(self) -> dict:
        exit_code = self.proc.poll()
        if exit_code is None:
            status = "running"
        else:
            status = "completed" if exit_code == 0 else "failed"
        return {
            "run_id": self.batch_id,
            "status": status,
            "exit_code": exit_code,
            "started_at": self.started_at,
            "elapsed_s": round(time.time() - self.started_at, 1),
            "validate_only": self.request.validate_only,
            "label": self.request.label,
            "cases": self.request.cases,
            "categories": self.request.categories,
            "trials": self.request.trials,
            "parallel": self.request.parallel,
            "judge": self.request.judge,
            "log_tail": _read_log_tail(self.log_path),
        }


def _read_log_tail(path: Path, lines: int = _LOG_TAIL_LINES) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(content.splitlines()[-lines:])


_UI_RUNS: dict[str, _UIRun] = {}
_UI_RUNS_LOCK = threading.Lock()


@router.post("/run")
async def start_eval_run(
    request: EvalRunRequest,
    _principal: Principal = Depends(require_permissions(ACTION_APPROVE)),
):
    """Run scripts/run_eval.py as a subprocess. One run at a time."""
    with _UI_RUNS_LOCK:
        for run in _UI_RUNS.values():
            if run.proc.poll() is None:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": (
                            "Another evaluation run is still in progress "
                            f"({run.batch_id})"
                        ),
                        "active_run_id": run.batch_id,
                    },
                )
    batch_id = (
        f"eval_ui_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4]}"
    )
    args = [sys.executable, "scripts/run_eval.py", "--batch-id", batch_id]
    if request.validate_only:
        args.append("--validate-only")
    for case in request.cases:
        args += ["--case", case]
    for category in request.categories:
        args += ["--category", category]
    if not request.validate_only:
        args += [
            "--trials", str(max(1, min(int(request.trials), _MAX_TRIALS))),
            "--parallel", str(max(1, min(int(request.parallel), _MAX_PARALLEL))),
        ]
        if request.judge:
            args.append("--judge")
        if request.stop_on_failure:
            args.append("--stop-on-failure")
    if request.label:
        args += ["--label", request.label]

    log_dir = WORKDIR / "eval" / ".runtime" / "ui_runs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{batch_id}.log"
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    log_file = log_path.open("w", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            args,
            cwd=str(WORKDIR),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
    finally:
        log_file.close()
    with _UI_RUNS_LOCK:
        _UI_RUNS[batch_id] = _UIRun(
            batch_id, args, log_path, proc, request,
        )
    return {
        "run_id": batch_id,
        "args": args,
        "log_path": str(log_path),
    }


@router.get("/runs")
async def list_eval_runs(
    _principal: Principal = Depends(require_permissions(AUDIT_VIEW)),
):
    """Status of UI-triggered runs, newest first (in-memory only)."""
    with _UI_RUNS_LOCK:
        runs = list(_UI_RUNS.values())
    statuses = [run.status() for run in runs]
    statuses.sort(key=lambda item: item["started_at"], reverse=True)
    # Drop finished runs beyond the most recent 10 to bound memory.
    finished = [s for s in statuses if s["status"] != "running"]
    for stale in finished[10:]:
        with _UI_RUNS_LOCK:
            _UI_RUNS.pop(stale["run_id"], None)
    return {"runs": statuses}

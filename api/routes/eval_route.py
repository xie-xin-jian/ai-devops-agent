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
from collections import defaultdict
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


def _cases_dir() -> Path:
    return (WORKDIR / "eval" / "cases").resolve()


def _fixtures_dir() -> Path:
    return (WORKDIR / "eval" / "fixtures").resolve()


def _case_history() -> dict[str, dict]:
    """Aggregate each case's most recent pass rate across all reports.

    Reports are visited newest-first; the first report containing a case id
    wins, so the UI shows "how did this case do last time it was run".
    """
    reports: list[tuple[float, str, dict]] = []
    for path in _reports_dir().glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or not isinstance(
            data.get("results"), list
        ):
            continue
        reports.append((float(data.get("started_at") or 0), path.stem, data))
    reports.sort(key=lambda item: item[0], reverse=True)

    history: dict[str, dict] = {}
    for _, batch_id, data in reports:
        grouped: dict[str, list[dict]] = defaultdict(list)
        for result in data["results"]:
            if isinstance(result, dict) and result.get("case_id"):
                grouped[str(result["case_id"])].append(result)
        for case_id, trials in grouped.items():
            if case_id in history:
                continue
            completed = [t for t in trials if t.get("status") == "completed"]
            passed = [t for t in completed if t.get("passed")]
            history[case_id] = {
                "last_pass_rate": (
                    len(passed) / len(completed) if completed else None
                ),
                "last_trials": len(completed),
                "last_batch_id": str(data.get("batch_id") or batch_id),
            }
    return history


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


@router.get("/metrics")
async def eval_metrics(
    _principal: Principal = Depends(require_permissions(AUDIT_VIEW)),
):
    """Cross-batch time series backing the experiments sparkline.

    Read-only: scans ``eval/reports/*.json`` and returns one pass-rate point
    per batch in chronological order. Report files are never modified and
    nothing is persisted. AI evaluation rarely reaches 100%, so tracking how
    the pass rate moves across batches is more useful than any single score.
    """
    points = []
    for path in sorted(_reports_dir().glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or not isinstance(
            data.get("results"), list
        ):
            continue
        completed = int(data.get("completed") or 0)
        passed = int(data.get("passed") or 0)
        pass_rate = data.get("pass_rate")
        if pass_rate is None:
            pass_rate = passed / completed if completed else 0.0
        cases = {
            str(result["case_id"])
            for result in data["results"]
            if isinstance(result, dict) and result.get("case_id")
        }
        points.append({
            "batch_id": str(data.get("batch_id") or path.stem),
            "label": str(data.get("label") or ""),
            "started_at": float(data.get("started_at") or 0),
            "pass_rate": float(pass_rate or 0),
            "total_cost_cny": float(data.get("total_cost_cny") or 0),
            "cases": len(cases),
            "trials": completed,
        })
    points.sort(key=lambda item: item["started_at"])
    return {
        "points": points,
        "total": len(points),
        "reports_dir": str(_reports_dir()),
    }


@router.get("/cases")
async def list_eval_cases(
    _principal: Principal = Depends(require_permissions(AUDIT_VIEW)),
):
    """Read-only catalog of evaluation cases with recent pass rates.

    Parses ``eval/cases/*.yaml`` using the same loader as ``run_eval.py`` so
    the UI can show exactly which cases exist (and how they last performed)
    instead of asking users to type ids into a free-text field.
    """
    from agent.evaluation.cases import (
        CATEGORIES,
        load_cases,
        rule_name,
        validate_cases,
    )

    cases, load_errors = load_cases(_cases_dir())
    validation_errors = validate_cases(cases, _fixtures_dir())
    history = _case_history()

    items = []
    for case in cases:
        stat = history.get(case.id, {})
        items.append({
            "id": case.id,
            "category": case.category,
            "topic": case.topic,
            "severity": case.severity,
            "prompt": case.prompt,
            "fixture": case.fixture,
            "service": case.service,
            "approvals": case.approvals,
            "timeout_seconds": case.timeout_seconds,
            "max_turns": case.max_turns,
            "expect_count": len(case.expect),
            "expect_rules": [
                name for name in (rule_name(r) for r in case.expect) if name
            ],
            "tags": list(case.tags),
            "notes": case.notes,
            "has_judge": bool(case.judge_rubric),
            "is_example": "example" in case.tags,
            "source": case.source,
            "last_pass_rate": stat.get("last_pass_rate"),
            "last_trials": stat.get("last_trials", 0),
            "last_batch_id": stat.get("last_batch_id", ""),
        })
    return {
        "cases": items,
        "categories": sorted(CATEGORIES),
        "total": len(items),
        "errors": load_errors + validation_errors,
    }


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
    comparison = compare_reports(
        baseline_report,
        current_report,
        tolerance=max(0.0, tolerance),
        alpha=min(max(float(alpha), 0.0), 1.0),
    )
    comparison["verdict"] = _build_verdict(comparison)
    return comparison


def _build_verdict(comparison: dict) -> dict:
    """Reduce a comparison to one three-state CI gate decision.

    Kept at the route layer so the statistical core (baseline.py) stays
    untouched: the API merely annotates its output for the UI.
    """
    regressions = comparison.get("regressions") or []
    high = comparison.get("high_severity_regressions") or []
    all_items = (
        regressions
        + (comparison.get("improvements") or [])
        + (comparison.get("drops_within_noise") or [])
    )
    significant = [
        item for item in regressions
        if item.get("significance") == "significant"
    ]
    insufficient = {
        str(item.get("case_id"))
        for item in all_items
        if item.get("significance") == "insufficient-samples"
    }
    alpha = comparison.get("alpha", 0.05)
    min_samples = comparison.get("min_samples", 5)

    # Only statistically-confirmed regressions block the gate. A high
    # severity case whose samples are insufficient is NOT a confirmed
    # regression (the z-test never ran), so severity must not pre-empt the
    # significance check here -- otherwise every small-sample demo report
    # would show a misleading hard "blocked".
    if significant:
        status = "blocked"
        notable = sum(
            1 for item in significant if item.get("severity") == "high"
        )
        detail = f"{len(significant)} 个统计显著回归 (p < {alpha})"
        if notable:
            detail += f"，其中 {notable} 个高危"
        reason = detail + "，建议阻断合入"
    elif any(
        item.get("significance") == "insufficient-samples"
        for item in regressions
    ):
        status = "insufficient"
        reason = (
            f"检测到数值下降，但用例试跑次数不足 {min_samples}，"
            "显著性门禁未生效，建议用 --trials 10 重跑后再判定"
        )
    elif insufficient and len(insufficient) == len(all_items):
        status = "insufficient"
        reason = (
            f"全部 {len(insufficient)} 个对比用例样本不足 {min_samples} 次，"
            "显著性门禁未生效，建议用 --trials 10 重跑"
        )
    else:
        status = "pass"
        reason = "未检测到显著回归，可合入"

    return {
        "status": status,
        "reason": reason,
        "alpha": alpha,
        "min_samples": min_samples,
        "tolerance": comparison.get("tolerance", 0.0),
        "significant_regressions": len(significant),
        "high_severity_regressions": len(high),
        "insufficient_cases": len(insufficient),
    }


class EvalRunRequest(BaseModel):
    """Parameters for a UI-triggered evaluation run."""

    validate_only: bool = False
    cases: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    trials: int = 3
    parallel: int = 1
    judge: bool = False
    stop_on_failure: bool = False
    include_examples: bool = False
    label: str = ""


_CATEGORY_NAMES = {
    "core": "正常诊断",
    "boundary": "边界拒答",
    "abnormal": "危险拦截",
    "faq": "开放问答",
}


def _auto_label(request: EvalRunRequest) -> str:
    """没有手填 label 时，按本次运行范围生成可读批次名。

    批次 ID 仍然保留时间戳 + 短哈希用于定位文件，这里只负责展示名，
    让「实验」列表不再直接暴露 ``eval_ui_20261121_140917_fd65``。
    """
    parts: list[str] = []
    if request.cases:
        parts.append(
            request.cases[0]
            if len(request.cases) == 1
            else f"{len(request.cases)} 个用例"
        )
    if request.categories:
        names = [_CATEGORY_NAMES.get(c, c) for c in request.categories]
        parts.append(" + ".join(names))
    scope = " · ".join(parts) if parts else "全部用例"
    if request.validate_only:
        return f"{scope} · 校验"
    return f"{scope} · {max(1, request.trials)} 次试跑"


def _effective_scope(request: EvalRunRequest) -> tuple[list[str], list[str]]:
    """Resolve a UI run scope to explicit case ids, minus teaching examples.

    ``--case`` and ``--category`` are intersected by the CLI and neither can
    express "everything except the two demo cases". Resolving the scope here
    keeps scripts/run_eval.py and the evaluation core untouched.
    """
    if request.validate_only or request.include_examples:
        return list(request.cases), list(request.categories)
    from agent.evaluation.cases import load_cases

    cases, _ = load_cases(_cases_dir())
    excluded = {c.id for c in cases if "example" in c.tags}
    if request.cases:
        ids = [c for c in request.cases if c not in excluded]
    elif request.categories:
        ids = [
            c.id for c in cases
            if c.category in request.categories and c.id not in excluded
        ]
    else:
        ids = [c.id for c in cases if c.id not in excluded]
    return ids, []


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
        self._planned_trials = 0
        self._peak_completed = 0

    def _progress(self) -> tuple[int, int]:
        """Best-effort (completed, total) without touching the runner.

        ``total`` comes from the ``selection`` line printed by run_eval.py;
        ``completed`` counts trial_* workspace dirs. Those dirs are deleted
        after each trial, so a monotonic high-water mark avoids regressions.
        """
        log = _read_log_tail(self.log_path, lines=200)
        if not self._planned_trials:
            match = re.search(r'"planned_trials"\s*:\s*(\d+)', log)
            if match:
                self._planned_trials = int(match.group(1))
        total = self._planned_trials
        exit_code = self.proc.poll()
        if exit_code == 0 and total:
            return total, total

        workspaces = (
            WORKDIR / "eval" / ".runtime" / self.batch_id / "workspaces"
        )
        try:
            running = sum(
                1
                for case_dir in workspaces.iterdir()
                if case_dir.is_dir()
                for trial in case_dir.iterdir()
                if trial.is_dir() and trial.name.startswith("trial_")
            )
        except OSError:
            running = 0
        self._peak_completed = max(self._peak_completed, running)
        completed = min(self._peak_completed, total) if total else self._peak_completed
        return completed, total

    def status(self) -> dict:
        exit_code = self.proc.poll()
        if exit_code is None:
            status = "running"
        else:
            status = "completed" if exit_code == 0 else "failed"
        completed, total = self._progress() if not self.request.validate_only else (0, 0)
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
            "completed": completed,
            "total": total,
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
    label = request.label.strip() or _auto_label(request)
    args = [sys.executable, "scripts/run_eval.py", "--batch-id", batch_id]
    if request.validate_only:
        args.append("--validate-only")
    case_args, category_args = _effective_scope(request)
    if not request.validate_only and not case_args and not category_args:
        raise HTTPException(
            status_code=400,
            detail="所选范围只包含教学示例用例；请勾选「包含教学示例」或改选其他用例。",
        )
    for case in case_args:
        args += ["--case", case]
    for category in category_args:
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
    if label:
        args += ["--label", label]

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

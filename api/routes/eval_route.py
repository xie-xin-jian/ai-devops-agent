"""Evaluation report viewing API routes.

Reports are read from the local ``eval/reports`` directory written by
``scripts/run_eval.py``. All endpoints are read-only.
"""

import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from agent.platform.config import WORKDIR
from agent.platform.identity import AUDIT_VIEW, Principal
from api.auth import require_permissions

router = APIRouter()

_BATCH_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
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

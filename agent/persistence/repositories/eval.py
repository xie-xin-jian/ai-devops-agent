"""PostgreSQL repository for the agent evaluation dataset.

Evaluation rows live in the same database as the run they describe, so a
trial can be traced back to ``runs`` / ``run_usage`` / ``audit_events`` by
``run_id``. Batches are meant to be run against a throwaway database (or
schema) so a full suite can be reset by dropping it.
"""

from __future__ import annotations

import time

from sqlalchemy import case, delete as sql_delete, func, select

from agent.persistence.database import session_scope
from agent.persistence.models import (
    EvalBatchRecord,
    EvalScoreRecord,
    EvalToolCallRecord,
    EvalTrialRecord,
)


BATCH_STATUS_RUNNING = "running"
BATCH_STATUS_COMPLETED = "completed"
BATCH_STATUS_FAILED = "failed"
BATCH_STATUS_CANCELED = "canceled"

TRIAL_STATUS_RUNNING = "running"
TRIAL_STATUS_COMPLETED = "completed"
TRIAL_STATUS_FAILED = "failed"
TRIAL_STATUS_TIMEOUT = "timeout"

SCORE_PASS = "pass"
SCORE_FAIL = "fail"
SCORE_SKIP = "skip"
SCORE_ERROR = "error"


def _trial_to_dict(row: EvalTrialRecord) -> dict:
    return {
        "id": row.id,
        "batch_id": row.batch_id,
        "case_id": row.case_id,
        "category": row.category,
        "severity": row.severity,
        "topic": row.topic,
        "trial_no": row.trial_no,
        "status": row.status,
        "run_id": row.run_id,
        "session_id": row.session_id,
        "final_answer": row.final_answer,
        "error": row.error,
        "tool_calls": row.tool_calls,
        "input_tokens": row.input_tokens,
        "output_tokens": row.output_tokens,
        "cost_cny": row.cost_cny,
        "duration_ms": row.duration_ms,
        "approvals_requested": row.approvals_requested,
        "approvals_granted": row.approvals_granted,
        "trajectory": list(row.trajectory or []),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _batch_to_dict(row: EvalBatchRecord) -> dict:
    return {
        "id": row.id,
        "suite": row.suite,
        "label": row.label,
        "model_id": row.model_id,
        "trials_per_case": row.trials_per_case,
        "status": row.status,
        "total_cases": row.total_cases,
        "planned_trials": row.planned_trials,
        "config": dict(row.config or {}),
        "error": row.error,
        "created_at": row.created_at,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
    }


def create_batch(
    batch_id: str,
    *,
    suite: str = "smoke",
    label: str = "",
    model_id: str = "",
    trials_per_case: int = 1,
    total_cases: int = 0,
    planned_trials: int = 0,
    config: dict | None = None,
) -> dict:
    batch_id = str(batch_id or "")
    if not batch_id:
        raise ValueError("batch_id is required")
    now = time.time()
    with session_scope() as session:
        session.add(EvalBatchRecord(
            id=batch_id,
            suite=str(suite or "smoke")[:64],
            label=str(label or "")[:120],
            model_id=str(model_id or "")[:200],
            trials_per_case=max(1, int(trials_per_case or 1)),
            status=BATCH_STATUS_RUNNING,
            total_cases=max(0, int(total_cases or 0)),
            planned_trials=max(0, int(planned_trials or 0)),
            config=dict(config or {}),
            error="",
            created_at=now,
            started_at=now,
            finished_at=None,
        ))
    return fetch_batch(batch_id) or {}


def finish_batch(
    batch_id: str,
    *,
    status: str = BATCH_STATUS_COMPLETED,
    error: str = "",
) -> bool:
    batch_id = str(batch_id or "")
    if not batch_id:
        return False
    with session_scope() as session:
        row = session.get(EvalBatchRecord, batch_id)
        if row is None:
            return False
        row.status = str(status)
        row.error = str(error or "")
        row.finished_at = time.time()
    return True


def fetch_batch(batch_id: str) -> dict | None:
    batch_id = str(batch_id or "")
    if not batch_id:
        return None
    with session_scope() as session:
        row = session.get(EvalBatchRecord, batch_id)
        return _batch_to_dict(row) if row is not None else None


def list_batches(*, limit: int = 50) -> list[dict]:
    with session_scope() as session:
        rows = session.execute(
            select(EvalBatchRecord)
            .order_by(EvalBatchRecord.created_at.desc())
            .limit(max(1, int(limit)))
        ).scalars()
        return [_batch_to_dict(row) for row in rows]


def create_trial(
    *,
    batch_id: str,
    case_id: str,
    trial_no: int = 1,
    category: str = "",
    severity: str = "medium",
    topic: str = "",
    run_id: str = "",
    session_id: str = "",
) -> int:
    """Insert one trial row and return its id."""
    now = time.time()
    with session_scope() as session:
        row = EvalTrialRecord(
            batch_id=str(batch_id),
            case_id=str(case_id)[:120],
            category=str(category or "")[:32],
            severity=str(severity or "medium")[:16],
            topic=str(topic or "")[:64],
            trial_no=max(1, int(trial_no or 1)),
            status=TRIAL_STATUS_RUNNING,
            run_id=str(run_id or ""),
            session_id=str(session_id or ""),
            final_answer="",
            error="",
            tool_calls=0,
            input_tokens=0,
            output_tokens=0,
            cost_cny=0.0,
            duration_ms=0,
            approvals_requested=0,
            approvals_granted=0,
            trajectory=[],
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.flush()
        return int(row.id)


def update_trial(trial_id: int, **fields) -> bool:
    """Update the mutable fields of one trial."""
    allowed = {
        "status",
        "run_id",
        "session_id",
        "final_answer",
        "error",
        "tool_calls",
        "input_tokens",
        "output_tokens",
        "cost_cny",
        "duration_ms",
        "approvals_requested",
        "approvals_granted",
        "trajectory",
    }
    payload = {key: value for key, value in fields.items() if key in allowed}
    if not payload:
        return False
    with session_scope() as session:
        row = session.get(EvalTrialRecord, int(trial_id))
        if row is None:
            return False
        for key, value in payload.items():
            setattr(row, key, value)
        row.updated_at = time.time()
    return True


def add_tool_calls(trial_id: int, batch_id: str, case_id: str, calls: list[dict]) -> int:
    """Store the tool-call trail of one trial."""
    if not calls:
        return 0
    now = time.time()
    with session_scope() as session:
        trial = session.get(EvalTrialRecord, int(trial_id))
        if trial is not None:
            trial.tool_calls = len(calls)
            trial.updated_at = now
        for item in calls:
            session.add(EvalToolCallRecord(
                trial_id=int(trial_id),
                batch_id=str(batch_id),
                case_id=str(case_id)[:120],
                step=int(item.get("step") or 0),
                tool=str(item.get("tool") or "")[:120],
                arguments=dict(item.get("arguments") or {}),
                output=str(item.get("output") or ""),
                ok=bool(item.get("ok", True)),
                duration_ms=int(item.get("duration_ms") or 0),
                created_at=now,
            ))
    return len(calls)


def add_scores(trial_id: int, batch_id: str, case_id: str, scores: list[dict]) -> int:
    """Store rule results for one trial."""
    if not scores:
        return 0
    now = time.time()
    with session_scope() as session:
        for item in scores:
            session.add(EvalScoreRecord(
                trial_id=int(trial_id),
                batch_id=str(batch_id),
                case_id=str(case_id)[:120],
                rule=str(item.get("rule") or "")[:64],
                status=str(item.get("status") or SCORE_PASS)[:16],
                score=float(item.get("score") or 0.0),
                detail=str(item.get("detail") or ""),
                evidence=dict(item.get("evidence") or {}),
                created_at=now,
            ))
    return len(scores)


def fetch_trial(trial_id: int) -> dict | None:
    with session_scope() as session:
        row = session.get(EvalTrialRecord, int(trial_id))
        if row is None:
            return None
        trial = _trial_to_dict(row)
        trial["scores"] = _scores_for(session, [int(trial_id)]).get(int(trial_id), [])
        trial["tool_call_rows"] = _tool_calls_for(session, [int(trial_id)]).get(int(trial_id), [])
        return trial


def fetch_trials(batch_id: str, *, case_id: str | None = None) -> list[dict]:
    statement = select(EvalTrialRecord).where(
        EvalTrialRecord.batch_id == str(batch_id)
    )
    if case_id:
        statement = statement.where(EvalTrialRecord.case_id == str(case_id))
    statement = statement.order_by(
        EvalTrialRecord.case_id,
        EvalTrialRecord.trial_no,
    )
    with session_scope() as session:
        rows = list(session.execute(statement).scalars())
        ids = [int(row.id) for row in rows]
        scores = _scores_for(session, ids)
        calls = _tool_calls_for(session, ids)
        result = []
        for row in rows:
            item = _trial_to_dict(row)
            item["scores"] = scores.get(int(row.id), [])
            item["tool_call_rows"] = calls.get(int(row.id), [])
            result.append(item)
        return result


def _scores_for(session, trial_ids: list[int]) -> dict[int, list[dict]]:
    if not trial_ids:
        return {}
    rows = session.execute(
        select(EvalScoreRecord)
        .where(EvalScoreRecord.trial_id.in_(trial_ids))
        .order_by(EvalScoreRecord.id)
    ).scalars()
    grouped: dict[int, list[dict]] = {}
    for row in rows:
        grouped.setdefault(int(row.trial_id), []).append({
            "rule": row.rule,
            "status": row.status,
            "score": row.score,
            "detail": row.detail,
            "evidence": dict(row.evidence or {}),
        })
    return grouped


def _tool_calls_for(session, trial_ids: list[int]) -> dict[int, list[dict]]:
    if not trial_ids:
        return {}
    rows = session.execute(
        select(EvalToolCallRecord)
        .where(EvalToolCallRecord.trial_id.in_(trial_ids))
        .order_by(EvalToolCallRecord.trial_id, EvalToolCallRecord.step)
    ).scalars()
    grouped: dict[int, list[dict]] = {}
    for row in rows:
        grouped.setdefault(int(row.trial_id), []).append({
            "step": row.step,
            "tool": row.tool,
            "arguments": dict(row.arguments or {}),
            "output": row.output,
            "ok": bool(row.ok),
            "duration_ms": row.duration_ms,
        })
    return grouped


def batch_summary(batch_id: str) -> dict:
    """Aggregate one batch: pass rate, cost, latency, per category and tool."""
    batch = fetch_batch(batch_id)
    if batch is None:
        return {}

    with session_scope() as session:
        trials = list(session.execute(
            select(EvalTrialRecord).where(
                EvalTrialRecord.batch_id == str(batch_id)
            )
        ).scalars())
        ids = [int(row.id) for row in trials]
        failed_scores = {}
        if ids:
            rows = session.execute(
                select(
                    EvalScoreRecord.trial_id,
                    func.count(),
                )
                .where(
                    EvalScoreRecord.trial_id.in_(ids),
                    EvalScoreRecord.status.in_([SCORE_FAIL, SCORE_ERROR]),
                )
                .group_by(EvalScoreRecord.trial_id)
            ).all()
            failed_scores = {int(trial_id): int(count) for trial_id, count in rows}

        tool_stats = {}
        if ids:
            rows = session.execute(
                select(
                    EvalToolCallRecord.tool,
                    func.count(),
                    func.sum(case(
                        (EvalToolCallRecord.ok.is_(True), 1),
                        else_=0,
                    )),
                )
                .where(EvalToolCallRecord.trial_id.in_(ids))
                .group_by(EvalToolCallRecord.tool)
            ).all()
            tool_stats = {
                str(tool): {"calls": int(calls), "ok": int(ok or 0)}
                for tool, calls, ok in rows
            }

    completed = [row for row in trials if row.status == TRIAL_STATUS_COMPLETED]
    passed = [
        row for row in completed
        if failed_scores.get(int(row.id), 0) == 0
    ]
    by_category: dict[str, dict] = {}
    for row in trials:
        entry = by_category.setdefault(row.category or "unknown", {
            "trials": 0,
            "completed": 0,
            "passed": 0,
            "failed": 0,
            "cost_cny": 0.0,
            "duration_ms": 0,
        })
        entry["trials"] += 1
        entry["cost_cny"] += float(row.cost_cny or 0)
        entry["duration_ms"] += int(row.duration_ms or 0)
        if row.status == TRIAL_STATUS_COMPLETED:
            entry["completed"] += 1
            if failed_scores.get(int(row.id), 0) == 0:
                entry["passed"] += 1
            else:
                entry["failed"] += 1

    durations = sorted(int(row.duration_ms or 0) for row in completed)

    def percentile(values: list[int], ratio: float) -> int:
        if not values:
            return 0
        index = min(len(values) - 1, int(round((len(values) - 1) * ratio)))
        return values[index]

    return {
        "batch": batch,
        "trials": len(trials),
        "completed": len(completed),
        "passed": len(passed),
        "failed": sum(1 for row in completed if failed_scores.get(int(row.id), 0)),
        "pass_rate": (len(passed) / len(completed)) if completed else 0.0,
        "total_cost_cny": sum(float(row.cost_cny or 0) for row in trials),
        "avg_duration_ms": int(
            sum(durations) / len(durations)
        ) if durations else 0,
        "p50_duration_ms": percentile(durations, 0.5),
        "p95_duration_ms": percentile(durations, 0.95),
        "total_tool_calls": sum(int(row.tool_calls or 0) for row in trials),
        "by_category": by_category,
        "tools": tool_stats,
    }


def delete_batch(batch_id: str) -> bool:
    """Remove a batch (trials/scores cascade)."""
    batch_id = str(batch_id or "")
    if not batch_id:
        return False
    with session_scope() as session:
        trial_ids = [
            int(trial_id)
            for trial_id in session.execute(
                select(EvalTrialRecord.id).where(
                    EvalTrialRecord.batch_id == batch_id
                )
            ).scalars()
        ]
        if trial_ids:
            session.execute(
                sql_delete(EvalScoreRecord).where(
                    EvalScoreRecord.trial_id.in_(trial_ids)
                )
            )
            session.execute(
                sql_delete(EvalToolCallRecord).where(
                    EvalToolCallRecord.trial_id.in_(trial_ids)
                )
            )
            session.execute(
                sql_delete(EvalTrialRecord).where(
                    EvalTrialRecord.id.in_(trial_ids)
                )
            )
        result = session.execute(
            sql_delete(EvalBatchRecord).where(EvalBatchRecord.id == batch_id)
        )
        return bool(result.rowcount)


__all__ = [
    "BATCH_STATUS_CANCELED",
    "BATCH_STATUS_COMPLETED",
    "BATCH_STATUS_FAILED",
    "BATCH_STATUS_RUNNING",
    "SCORE_ERROR",
    "SCORE_FAIL",
    "SCORE_PASS",
    "SCORE_SKIP",
    "TRIAL_STATUS_COMPLETED",
    "TRIAL_STATUS_FAILED",
    "TRIAL_STATUS_RUNNING",
    "TRIAL_STATUS_TIMEOUT",
    "add_scores",
    "add_tool_calls",
    "batch_summary",
    "create_batch",
    "create_trial",
    "delete_batch",
    "fetch_batch",
    "fetch_trial",
    "fetch_trials",
    "finish_batch",
    "list_batches",
    "update_trial",
]

"""PostgreSQL repository for per-call LLM token usage."""

from __future__ import annotations

import time

from sqlalchemy import delete as sql_delete

from agent.persistence.database import session_scope
from agent.persistence.models import RunUsageRecord


def persist_run_usage(
    *,
    run_id: str,
    session_id: str = "",
    turn: int = 0,
    model_id: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    estimated_cost_cny: float = 0.0,
) -> bool:
    if not run_id:
        return False
    with session_scope() as session:
        session.add(RunUsageRecord(
            run_id=str(run_id),
            session_id=str(session_id or ""),
            turn=max(0, int(turn or 0)),
            model_id=str(model_id or ""),
            input_tokens=max(0, int(input_tokens or 0)),
            output_tokens=max(0, int(output_tokens or 0)),
            cache_read_tokens=max(0, int(cache_read_tokens or 0)),
            cache_write_tokens=max(0, int(cache_write_tokens or 0)),
            estimated_cost_cny=max(0.0, float(estimated_cost_cny or 0.0)),
            created_at=time.time(),
        ))
    return True


def delete_run_usage(run_id: str) -> int:
    """Remove every mirrored usage row of a run (mirror maintenance only)."""
    run_id = str(run_id or "")
    if not run_id:
        return 0
    with session_scope() as session:
        result = session.execute(
            sql_delete(RunUsageRecord).where(RunUsageRecord.run_id == run_id)
        )
        return int(result.rowcount or 0)


__all__ = ["delete_run_usage", "persist_run_usage"]

"""Session and interrupted-run recovery API routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from agent.platform.identity import AGENT_CHAT, SESSION_MANAGE, Principal
from agent.sessions.state_store import (
    RUN_STATUS_CANCELED,
    RUN_STATUS_FAILED,
    RUN_STATUS_INTERRUPTED,
    RUN_STATUS_RUNNING,
    RecoveryStore,
)
from api.auth import require_permissions


router = APIRouter()

RESUMABLE_STATUSES = {
    RUN_STATUS_INTERRUPTED,
    RUN_STATUS_FAILED,
    RUN_STATUS_CANCELED,
}


def _can_access(principal: Principal, run: dict) -> bool:
    return (
        principal.has(SESSION_MANAGE)
        or not run.get("owner_id")
        or run.get("owner_id") == principal.id
    )


def _summary(run: dict) -> dict:
    return {
        "run_id": run.get("run_id", ""),
        "session_id": run.get("session_id", ""),
        "owner_id": run.get("owner_id", ""),
        "source": run.get("source", "chat"),
        "status": run.get("status", ""),
        "phase": run.get("phase", ""),
        "user_message": run.get("user_message", ""),
        "safe_to_resume": bool(run.get("safe_to_resume")),
        "active_tool": run.get("active_tool", ""),
        "interruption_reason": run.get("interruption_reason", ""),
        "resume_count": int(run.get("resume_count") or 0),
        "message_count": int(
            run.get("message_count")
            or len(run.get("messages") or [])
        ),
        "created_at": float(run.get("created_at") or 0),
        "updated_at": float(run.get("updated_at") or 0),
        "finished_at": run.get("finished_at"),
    }


@router.get("/runs")
async def list_recovery_runs(
    session_id: str | None = None,
    status: str | None = None,
    include_completed: bool = False,
    limit: int = 100,
    principal: Principal = Depends(require_permissions(AGENT_CHAT)),
):
    owner_id = None if principal.has(SESSION_MANAGE) else principal.id
    if status:
        statuses = {status}
    elif include_completed:
        statuses = None
    else:
        statuses = {
            RUN_STATUS_RUNNING,
            RUN_STATUS_INTERRUPTED,
            RUN_STATUS_FAILED,
            RUN_STATUS_CANCELED,
        }
    runs = RecoveryStore().list_runs(
        owner_id=owner_id,
        session_id=session_id,
        statuses=statuses,
        limit=limit,
    )
    return {"runs": [_summary(run) for run in runs]}


@router.get("/runs/{run_id}")
async def get_recovery_run(
    run_id: str,
    principal: Principal = Depends(require_permissions(AGENT_CHAT)),
):
    run = RecoveryStore().get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if not _can_access(principal, run):
        raise HTTPException(status_code=403, detail="Permission denied")
    return _summary(run)


@router.post("/runs/{run_id}/resume/stream")
async def resume_recovery_run(
    run_id: str,
    principal: Principal = Depends(require_permissions(AGENT_CHAT)),
):
    from api.main import get_or_create_session

    store = RecoveryStore()
    run = store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if not _can_access(principal, run):
        raise HTTPException(status_code=403, detail="Permission denied")
    if run.get("status") not in RESUMABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Run status is {run.get('status')}",
        )
    if not run.get("safe_to_resume"):
        raise HTTPException(
            status_code=409,
            detail=(
                run.get("interruption_reason")
                or "Run has no safe point to resume from"
            ),
        )

    _, session = get_or_create_session(
        run.get("session_id", ""),
        principal,
    )
    store.mark_resumed(run_id)

    def event_generator():
        with session["run_lock"]:
            session["cancel_event"].clear()
            for event in session["agent"].resume_stream(
                run_id,
                run.get("messages", []),
                session["cancel_event"],
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "session-id": run.get("session_id", ""),
            "run-id": run_id,
        },
    )

"""Run checkpoint query and resume API routes."""

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from agent.rbac import (
    AGENT_CHAT,
    AUDIT_VIEW,
    SESSION_MANAGE,
    Principal,
)
from agent.run_checkpoint import (
    PHASE_ACTION_SELECTED,
    STATUS_CANCELED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_INTERRUPTED,
    STATUS_RUNNING,
    STATUS_WAITING_APPROVAL,
    RunCheckpointStore,
)
from api.auth import require_permissions


router = APIRouter()

_RESUMABLE_STATUSES = {
    STATUS_RUNNING,
    STATUS_INTERRUPTED,
    STATUS_FAILED,
}


def _can_access(principal: Principal, checkpoint) -> bool:
    if principal.has(SESSION_MANAGE) or principal.has(AUDIT_VIEW):
        return True
    return bool(
        checkpoint.owner_id
        and checkpoint.owner_id == principal.id
    )


@router.get("/")
async def list_runs(
    session_id: str | None = None,
    status: str | None = None,
    principal: Principal = Depends(require_permissions(AGENT_CHAT)),
):
    runs = RunCheckpointStore().list(
        session_id=session_id,
        status=status,
    )
    if not (
        principal.has(SESSION_MANAGE)
        or principal.has(AUDIT_VIEW)
    ):
        runs = [
            run for run in runs
            if run.owner_id == principal.id
        ]
    return {"runs": [run.to_dict() for run in runs]}


@router.get("/{run_id}")
async def get_run(
    run_id: str,
    principal: Principal = Depends(require_permissions(AGENT_CHAT)),
):
    checkpoint = RunCheckpointStore().get(run_id)
    if checkpoint is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if not _can_access(principal, checkpoint):
        raise HTTPException(status_code=403, detail="Permission denied")
    return checkpoint.to_dict()


@router.post("/{run_id}/resume/stream")
async def resume_run_stream(
    run_id: str,
    principal: Principal = Depends(require_permissions(AGENT_CHAT)),
):
    from api.main import get_or_create_session

    store = RunCheckpointStore()
    checkpoint = store.get(run_id)
    if checkpoint is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if not _can_access(principal, checkpoint):
        raise HTTPException(status_code=403, detail="Permission denied")
    if checkpoint.status not in _RESUMABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Run status is {checkpoint.status}",
        )

    _, session = get_or_create_session(
        checkpoint.session_id,
        principal,
    )
    checkpoint.status = STATUS_RUNNING
    checkpoint.phase = PHASE_ACTION_SELECTED
    checkpoint.resume_count += 1
    store.save(checkpoint)

    def event_generator():
        with session["run_lock"]:
            session["cancel_event"].clear()
            for event in session["agent"].resume_stream(
                checkpoint,
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
            "session-id": checkpoint.session_id,
            "run-id": checkpoint.run_id,
        },
    )

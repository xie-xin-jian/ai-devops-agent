"""Audit event and run timeline API routes."""

from fastapi import APIRouter, Depends

from agent.observability.audit import AuditStore
from agent.platform.identity import AUDIT_VIEW, Principal
from api.auth import require_permissions


router = APIRouter()


@router.get("/events")
async def list_audit_events(
    session_id: str | None = None,
    run_id: str | None = None,
    action_id: str | None = None,
    event_type: str | None = None,
    limit: int = 200,
    _principal: Principal = Depends(require_permissions(AUDIT_VIEW)),
):
    events = AuditStore().list_events(
        session_id=session_id,
        run_id=run_id,
        action_id=action_id,
        event_type=event_type,
        limit=limit,
    )
    return {"events": [event.to_dict() for event in events]}


@router.get("/timeline")
async def session_timeline(
    session_id: str,
    limit: int = 500,
    _principal: Principal = Depends(require_permissions(AUDIT_VIEW)),
):
    events = AuditStore().list_events(
        session_id=session_id,
        limit=limit,
    )
    ordered = list(reversed(events))
    return {
        "session_id": session_id,
        "events": [event.to_dict() for event in ordered],
        "summary": {
            "total": len(ordered),
            "failed": sum(
                1 for event in ordered
                if event.result == "failed"
            ),
            "blocked": sum(
                1 for event in ordered
                if event.result == "blocked"
            ),
        },
    }


@router.get("/runs/{run_id}")
async def run_trace(
    run_id: str,
    _principal: Principal = Depends(require_permissions(AUDIT_VIEW)),
):
    events = AuditStore().get_run_trace(run_id)
    return {
        "run_id": run_id,
        "events": [event.to_dict() for event in events],
    }

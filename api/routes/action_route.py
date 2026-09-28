"""Pending action and preflight API routes."""

from fastapi import APIRouter, Depends, HTTPException

from agent.rbac import (
    ACTION_APPROVE,
    AGENT_CHAT,
    AUDIT_VIEW,
    SESSION_MANAGE,
    Principal,
)
from agent.pending_actions import (
    PendingActionStore,
    get_action_preflight_contract,
)
from agent.audit import (
    RESULT_CANCELED,
    RESULT_SUCCESS,
    SEVERITY_INFO,
    record_event,
)
from api.auth import require_permissions
from api.schemas import (
    PendingActionCancelRequest,
    PendingActionConfirmRequest,
)


router = APIRouter()


def _can_access_action(principal: Principal, action) -> bool:
    if principal.has(SESSION_MANAGE) or principal.has(AUDIT_VIEW):
        return True
    return bool(action.owner_id and action.owner_id == principal.id)


@router.get("/preflight/{action_code}")
async def action_preflight(
    action_code: str,
    message: str = "",
    _principal: Principal = Depends(require_permissions(AGENT_CHAT)),
):
    try:
        result = get_action_preflight_contract(
            action_code,
            {"source_message": message},
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result.to_dict()


@router.get("/pending")
async def list_pending_actions(
    session_id: str | None = None,
    status: str | None = None,
    principal: Principal = Depends(require_permissions(AGENT_CHAT)),
):
    actions = PendingActionStore().list(
        session_id=session_id,
        status=status,
    )
    if not (
        principal.has(SESSION_MANAGE)
        or principal.has(AUDIT_VIEW)
    ):
        actions = [
            action for action in actions
            if action.owner_id == principal.id
        ]
    return {"actions": [item.to_dict() for item in actions]}


@router.get("/pending/{action_id}")
async def get_pending_action(
    action_id: str,
    principal: Principal = Depends(require_permissions(AGENT_CHAT)),
):
    action = PendingActionStore().get(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Pending action not found")
    if not _can_access_action(principal, action):
        raise HTTPException(status_code=403, detail="Permission denied")
    return action.to_dict()


@router.post("/pending/{action_id}/confirm")
async def confirm_pending_action(
    action_id: str,
    payload: PendingActionConfirmRequest | None = None,
    principal: Principal = Depends(require_permissions(ACTION_APPROVE)),
):
    actor = principal.id
    try:
        store = PendingActionStore()
        current = store.get(action_id)
        if current is None:
            raise KeyError(action_id)
        if not _can_access_action(principal, current):
            raise HTTPException(status_code=403, detail="Permission denied")
        action = store.confirm(action_id, actor=actor)
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="Pending action not found",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    record_event(
        "pending_action.confirmed",
        f"Pending action confirmed: {action_id}",
        summary=action.summary,
        result=RESULT_SUCCESS,
        severity=SEVERITY_INFO,
        actor=actor,
        session_id=action.session_id,
        action_id=action.id,
        action_code=action.action_code,
        risk_level=action.risk_level,
        correlation_id=action.id,
        payload={
            "confirmed_at": action.confirmed_at,
            "execution_enabled": False,
        },
    )
    return action.to_dict()


@router.post("/pending/{action_id}/cancel")
async def cancel_pending_action(
    action_id: str,
    payload: PendingActionCancelRequest | None = None,
    principal: Principal = Depends(require_permissions(ACTION_APPROVE)),
):
    actor = principal.id
    reason = payload.reason if payload else ""
    try:
        store = PendingActionStore()
        current = store.get(action_id)
        if current is None:
            raise KeyError(action_id)
        if not _can_access_action(principal, current):
            raise HTTPException(status_code=403, detail="Permission denied")
        action = store.cancel(
            action_id,
            actor=actor,
            reason=reason,
        )
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="Pending action not found",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    record_event(
        "pending_action.canceled",
        f"Pending action canceled: {action_id}",
        summary=reason,
        result=RESULT_CANCELED,
        severity=SEVERITY_INFO,
        actor=actor,
        session_id=action.session_id,
        action_id=action.id,
        action_code=action.action_code,
        risk_level=action.risk_level,
        correlation_id=action.id,
        payload={"reason": reason, "canceled_at": action.canceled_at},
    )
    return action.to_dict()

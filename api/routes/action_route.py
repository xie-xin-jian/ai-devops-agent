"""Pending action API routes."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool

from agent.platform.identity import (
    ACTION_APPROVE,
    AGENT_CHAT,
    AUDIT_VIEW,
    SESSION_MANAGE,
    Principal,
)
from agent.orchestration.pending_actions import (
    PendingActionStore,
    STATUS_EXECUTED,
    STATUS_FAILED,
)
from agent.orchestration.pending_executor import execute_pending_action
from agent.orchestration.pending_executor import (
    build_approval_continuation_message,
)
from agent.observability.audit import (
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


async def _continue_session_after_approval(
    action,
    result: dict,
    principal: Principal,
) -> str:
    """Return the approved result to the originating Session and continue it."""
    if not action.session_id:
        return ""

    from api.main import get_or_create_session

    _, session = get_or_create_session(action.session_id, principal)
    message = build_approval_continuation_message(action, result)

    def _run_continuation():
        with session["run_lock"]:
            session["cancel_event"].clear()
            return session["agent"].run(
                message,
                session["cancel_event"],
            )

    return await run_in_threadpool(_run_continuation)


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
        try:
            result = await run_in_threadpool(
                execute_pending_action,
                action,
                principal,
            )
            try:
                assistant_response = await _continue_session_after_approval(
                    action,
                    result,
                    principal,
                )
                if assistant_response:
                    result["assistant_response"] = assistant_response
            except Exception as continuation_error:
                result["continuation_error"] = str(continuation_error)
            action = store.finish(
                action_id,
                status=(
                    STATUS_EXECUTED
                    if result.get("success")
                    else STATUS_FAILED
                ),
                result_payload=result,
            )
        except Exception as exc:
            action = store.finish(
                action_id,
                status=STATUS_FAILED,
                result_payload={
                    "execution_enabled": True,
                    "success": False,
                    "error": str(exc),
                },
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
    if action.status == STATUS_EXECUTED:
        event_type = "pending_action.executed"
        event_title = f"Pending action executed: {action_id}"
        event_result = RESULT_SUCCESS
        event_severity = SEVERITY_INFO
    elif action.status == STATUS_FAILED:
        event_type = "pending_action.execution_failed"
        event_title = f"Pending action execution failed: {action_id}"
        event_result = "failed"
        event_severity = "high"
    else:
        event_type = "pending_action.confirmed"
        event_title = f"Pending action confirmed: {action_id}"
        event_result = RESULT_SUCCESS
        event_severity = SEVERITY_INFO
    record_event(
        event_type,
        event_title,
        summary=action.summary,
        result=event_result,
        severity=event_severity,
        actor=actor,
        session_id=action.session_id,
        action_id=action.id,
        action_code=action.action_code,
        risk_level=action.risk_level,
        correlation_id=action.id,
        payload={
            "confirmed_at": action.confirmed_at,
            "execution_enabled": bool(
                action.result_payload.get("execution_enabled")
            ),
            "success": action.result_payload.get("success"),
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

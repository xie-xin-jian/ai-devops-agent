"""Project target configuration and activation routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from agent.platform.identity import (
    AGENT_CHAT,
    SESSION_MANAGE,
    Principal,
)
from agent.sessions.state_store import RecoveryStore
from agent.targets.service import browse_directories
from agent.targets.store import TargetStore
from api.auth import require_permissions
from api.schemas import (
    TargetActivateRequest,
    TargetCreateRequest,
    TargetUpdateRequest,
)


router = APIRouter()


def _get_target_or_404(target_id: str):
    target = TargetStore().get(target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Target not found")
    return target


@router.get("/browse")
async def browse_target_directories(
    path: str = "",
    _principal: Principal = Depends(require_permissions(AGENT_CHAT)),
):
    try:
        return browse_directories(path or None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/")
async def list_targets(
    session_id: str = "",
    _principal: Principal = Depends(require_permissions(AGENT_CHAT)),
):
    targets = TargetStore().list()
    active_target_id = ""
    if session_id:
        session = RecoveryStore().get_session(session_id)
        if session:
            active_target_id = str(session.get("target_id") or "")
    return {
        "targets": [target.to_dict() for target in targets],
        "active_target_id": active_target_id,
    }


@router.post("/")
async def create_target(
    payload: TargetCreateRequest,
    principal: Principal = Depends(require_permissions(SESSION_MANAGE)),
):
    try:
        target = TargetStore().create(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return target.to_dict()


@router.get("/{target_id}")
async def get_target(
    target_id: str,
    _principal: Principal = Depends(require_permissions(AGENT_CHAT)),
):
    return _get_target_or_404(target_id).to_dict()


@router.patch("/{target_id}")
async def update_target(
    target_id: str,
    payload: TargetUpdateRequest,
    _principal: Principal = Depends(require_permissions(SESSION_MANAGE)),
):
    try:
        target = TargetStore().update(target_id, payload.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Target not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return target.to_dict()


@router.delete("/{target_id}")
async def delete_target(
    target_id: str,
    _principal: Principal = Depends(require_permissions(SESSION_MANAGE)),
):
    try:
        TargetStore().delete(target_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Target not found") from exc
    return {"status": "deleted", "target_id": target_id}


@router.post("/{target_id}/activate")
async def activate_target(
    target_id: str,
    payload: TargetActivateRequest | None = None,
    principal: Principal = Depends(require_permissions(AGENT_CHAT)),
):
    _get_target_or_404(target_id)
    from api.main import get_or_create_session

    session_id = payload.session_id if payload else None
    _, session = get_or_create_session(session_id, principal)
    from api.main import _session_manager

    result = _session_manager.activate_target(
        session["agent"].session_id,
        target_id,
        principal,
    )
    return {**result, "target": _get_target_or_404(target_id).to_dict()}

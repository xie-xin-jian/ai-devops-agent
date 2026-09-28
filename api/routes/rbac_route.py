"""RBAC identity and catalog API routes."""

from fastapi import APIRouter, Depends

from agent.rbac import (
    AGENT_CHAT,
    SESSION_MANAGE,
    Principal,
    get_permission_catalog,
    get_role_catalog,
)
from api.auth import get_request_principal, require_permissions


router = APIRouter()


@router.get("/me")
async def current_principal(
    principal: Principal = Depends(get_request_principal),
):
    return principal.to_dict()


@router.get("/permissions")
async def permission_catalog(
    _principal: Principal = Depends(require_permissions(AGENT_CHAT)),
):
    return {"permissions": get_permission_catalog()}


@router.get("/roles")
async def role_catalog(
    _principal: Principal = Depends(require_permissions(SESSION_MANAGE)),
):
    return {"roles": get_role_catalog()}

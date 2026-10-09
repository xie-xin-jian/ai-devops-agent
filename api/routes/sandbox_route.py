"""Active Docker Sandbox status API routes."""

from fastapi import APIRouter, Depends

from agent.platform.identity import AGENT_CHAT, SESSION_MANAGE, Principal
from agent.sandbox.manager import list_sandbox_sessions
from api.auth import require_permissions


router = APIRouter()


@router.get("/")
async def list_sandboxes(
    principal: Principal = Depends(require_permissions(AGENT_CHAT)),
):
    active = list_sandbox_sessions()
    if not principal.has(SESSION_MANAGE):
        active = [
            item for item in active
            if item.get("owner_id") == principal.id
        ]
    return {
        "active": active,
    }

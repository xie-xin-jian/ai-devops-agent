"""Active and checkpointed Sandbox status API routes."""

from fastapi import APIRouter, Depends

from agent.rbac import (
    AGENT_CHAT,
    AUDIT_VIEW,
    SESSION_MANAGE,
    Principal,
)
from agent.run_checkpoint import RunCheckpointStore
from agent.sandbox import list_sandbox_sessions
from api.auth import require_permissions


router = APIRouter()


@router.get("/")
async def list_sandboxes(
    principal: Principal = Depends(require_permissions(AGENT_CHAT)),
):
    active = list_sandbox_sessions()
    if not (
        principal.has(AUDIT_VIEW)
        or principal.has(SESSION_MANAGE)
    ):
        active = [
            item for item in active
            if item.get("owner_id") == principal.id
        ]

    checkpointed = []
    for checkpoint in RunCheckpointStore().list():
        if not checkpoint.sandbox_workspace:
            continue
        if not (
            principal.has(AUDIT_VIEW)
            or principal.has(SESSION_MANAGE)
            or checkpoint.owner_id == principal.id
        ):
            continue
        checkpointed.append({
            "run_id": checkpoint.run_id,
            "source": checkpoint.source,
            "status": "checkpointed",
            "workspace_host_path": checkpoint.sandbox_workspace,
            "updated_at": checkpoint.updated_at,
        })
    return {
        "active": active,
        "checkpointed": checkpointed,
    }

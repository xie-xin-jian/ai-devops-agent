"""Governed long-term memory API routes."""

from fastapi import APIRouter, Depends, HTTPException

from agent.audit import (
    RESULT_SUCCESS,
    SEVERITY_INFO,
    record_event,
)
from agent.memory import MemorySystem
from agent.memory_policy import can_manage_record, can_read_scope
from agent.rbac import (
    ACTION_APPROVE,
    MEMORY_MANAGE,
    MEMORY_READ,
    Principal,
)
from api.auth import require_permissions


router = APIRouter()


def _visible_memory(principal: Principal, memory: dict, session_id: str = "") -> bool:
    return can_read_scope(
        principal,
        memory.get("scope", "global"),
        owner_id=memory.get("owner_id", ""),
        session_id=session_id,
    )


@router.get("/")
async def list_memories(
    scope: str | None = None,
    status: str | None = None,
    session_id: str = "",
    principal: Principal = Depends(require_permissions(MEMORY_READ)),
):
    if scope and not can_read_scope(
        principal,
        scope,
        session_id=session_id,
    ):
        raise HTTPException(status_code=403, detail="Permission denied")
    memories = [
        memory
        for memory in MemorySystem().memories
        if (not scope or memory.get("scope", "global") == scope)
        and (not status or memory.get("status", "active") == status)
        and _visible_memory(principal, memory, session_id=session_id)
    ]
    return {"memories": memories, "count": len(memories)}


@router.get("/{memory_id}")
async def get_memory(
    memory_id: str,
    session_id: str = "",
    principal: Principal = Depends(require_permissions(MEMORY_READ)),
):
    memory = MemorySystem().get(memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    if not _visible_memory(principal, memory, session_id=session_id):
        raise HTTPException(status_code=403, detail="Permission denied")
    return memory


@router.post("/{memory_id}/approve")
async def approve_memory(
    memory_id: str,
    session_id: str = "",
    principal: Principal = Depends(
        require_permissions(MEMORY_MANAGE, ACTION_APPROVE)
    ),
):
    system = MemorySystem()
    memory = system.get(memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    if not can_manage_record(
        principal,
        memory,
        session_id=session_id,
    ):
        raise HTTPException(status_code=403, detail="Permission denied")
    if memory.get("status") != "candidate":
        raise HTTPException(
            status_code=409,
            detail="Memory is not a candidate",
        )
    approved = system.approve(memory_id)
    record_event(
        "memory.approved",
        f"Memory approved: {memory_id}",
        summary=approved.get("content", "")[:300],
        result=RESULT_SUCCESS,
        severity=SEVERITY_INFO,
        actor=principal.id,
        session_id=approved.get("session_id", ""),
        action_code="memory.manage",
        risk_level="medium",
        correlation_id=memory_id,
        payload={
            "memory_id": memory_id,
            "scope": approved.get("scope", ""),
            "owner_id": approved.get("owner_id", ""),
        },
    )
    return approved

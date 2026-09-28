"""Unified run identity shared by chat, task, cron, background, and MCP."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from agent.rbac import Principal, system_admin_principal
from agent.run_checkpoint import (
    PHASE_INITIALIZED,
    STATUS_RUNNING,
    RunCheckpoint,
    RunCheckpointStore,
)


@dataclass(frozen=True)
class RunContext:
    run_id: str
    source: str
    session_id: str
    owner_id: str
    principal: Principal
    parent_run_id: str = ""
    resource_id: str = ""
    metadata: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "source": self.source,
            "session_id": self.session_id,
            "owner_id": self.owner_id,
            "parent_run_id": self.parent_run_id,
            "resource_id": self.resource_id,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
        }


def create_run_context(
    *,
    source: str,
    session_id: str = "",
    owner_id: str = "",
    principal: Principal | None = None,
    parent_run_id: str = "",
    resource_id: str = "",
    metadata: dict | None = None,
) -> RunContext:
    principal = principal or system_admin_principal()
    return RunContext(
        run_id=f"run_{uuid.uuid4().hex}",
        source=str(source or "chat"),
        session_id=str(session_id or ""),
        owner_id=str(owner_id or principal.id),
        principal=principal,
        parent_run_id=str(parent_run_id or ""),
        resource_id=str(resource_id or ""),
        metadata=dict(metadata or {}),
    )


def initialize_checkpoint(
    context: RunContext,
    *,
    user_message: str = "",
    store: RunCheckpointStore | None = None,
) -> RunCheckpoint:
    checkpoint = RunCheckpoint(
        run_id=context.run_id,
        session_id=context.session_id,
        owner_id=context.owner_id,
        source=context.source,
        parent_run_id=context.parent_run_id,
        resource_id=context.resource_id,
        status=STATUS_RUNNING,
        phase=PHASE_INITIALIZED,
        user_message=user_message,
        metadata=dict(context.metadata),
    )
    return (store or RunCheckpointStore()).save(checkpoint)


__all__ = [
    "RunContext",
    "create_run_context",
    "initialize_checkpoint",
]

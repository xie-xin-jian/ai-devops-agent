"""Sandbox workspace models and errors."""

from __future__ import annotations

from dataclasses import asdict, dataclass


class SandboxError(RuntimeError):
    pass


class SandboxUnavailable(SandboxError):
    pass


@dataclass
class SandboxSession:
    id: str
    run_id: str
    workspace_host_path: str
    created_at: float
    status: str = "ready"
    owner_id: str = ""
    source: str = "chat"

    def to_dict(self) -> dict:
        return asdict(self)


__all__ = [
    "SandboxError",
    "SandboxSession",
    "SandboxUnavailable",
]

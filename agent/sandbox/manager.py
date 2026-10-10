"""Isolated temporary workspace manager."""

from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

import agent.platform.config as config
from agent.sandbox.cleanup import cleanup_orphan_sandboxes
from agent.sandbox.models import (
    SandboxError,
    SandboxSession,
    SandboxUnavailable,
)
from agent.sandbox.workspace import SandboxWorkspaceMixin
from agent.tools.file_tools import run_edit, run_glob, run_read, run_write


_active_sandboxes: dict[str, dict] = {}
_active_sandboxes_lock = threading.Lock()


def list_sandbox_sessions() -> list[dict]:
    with _active_sandboxes_lock:
        return [
            dict(item)
            for item in sorted(
                _active_sandboxes.values(),
                key=lambda value: value.get("created_at", 0),
                reverse=True,
            )
        ]


class SandboxManager(SandboxWorkspaceMixin):
    def __init__(
        self,
        *,
        base_dir: str | Path | None = None,
        enabled: bool | None = None,
    ):
        self.base_dir = Path(base_dir or config.SANDBOX_DIR)
        self.enabled = config.SANDBOX_ENABLED if enabled is None else enabled
        self._sessions: dict[str, SandboxSession] = {}

    def get(self, run_id: str) -> SandboxSession | None:
        return self._sessions.get(run_id)

    def create(
        self,
        run_id: str,
        *,
        source_workspace: str | Path | None = None,
        reuse_existing_workspace: bool = False,
        owner_id: str = "",
        source: str = "chat",
    ) -> SandboxSession:
        if not self.enabled:
            raise SandboxUnavailable("Sandbox workspace is disabled")
        existing = self._sessions.get(run_id)
        if existing is not None:
            return existing

        workspace = self._workspace_path(run_id)
        self._prepare_workspace(
            workspace,
            source_workspace,
            reuse_existing=reuse_existing_workspace,
        )
        sandbox_id = f"sbox_{uuid.uuid4().hex}"

        session = SandboxSession(
            id=sandbox_id,
            run_id=run_id,
            workspace_host_path=str(workspace),
            created_at=time.time(),
            owner_id=str(owner_id or ""),
            source=str(source or "chat"),
        )
        self._sessions[run_id] = session
        with _active_sandboxes_lock:
            _active_sandboxes[run_id] = session.to_dict()
        return session

    def read_file(
        self,
        run_id: str,
        path: str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> str:
        session = self._require_session(run_id)
        return run_read(
            path,
            limit=limit,
            offset=offset,
            cwd=Path(session.workspace_host_path),
        )

    def write_file(self, run_id: str, path: str, content: str) -> str:
        session = self._require_session(run_id)
        return run_write(
            path,
            content,
            cwd=Path(session.workspace_host_path),
        )

    def edit_file(
        self,
        run_id: str,
        path: str,
        old_text: str,
        new_text: str,
    ) -> str:
        session = self._require_session(run_id)
        return run_edit(
            path,
            old_text,
            new_text,
            cwd=Path(session.workspace_host_path),
        )

    def glob(self, run_id: str, pattern: str) -> str:
        session = self._require_session(run_id)
        return run_glob(
            pattern,
            cwd=Path(session.workspace_host_path),
        )

    def cleanup(self, run_id: str, *, remove_workspace: bool = True) -> None:
        session = self._sessions.pop(run_id, None)
        if session is not None:
            session.status = "removed"
            if remove_workspace:
                self._remove_workspace(Path(session.workspace_host_path))
        with _active_sandboxes_lock:
            _active_sandboxes.pop(run_id, None)

    def _require_session(self, run_id: str) -> SandboxSession:
        session = self._sessions.get(run_id)
        if session is None:
            raise SandboxUnavailable("Sandbox workspace is not active")
        return session


__all__ = [
    "SandboxError",
    "SandboxManager",
    "SandboxSession",
    "SandboxUnavailable",
    "cleanup_orphan_sandboxes",
    "list_sandbox_sessions",
]

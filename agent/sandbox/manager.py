"""Sandbox manager and public compatibility exports."""

from __future__ import annotations

import concurrent.futures
import threading
import time
import uuid
from pathlib import Path

import agent.platform.config as config
from agent.sandbox.backend import (
    ContainerHandle,
    DockerBackend,
    SandboxBackend,
    SandboxError,
    SandboxSession,
    SandboxSpec,
    SandboxTimeout,
    SandboxUnavailable,
)
from agent.sandbox.cleanup import cleanup_orphan_sandboxes
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
        backend: SandboxBackend | None = None,
        base_dir: str | Path | None = None,
        enabled: bool | None = None,
    ):
        self.backend = backend or DockerBackend()
        self.base_dir = Path(base_dir or config.SANDBOX_DIR)
        self.enabled = config.SANDBOX_ENABLED if enabled is None else enabled
        self.spec = SandboxSpec(
            image=config.SANDBOX_IMAGE,
            user=config.SANDBOX_USER,
            memory_limit=config.SANDBOX_MEMORY_LIMIT,
            nano_cpus=int(config.SANDBOX_CPUS * 1_000_000_000),
            pids_limit=config.SANDBOX_PIDS_LIMIT,
            network_disabled=config.SANDBOX_NETWORK_DISABLED,
            timeout_seconds=config.SANDBOX_TIMEOUT_SECONDS,
        )
        self._sessions: dict[str, SandboxSession] = {}
        self._handles: dict[str, ContainerHandle] = {}

    def available(self) -> bool:
        if not self.enabled:
            return False
        try:
            return self.backend.ping()
        except Exception:
            return False

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
            raise SandboxUnavailable("Docker sandbox is disabled")
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
        name = f"ai-devops-{run_id[:24]}-{uuid.uuid4().hex[:6]}"
        labels = {
            "managed-by": "ai-devops-agent",
            "run-id": run_id,
            "sandbox-id": sandbox_id,
        }
        try:
            handle = self.backend.create(
                name=name,
                spec=self.spec,
                workspace_host_path=str(workspace),
                labels=labels,
            )
        except Exception:
            self._remove_workspace(workspace)
            raise

        session = SandboxSession(
            id=sandbox_id,
            run_id=run_id,
            container_id=handle.id,
            image=self.spec.image,
            workspace_host_path=str(workspace),
            workspace_container_path="/workspace",
            created_at=time.time(),
            owner_id=str(owner_id or ""),
            source=str(source or "chat"),
        )
        self._sessions[run_id] = session
        self._handles[run_id] = handle
        with _active_sandboxes_lock:
            _active_sandboxes[run_id] = session.to_dict()
        return session

    def run(
        self,
        run_id: str,
        command: str,
        *,
        cwd: str | None = None,
        timeout_seconds: int | None = None,
    ) -> str:
        session = self._sessions.get(run_id)
        handle = self._handles.get(run_id)
        if session is None or handle is None:
            raise SandboxUnavailable("Sandbox session is not running")
        if not str(command or "").strip():
            return "Error: command is required"

        timeout = timeout_seconds or self.spec.timeout_seconds
        container_cwd = self._container_workdir(cwd)
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(
            handle.exec,
            command,
            container_cwd,
            timeout,
        )
        try:
            exit_code, output = future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            session.status = "timed_out"
            try:
                handle.kill()
            except Exception:
                pass
            raise SandboxTimeout(f"Sandbox command timed out after {timeout}s") from exc
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        if not output:
            output = "(no output)"
        prefix = f"exit_code={exit_code}\n"
        return (prefix + output)[:50000]

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
        handle = self._handles.pop(run_id, None)
        if handle is not None:
            try:
                handle.remove(force=True)
            except Exception:
                pass
        if session is not None:
            session.status = "removed"
            if remove_workspace:
                self._remove_workspace(Path(session.workspace_host_path))
        with _active_sandboxes_lock:
            _active_sandboxes.pop(run_id, None)

    def cleanup_all(self) -> None:
        for run_id in list(self._sessions):
            self.cleanup(run_id)

    def _require_session(self, run_id: str) -> SandboxSession:
        session = self._sessions.get(run_id)
        if session is None:
            raise SandboxUnavailable("Sandbox session is not running")
        return session


__all__ = [
    "DockerBackend",
    "SandboxBackend",
    "SandboxError",
    "SandboxManager",
    "SandboxSession",
    "SandboxSpec",
    "SandboxTimeout",
    "SandboxUnavailable",
    "cleanup_orphan_sandboxes",
    "list_sandbox_sessions",
]

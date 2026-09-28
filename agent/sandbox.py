"""Per-run Docker sandbox management.

The sandbox is intentionally isolated from the host workspace and Docker
daemon. Production deployments should point DOCKER_HOST at a remote daemon.
"""

from __future__ import annotations

import concurrent.futures
import os
import shutil
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Protocol

import agent.config as config
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


class SandboxError(RuntimeError):
    pass


class SandboxUnavailable(SandboxError):
    pass


class SandboxTimeout(SandboxError):
    pass


@dataclass(frozen=True)
class SandboxSpec:
    image: str
    user: str
    memory_limit: str
    nano_cpus: int
    pids_limit: int
    network_disabled: bool
    read_only_root: bool = True
    tmpfs_size: str = "64m"
    timeout_seconds: int = 120

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SandboxSession:
    id: str
    run_id: str
    container_id: str
    image: str
    workspace_host_path: str
    workspace_container_path: str
    created_at: float
    status: str = "running"
    owner_id: str = ""
    source: str = "chat"

    def to_dict(self) -> dict:
        return asdict(self)


class ContainerHandle(Protocol):
    id: str

    def exec(self, command: str, cwd: str, timeout_seconds: int) -> tuple[int, str]:
        ...

    def kill(self) -> None:
        ...

    def remove(self, force: bool = True) -> None:
        ...


class SandboxBackend(Protocol):
    def ping(self) -> bool:
        ...

    def create(
        self,
        *,
        name: str,
        spec: SandboxSpec,
        workspace_host_path: str,
        labels: dict,
    ) -> ContainerHandle:
        ...


class DockerContainerHandle:
    def __init__(self, container, user: str):
        self._container = container
        self._user = user
        self.id = str(getattr(container, "id", "") or "")

    def exec(
        self,
        command: str,
        cwd: str,
        timeout_seconds: int,
    ) -> tuple[int, str]:
        result = self._container.exec_run(
            ["sh", "-lc", command],
            workdir=cwd,
            user=self._user,
            demux=False,
        )
        exit_code = int(getattr(result, "exit_code", 1))
        output = getattr(result, "output", b"")
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        return exit_code, str(output or "").strip()

    def kill(self) -> None:
        self._container.kill()

    def remove(self, force: bool = True) -> None:
        self._container.remove(force=force)


class DockerBackend:
    """Docker SDK backend using DOCKER_HOST; no socket mount is requested."""

    def __init__(self):
        self._client = None

    def _get_client(self):
        if self._client is None:
            if (
                not os.environ.get("DOCKER_HOST")
                and not config.SANDBOX_ALLOW_LOCAL_DOCKER
            ):
                raise SandboxUnavailable(
                    "DOCKER_HOST is not configured; local Docker socket "
                    "access is disabled"
                )
            try:
                import docker
            except ImportError as exc:
                raise SandboxUnavailable(
                    "docker SDK is not installed"
                ) from exc
            self._client = docker.from_env()
        return self._client

    def ping(self) -> bool:
        try:
            return bool(self._get_client().ping())
        except Exception as exc:
            raise SandboxUnavailable(str(exc)) from exc

    def create(
        self,
        *,
        name: str,
        spec: SandboxSpec,
        workspace_host_path: str,
        labels: dict,
    ) -> ContainerHandle:
        try:
            container = self._get_client().containers.run(
                image=spec.image,
                command=["sh", "-lc", "while sleep 3600; do :; done"],
                name=name,
                detach=True,
                working_dir="/workspace",
                volumes={
                    workspace_host_path: {
                        "bind": "/workspace",
                        "mode": "rw",
                    },
                },
                user=spec.user,
                network_disabled=spec.network_disabled,
                mem_limit=spec.memory_limit,
                nano_cpus=spec.nano_cpus,
                pids_limit=spec.pids_limit,
                read_only=spec.read_only_root,
                tmpfs={
                    "/tmp": (
                        f"rw,noexec,nosuid,size={spec.tmpfs_size}"
                    ),
                },
                security_opt=["no-new-privileges:true"],
                cap_drop=["ALL"],
                init=True,
                labels=labels,
            )
        except SandboxUnavailable:
            raise
        except Exception as exc:
            raise SandboxUnavailable(str(exc)) from exc
        return DockerContainerHandle(container, spec.user)


class SandboxManager:
    """Create, execute, and clean one isolated workspace per Agent run."""

    def __init__(
        self,
        *,
        backend: SandboxBackend | None = None,
        base_dir: str | Path | None = None,
        enabled: bool | None = None,
    ):
        self.backend = backend or DockerBackend()
        self.base_dir = Path(base_dir or config.SANDBOX_DIR)
        self.enabled = (
            config.SANDBOX_ENABLED
            if enabled is None
            else enabled
        )
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
            raise SandboxTimeout(
                f"Sandbox command timed out after {timeout}s"
            ) from exc
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
                self._remove_workspace(
                    Path(session.workspace_host_path)
                )
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

    def _workspace_path(self, run_id: str) -> Path:
        safe_run = "".join(
            char if char.isalnum() or char in "-_" else "_"
            for char in str(run_id)
        )[:80]
        if not safe_run:
            safe_run = uuid.uuid4().hex
        base = self.base_dir.resolve()
        path = (base / safe_run).resolve()
        if not path.is_relative_to(base):
            raise SandboxError("Sandbox workspace escaped its base directory")
        return path

    def _prepare_workspace(
        self,
        workspace: Path,
        source_workspace: str | Path | None,
        *,
        reuse_existing: bool = False,
    ) -> None:
        workspace.parent.mkdir(parents=True, exist_ok=True)
        if workspace.exists() and reuse_existing:
            self._make_workspace_writable(workspace)
            return
        if workspace.exists():
            shutil.rmtree(workspace)
        if source_workspace is None:
            workspace.mkdir(parents=True, exist_ok=True)
        else:
            source = Path(source_workspace).resolve()
            if not source.exists() or not source.is_dir():
                raise SandboxError(
                    f"Sandbox source workspace does not exist: {source}"
                )
            ignore_patterns = shutil.ignore_patterns(
                ".git",
                ".env",
                ".audit",
                ".memory",
                ".sandboxes",
                ".tasks",
                ".transcripts",
                ".task_outputs",
                "node_modules",
                "tmp",
                "__pycache__",
                "*.pyc",
            )

            def ignore_symlinks(directory, names):
                ignored = set(ignore_patterns(directory, names))
                for name in names:
                    if (Path(directory) / name).is_symlink():
                        ignored.add(name)
                return ignored

            shutil.copytree(
                source,
                workspace,
                ignore=ignore_symlinks,
            )
        self._make_workspace_writable(workspace)

    def _make_workspace_writable(self, workspace: Path) -> None:
        if os.name == "nt":
            return
        try:
            os.chmod(workspace, 0o777)
            for root, dirs, files in os.walk(workspace):
                for name in dirs:
                    os.chmod(Path(root) / name, 0o777)
                for name in files:
                    os.chmod(Path(root) / name, 0o666)
        except OSError:
            pass

    def _remove_workspace(self, workspace: Path) -> None:
        base = self.base_dir.resolve()
        target = workspace.resolve()
        if not target.is_relative_to(base):
            raise SandboxError("Refusing to remove workspace outside sandbox base")
        if target.exists():
            shutil.rmtree(target)

    def _container_workdir(self, cwd: str | None) -> str:
        if not cwd or cwd in {".", "/"}:
            return "/workspace"
        path = PurePosixPath(cwd)
        if ".." in path.parts:
            raise SandboxError("Working directory escapes sandbox workspace")
        if path.is_absolute():
            if path == PurePosixPath("/workspace"):
                return "/workspace"
            if path.is_relative_to("/workspace"):
                return str(path)
            raise SandboxError(
                "Absolute working directory must be under /workspace"
            )
        return str(PurePosixPath("/workspace") / path)


__all__ = [
    "DockerBackend",
    "SandboxBackend",
    "SandboxError",
    "SandboxManager",
    "SandboxSession",
    "SandboxSpec",
    "SandboxTimeout",
    "SandboxUnavailable",
    "list_sandbox_sessions",
]

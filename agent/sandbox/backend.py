"""Docker and backend primitives for the Sandbox subsystem."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Protocol

import agent.platform.config as config


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

    def exec(self, command: str, cwd: str, timeout_seconds: int) -> tuple[int, str]: ...

    def kill(self) -> None: ...

    def remove(self, force: bool = True) -> None: ...


class SandboxBackend(Protocol):
    def ping(self) -> bool: ...

    def create(
        self,
        *,
        name: str,
        spec: SandboxSpec,
        workspace_host_path: str,
        labels: dict,
    ) -> ContainerHandle: ...


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
                raise SandboxUnavailable("docker SDK is not installed") from exc
            self._client = docker.from_env()
        return self._client

    def ping(self) -> bool:
        try:
            return bool(self._get_client().ping())
        except Exception as exc:
            raise SandboxUnavailable(str(exc)) from exc

    def remove_managed_containers(self) -> int:
        """Best-effort removal of containers left by a previous process."""
        client = self._get_client()
        containers = client.containers.list(
            all=True,
            filters={"label": "managed-by=ai-devops-agent"},
        )
        removed = 0
        for container in containers:
            try:
                container.remove(force=True)
                removed += 1
            except Exception:
                continue
        return removed

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
                    "/tmp": (f"rw,noexec,nosuid,size={spec.tmpfs_size}"),
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

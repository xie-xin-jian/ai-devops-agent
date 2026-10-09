"""Startup cleanup for orphaned Sandbox resources."""

from __future__ import annotations

import shutil
from pathlib import Path

import agent.platform.config as config
from agent.sandbox.backend import DockerBackend, SandboxBackend, SandboxError


def cleanup_orphan_sandboxes(
    *,
    backend: SandboxBackend | None = None,
    base_dir: str | Path | None = None,
) -> dict:
    """Remove containers and workspaces left after an unclean shutdown."""
    result = {
        "containers_removed": 0,
        "workspaces_removed": 0,
        "errors": [],
    }
    docker_backend = backend or DockerBackend()
    try:
        ping = getattr(docker_backend, "ping", None)
        if callable(ping) and ping():
            remove_managed = getattr(
                docker_backend,
                "remove_managed_containers",
                None,
            )
            if callable(remove_managed):
                result["containers_removed"] = int(remove_managed() or 0)
    except Exception as exc:
        result["errors"].append(f"docker cleanup failed: {exc}")

    target_base = Path(base_dir or config.SANDBOX_DIR).resolve()
    if not target_base.exists():
        return result
    for path in target_base.iterdir():
        if not path.is_dir():
            continue
        try:
            resolved = path.resolve()
            if not resolved.is_relative_to(target_base):
                raise SandboxError("Refusing to remove workspace outside sandbox base")
            shutil.rmtree(resolved)
            result["workspaces_removed"] += 1
        except Exception as exc:
            result["errors"].append(f"{path}: {exc}")
    return result

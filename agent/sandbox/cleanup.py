"""Startup cleanup for orphaned Sandbox workspaces."""

from __future__ import annotations

import shutil
from pathlib import Path

import agent.platform.config as config
from agent.sandbox.models import SandboxError


def cleanup_orphan_sandboxes(
    *,
    base_dir: str | Path | None = None,
) -> dict:
    """Remove workspaces left after an unclean shutdown."""
    result = {
        "workspaces_removed": 0,
        "errors": [],
    }
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

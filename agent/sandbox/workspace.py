"""Sandbox workspace validation and lifecycle helpers."""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path, PurePosixPath

from agent.sandbox.backend import SandboxError


class SandboxWorkspaceMixin:
    def _workspace_path(self, run_id: str) -> Path:
        safe_run = "".join(
            char if char.isalnum() or char in "-_" else "_" for char in str(run_id)
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
                raise SandboxError(f"Sandbox source workspace does not exist: {source}")
            ignore_patterns = shutil.ignore_patterns(
                ".git",
                ".env",
                ".audit",
                ".memory",
                ".sandboxes",
                ".sessions",
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
            raise SandboxError("Absolute working directory must be under /workspace")
        return str(PurePosixPath("/workspace") / path)

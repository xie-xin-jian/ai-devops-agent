"""Unified execution path for registered tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from agent.platform.config import WORKDIR
from agent.platform.identity import Principal, system_admin_principal
from agent.sandbox.manager import (
    SandboxManager,
    SandboxUnavailable,
)
from agent.tools.policy import ToolPolicyContext, evaluate_tool_policy
from agent.tools.registry import ToolRegistry
from agent.tools.shell import run_host_bash
from agent.targets.store import TargetStore
from agent.targets.tools import TARGET_TOOL_NAMES


SANDBOX_TOOL_NAMES = {
    "read_file",
    "write_file",
    "edit_file",
    "glob",
}


@dataclass(frozen=True)
class ToolExecutionResult:
    output: str
    sandbox_used: bool = False


class ToolExecutor:
    """Execute an allowed tool through one Sandbox/direct dispatch path."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        sandbox_manager: SandboxManager | None = None,
        sandbox_source: str = "",
        principal: Principal | None = None,
        tool_context: ToolPolicyContext | None = None,
        audit: Callable[..., None] | None = None,
        target_id: str = "",
    ):
        self.registry = registry
        self.sandbox_manager = sandbox_manager or SandboxManager()
        self.sandbox_source = sandbox_source
        self.principal = principal or system_admin_principal()
        self.tool_context = (
            tool_context
            or self.principal.to_tool_policy_context()
        )
        self.audit = audit
        self.target_id = str(target_id or "")

    def execute(
        self,
        tool_name: str,
        tool_input: dict,
        *,
        run_id: str,
        registry: ToolRegistry | None = None,
        source: str | None = None,
    ) -> ToolExecutionResult:
        active_registry = registry or self.registry
        if not isinstance(tool_input, dict):
            raise ValueError(f"Invalid input for tool '{tool_name}'")

        decision = evaluate_tool_policy(tool_name, self.tool_context)
        if not decision.allowed:
            raise PermissionError(decision.reason)

        spec = active_registry.get(tool_name)
        if spec is None:
            raise ValueError(f"No executor registered for tool '{tool_name}'")

        if (
            decision.policy.sandbox_required
            and tool_name in SANDBOX_TOOL_NAMES
        ):
            self._ensure_sandbox_workspace(run_id, source=source)
            output = self._run_sandboxed_tool(
                run_id,
                tool_name,
                tool_input,
            )
            return ToolExecutionResult(
                output=str(output),
                sandbox_used=True,
            )

        if tool_name == "bash":
            target_root = ""
            if self.target_id:
                target = TargetStore().get(self.target_id)
                if target is not None:
                    target_root = target.root
            output = run_host_bash(
                tool_input.get("command", ""),
                cwd=tool_input.get("cwd"),
                default_cwd=target_root or WORKDIR,
                timeout=decision.policy.timeout_seconds,
            )
            return ToolExecutionResult(output=output)

        try:
            if tool_name in TARGET_TOOL_NAMES:
                output = spec.handler(
                    target_id=self.target_id,
                    **tool_input,
                )
            else:
                output = spec.handler(**tool_input)
        except TypeError as exc:
            output = f"Error: {exc}"
        return ToolExecutionResult(output=str(output))

    def cleanup_sandbox(self, run_id: str) -> None:
        getter = getattr(self.sandbox_manager, "get", None)
        session = getter(run_id) if callable(getter) else None
        if callable(getter) and session is None:
            return
        try:
            self.sandbox_manager.cleanup(
                run_id,
                remove_workspace=True,
            )
        except TypeError:
            self.sandbox_manager.cleanup(run_id)
        if self.audit:
            self.audit(
                "sandbox.removed",
                "Sandbox workspace removed",
                result="success",
                severity="info",
                actor="agent",
                correlation_id=run_id,
                payload={
                    "sandbox_id": session.id,
                    "workspace_host_path": session.workspace_host_path,
                },
            )

    def _ensure_sandbox_workspace(
        self,
        run_id: str,
        *,
        source: str | None = None,
    ):
        getter = getattr(self.sandbox_manager, "get", None)
        session = getter(run_id) if callable(getter) else None
        if session is not None:
            return session
        if self.audit:
            self.audit(
                "sandbox.creating",
                "Creating sandbox workspace",
                result="success",
                severity="info",
                actor="agent",
                correlation_id=run_id,
                payload={"base_dir": str(self.sandbox_manager.base_dir)},
            )
        try:
            session = self.sandbox_manager.create(
                run_id,
                source_workspace=self.sandbox_source or None,
                owner_id=self.principal.id,
                source=source or "chat",
            )
        except SandboxUnavailable as exc:
            if self.audit:
                self.audit(
                    "sandbox.failed",
                    "Sandbox workspace unavailable",
                    summary=str(exc),
                    result="failed",
                    severity="high",
                    actor="agent",
                    correlation_id=run_id,
                )
            raise
        if self.audit:
            self.audit(
                "sandbox.created",
                "Sandbox workspace created",
                result="success",
                severity="info",
                actor="agent",
                correlation_id=run_id,
                payload=session.to_dict(),
            )
        return session

    def _run_sandboxed_tool(
        self,
        run_id: str,
        tool_name: str,
        tool_input: dict,
    ) -> str:
        try:
            if tool_name == "read_file":
                return self.sandbox_manager.read_file(
                    run_id,
                    tool_input.get("path", ""),
                    limit=tool_input.get("limit"),
                    offset=tool_input.get("offset", 0),
                )
            if tool_name == "write_file":
                return self.sandbox_manager.write_file(
                    run_id,
                    tool_input.get("path", ""),
                    tool_input.get("content", ""),
                )
            if tool_name == "edit_file":
                return self.sandbox_manager.edit_file(
                    run_id,
                    tool_input.get("path", ""),
                    tool_input.get("old_text", ""),
                    tool_input.get("new_text", ""),
                )
            if tool_name == "glob":
                return self.sandbox_manager.glob(
                    run_id,
                    tool_input.get("pattern", ""),
                )
        except SandboxUnavailable as exc:
            return f"Error: Sandbox workspace unavailable: {exc}"
        except Exception as exc:
            return f"Error: sandbox tool failed: {exc}"
        raise ValueError(f"Tool '{tool_name}' is not supported in Sandbox")


__all__ = [
    "SANDBOX_TOOL_NAMES",
    "ToolExecutionResult",
    "ToolExecutor",
]

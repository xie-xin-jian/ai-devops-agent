"""Unified execution path for registered tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from agent.platform.identity import Principal, system_admin_principal
from agent.sandbox.manager import (
    SandboxManager,
    SandboxTimeout,
    SandboxUnavailable,
)
from agent.tools.policy import ToolPolicyContext, evaluate_tool_policy
from agent.tools.registry import ToolRegistry


SANDBOX_TOOL_NAMES = {
    "bash",
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
        spec = active_registry.get(tool_name)
        if spec is None:
            raise ValueError(f"No executor registered for tool '{tool_name}'")
        if not isinstance(tool_input, dict):
            raise ValueError(f"Invalid input for tool '{tool_name}'")

        decision = evaluate_tool_policy(tool_name, self.tool_context)
        if not decision.allowed:
            raise PermissionError(decision.reason)

        if (
            decision.policy.sandbox_required
            and tool_name in SANDBOX_TOOL_NAMES
        ):
            self._ensure_sandbox(run_id, source=source)
            output = self._run_sandboxed_tool(
                run_id,
                tool_name,
                tool_input,
                decision.policy.timeout_seconds,
            )
            return ToolExecutionResult(
                output=str(output),
                sandbox_used=True,
            )

        try:
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
                "Docker sandbox removed",
                result="success",
                severity="info",
                actor="agent",
                correlation_id=run_id,
                payload={
                    "sandbox_id": session.id,
                    "container_id": session.container_id,
                },
            )

    def _ensure_sandbox(
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
                "Creating Docker sandbox",
                result="success",
                severity="info",
                actor="agent",
                correlation_id=run_id,
                payload={"image": self.sandbox_manager.spec.image},
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
                    "Docker sandbox unavailable",
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
                "Docker sandbox created",
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
        timeout_seconds: int,
    ) -> str:
        try:
            if tool_name == "bash":
                if tool_input.get("run_in_background"):
                    return (
                        "Error: background sandbox execution is not "
                        "enabled here"
                    )
                return self.sandbox_manager.run(
                    run_id,
                    tool_input.get("command", ""),
                    cwd=tool_input.get("cwd"),
                    timeout_seconds=timeout_seconds,
                )
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
        except SandboxTimeout as exc:
            if self.audit:
                self.audit(
                    "sandbox.timeout",
                    f"Sandbox tool timed out: {tool_name}",
                    summary=str(exc),
                    result="failed",
                    severity="high",
                    actor="agent",
                    tool_name=tool_name,
                    correlation_id=run_id,
                    payload={"input": tool_input},
                )
            return f"Error: {exc}"
        except SandboxUnavailable as exc:
            return f"Error: Docker sandbox unavailable: {exc}"
        except Exception as exc:
            return f"Error: sandbox tool failed: {exc}"
        raise ValueError(f"Tool '{tool_name}' is not supported in Sandbox")


__all__ = [
    "SANDBOX_TOOL_NAMES",
    "ToolExecutionResult",
    "ToolExecutor",
]

"""Execute approved tool calls through the shared ToolExecutor."""

from __future__ import annotations

from types import SimpleNamespace

from agent.orchestration.background import should_run_background, start_background_task
from agent.mcp.client import assemble_tool_pool
from agent.platform.identity import Principal
from agent.sandbox.manager import SandboxManager
from agent.tools.executor import ToolExecutor
from agent.tools.registry import ToolRegistry


def execute_pending_action(action, principal: Principal) -> dict:
    run_id = f"approved_{action.id}"
    base_registry = ToolRegistry.builtin()
    tools, handlers = assemble_tool_pool(
        base_registry.schemas(),
        base_registry.handlers(),
        {
            "owner_id": getattr(action, "owner_id", ""),
            "session_id": getattr(action, "session_id", ""),
            "run_id": run_id,
        },
    )
    registry = base_registry.with_dynamic_tools(tools, handlers)
    sandbox = SandboxManager()
    executor = ToolExecutor(
        registry,
        sandbox_manager=sandbox,
        sandbox_source="",
        principal=principal,
    )
    outputs = []

    try:
        for step in action.steps:
            tool_name = str(step.get("tool") or "").strip()
            tool_input = step.get("input") or {}
            if not isinstance(tool_input, dict):
                raise ValueError(f"Invalid input for tool '{tool_name}'")

            if (
                tool_name == "bash"
                and should_run_background(tool_name, tool_input)
            ):
                background_id = start_background_task(
                    SimpleNamespace(
                        id=action.id,
                        name=tool_name,
                        input=tool_input,
                    ),
                    registry.handlers(),
                    lambda *args: None,
                    principal=principal,
                    session_id=getattr(action, "session_id", ""),
                    parent_run_id=run_id,
                )
                result = (
                    f"Background task started: {background_id}\n"
                    "Check results with list_background_tasks."
                )
            else:
                result = executor.execute(
                    tool_name,
                    tool_input,
                    run_id=run_id,
                    registry=registry,
                    source="approved_action",
                ).output

            outputs.append({
                "tool": tool_name,
                "input": tool_input,
                "output": str(result)[:50000],
            })
    finally:
        executor.cleanup_sandbox(run_id)

    success = all(
        not item["output"].startswith("Error:")
        for item in outputs
    )
    return {
        "execution_enabled": True,
        "success": success,
        "summary": "\n\n".join(
            f"{item['tool']}:\n{item['output']}"
            for item in outputs
        )[:50000],
        "outputs": outputs,
    }


__all__ = ["execute_pending_action"]

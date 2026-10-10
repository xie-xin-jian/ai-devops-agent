"""Agent background-task integration tests."""

from types import SimpleNamespace

from agent.core import comprehensive
from agent.orchestration.pending_actions import PendingActionStore
from agent.platform.identity import system_admin_principal
from agent.tools.executor import ToolExecutor
from agent.tools.policy import ToolPolicyContext
from agent.tools.registry import ToolRegistry


def test_bash_waits_for_approval_before_background_start(
    tmp_path,
    monkeypatch,
):
    agent = object.__new__(comprehensive.ComprehensiveAgent)
    agent.session_id = "session-bg"
    agent.principal = system_admin_principal()
    agent.tool_context = ToolPolicyContext()
    agent.pending_action_store = PendingActionStore(
        tmp_path / "actions.json"
    )
    agent._pending_action_notifications = []
    agent._last_user_query = "npm install"
    agent.audit_enabled = False
    agent.current_run_id = "run-bg"
    agent.tool_registry = ToolRegistry.builtin()
    agent.sandbox_manager = object()
    agent.tool_executor = ToolExecutor(
        agent.tool_registry,
        sandbox_manager=agent.sandbox_manager,
        principal=agent.principal,
        tool_context=agent.tool_context,
    )


    output = agent._handle_tool_call(
        SimpleNamespace(name="bash", input={"command": "npm install"})
    )

    assert output.startswith("Approval required")


def test_approved_background_bash_starts_background(monkeypatch):
    from agent.orchestration import pending_executor as pending_action_executor

    calls = []
    action = SimpleNamespace(
        id="act_bg",
        session_id="session-bg",
        steps=[{
            "tool": "bash",
            "input": {
                "command": "npm install",
                "run_in_background": True,
            },
        }],
    )
    monkeypatch.setattr(
        pending_action_executor,
        "start_background_task",
        lambda *args, **kwargs: calls.append((args, kwargs)) or "bg_0001",
    )

    result = pending_action_executor.execute_pending_action(
        action,
        system_admin_principal(),
    )

    assert result["success"] is True
    assert "bg_0001" in result["summary"]
    assert calls[0][1]["parent_run_id"].startswith("approved_")

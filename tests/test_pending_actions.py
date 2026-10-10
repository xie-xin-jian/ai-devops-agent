"""Tool policy and pending-action execution tests."""

from types import SimpleNamespace

import pytest

from agent.core import comprehensive
from agent.core import pipeline
from agent.orchestration.pending_actions import (
    STATUS_CANCELED,
    STATUS_CONFIRMED,
    STATUS_EXECUTED,
    PendingActionStore,
)
from agent.platform.identity import system_admin_principal
from agent.sandbox.manager import SandboxManager
from agent.tools.executor import ToolExecutor
from agent.tools.policy import ToolPolicyContext
from agent.tools.registry import ToolRegistry


def _make_agent(tmp_path, monkeypatch):
    agent = object.__new__(comprehensive.ComprehensiveAgent)
    agent.session_id = "session-1"
    agent.principal = system_admin_principal()
    agent.tool_context = ToolPolicyContext()
    agent.pending_action_store = PendingActionStore(
        tmp_path / "actions.json"
    )
    agent._pending_action_notifications = []
    agent._last_user_query = "test request"
    agent.audit_enabled = False
    agent.current_run_id = "run-test"
    agent.sandbox_manager = SandboxManager()
    agent.tool_registry = ToolRegistry.builtin()
    agent.tool_executor = ToolExecutor(
        agent.tool_registry,
        sandbox_manager=agent.sandbox_manager,
        principal=agent.principal,
        tool_context=agent.tool_context,
    )
    return agent


def test_pending_action_store_lifecycle(tmp_path):
    store = PendingActionStore(tmp_path / "actions.json")
    record = store.create_tool_call(
        "bash",
        {"command": "echo hello"},
        session_id="session-1",
        run_id="run-1",
        tool_use_id="call-1",
        owner_id="system",
        summary="执行命令: echo hello",
    )

    assert store.get(record.id).status == "pending"
    assert store.get(record.id).run_id == "run-1"
    assert store.get(record.id).tool_use_id == "call-1"
    assert store.list(session_id="session-1")[0].id == record.id

    confirmed = store.confirm(record.id, actor="tester")
    assert confirmed.status == STATUS_CONFIRMED
    assert confirmed.confirmed_by == "tester"
    assert confirmed.result_payload["execution_enabled"] is False

    canceled = store.cancel(
        record.id,
        actor="tester",
        reason="not needed",
    )
    assert canceled.status == STATUS_CANCELED
    assert canceled.cancel_reason == "not needed"


def test_pending_action_store_rejects_invalid_transition(tmp_path):
    store = PendingActionStore(tmp_path / "actions.json")
    record = store.create_tool_call(
        "bash",
        {"command": "echo hello"},
        session_id="session-1",
    )
    store.cancel(record.id)

    with pytest.raises(ValueError, match="canceled"):
        store.confirm(record.id)


def test_pending_action_recovery_fails_confirmed_action(tmp_path):
    store = PendingActionStore(tmp_path / "actions.json")
    record = store.create_tool_call(
        "bash",
        {"command": "echo hello"},
        session_id="session-1",
    )
    store.confirm(record.id)

    recovered = store.recover_interrupted(
        "process restarted during execution"
    )

    assert len(recovered) == 1
    loaded = store.get(record.id)
    assert loaded.status == "failed"
    assert loaded.result_payload["interrupted"] is True


def test_read_only_host_inspection_executes_without_approval(
    tmp_path,
    monkeypatch,
):
    agent = _make_agent(tmp_path, monkeypatch)
    agent.tool_registry.replace_handler(
        "cpu_usage",
        lambda: "CPU 7%",
    )

    output = agent._handle_tool_call(
        SimpleNamespace(name="cpu_usage", input={})
    )

    assert output == "CPU 7%"
    assert agent.pending_action_store.list() == []


def test_bash_creates_pending_action_without_executing(
    tmp_path,
    monkeypatch,
):
    agent = _make_agent(tmp_path, monkeypatch)
    agent.target_id = "tgt-test"

    output = agent._handle_tool_call(
        SimpleNamespace(name="bash", input={"command": "echo hello"})
    )

    assert output.startswith("Approval required: pending action act_")
    actions = agent.pending_action_store.list()
    assert len(actions) == 1
    assert actions[0].payload == {
        "tool": "bash",
        "input": {"command": "echo hello"},
    }
    assert actions[0].run_id == "run-test"
    assert actions[0].target_id == "tgt-test"
    assert agent._pending_action_notifications[0]["id"] == actions[0].id


def test_agent_stream_emits_pending_action_event(tmp_path, monkeypatch):
    agent = _make_agent(tmp_path, monkeypatch)
    agent.client = object()
    agent.model = "test-model"
    agent.recovery = SimpleNamespace(current_model="test-model")
    agent.messages = []
    agent._pending_compaction = False

    tool_use = SimpleNamespace(
        type="tool_use",
        name="bash",
        id="call_bash",
        input={"command": "echo hello"},
    )
    final = SimpleNamespace(type="text", text="已生成待审批命令")
    responses = iter([
        SimpleNamespace(content=[tool_use]),
        SimpleNamespace(content=[final]),
    ])

    monkeypatch.setattr(pipeline, "collect_background_results", lambda: [])
    monkeypatch.setattr(agent, "_compact_if_needed", lambda messages: messages)
    monkeypatch.setattr(agent, "_call_api", lambda messages: next(responses))

    events = list(agent.run_stream("echo hello"))
    pending_events = [
        event for event in events
        if event["type"] == "pending_action"
    ]

    assert len(pending_events) == 1
    assert pending_events[0]["pending_action"]["payload"]["tool"] == "bash"
    assert agent.pending_action_store.list()[0].status == "pending"


def test_execute_pending_action_runs_bash_on_host(monkeypatch):
    from agent.tools import executor as executor_module
    from agent.orchestration import pending_executor as pending_action_executor

    class FakeSandboxManager:
        calls = []

        def create(self, run_id, **kwargs):
            self.calls.append(("create", run_id))

        def run(self, run_id, command, cwd=None, timeout_seconds=None):
            self.calls.append(("run", run_id, command, cwd))
            return "exit_code=0\nhello"

        def cleanup(self, run_id):
            self.calls.append(("cleanup", run_id))

    monkeypatch.setattr(
        pending_action_executor,
        "SandboxManager",
        FakeSandboxManager,
    )
    monkeypatch.setattr(
        executor_module,
        "run_host_bash",
        lambda *args, **kwargs: "exit_code=0\nhello",
    )

    action = SimpleNamespace(
        id="act_test",
        steps=[{
            "tool": "bash",
            "input": {"command": "echo hello"},
        }],
    )
    result = pending_action_executor.execute_pending_action(
        action,
        system_admin_principal(),
    )

    assert result["success"] is True
    assert "hello" in result["summary"]
    assert not any(
        call[0] in {"create", "run"}
        for call in FakeSandboxManager.calls
    )


def test_build_approval_continuation_message_contains_result():
    from agent.orchestration.pending_executor import (
        build_approval_continuation_message,
    )

    action = SimpleNamespace(
        id="act_test",
        payload={
            "tool": "bash",
            "input": {"command": "echo hello"},
        },
    )
    message = build_approval_continuation_message(
        action,
        {
            "success": True,
            "summary": "exit_code=0\nhello",
        },
    )

    assert "act_test" in message
    assert "echo hello" in message
    assert "hello" in message
    assert "不要重复申请或执行同一个命令" in message


def test_pending_action_api_executes_and_cancels(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from api.routes import action_route

    store_path = tmp_path / "api-actions.json"
    monkeypatch.setattr(
        "agent.orchestration.pending_actions.PENDING_ACTIONS_PATH",
        store_path,
    )
    store = PendingActionStore(store_path)
    executable = store.create_tool_call(
        "bash",
        {"command": "echo hello"},
        session_id="api-session",
        owner_id="system",
    )
    canceled = store.create_tool_call(
        "bash",
        {"command": "echo canceled"},
        session_id="api-session",
        owner_id="system",
    )

    monkeypatch.setattr(
        action_route,
        "execute_pending_action",
        lambda action, principal: {
            "execution_enabled": True,
            "success": True,
            "summary": "exit_code=0\nhello",
            "outputs": [],
        },
    )
    async def fake_continue(action, result, principal):
        return "Agent continued with the approved result."

    monkeypatch.setattr(
        action_route,
        "_continue_session_after_approval",
        fake_continue,
    )

    from api.main import app
    client = TestClient(app)
    confirmed = client.post(
        f"/api/actions/pending/{executable.id}/confirm",
        json={},
    )
    rejected = client.post(
        f"/api/actions/pending/{canceled.id}/cancel",
        json={"reason": "test complete"},
    )

    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == STATUS_EXECUTED
    assert "hello" in confirmed.json()["result_payload"]["summary"]
    assert (
        confirmed.json()["result_payload"]["assistant_response"]
        == "Agent continued with the approved result."
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == STATUS_CANCELED

"""Preflight and pending-action persistence tests."""

from types import SimpleNamespace

import pytest

from agent import comprehensive
from agent.action_router import get_action
from agent.pending_actions import (
    STATUS_CANCELED,
    STATUS_CONFIRMED,
    PendingActionStore,
    build_preflight,
)
from agent.tool_policy import ToolPolicyContext


def test_preflight_reports_missing_required_fields():
    action = get_action("command.execute")

    result = build_preflight(action, {"target": "test-host"})

    assert result.ready is False
    assert "command" in result.missing_fields
    assert "rollback_plan" in result.missing_fields


def test_pending_action_store_lifecycle(tmp_path):
    action = get_action("file.change")
    store = PendingActionStore(tmp_path / "actions.json")

    record = store.create(
        action,
        session_id="session-1",
        source_message="修改配置",
        summary="修改配置文件",
        payload={
            "target_path": "config.yaml",
            "change_summary": "更新端口",
        },
        steps=[
            {"tool": "edit_file", "description": "更新配置"},
        ],
    )

    assert store.get(record.id).status == "pending"
    assert store.list(session_id="session-1")[0].id == record.id

    confirmed = store.confirm(record.id, actor="tester")
    assert confirmed.status == STATUS_CONFIRMED
    assert confirmed.confirmed_by == "tester"
    assert confirmed.result_payload["execution_enabled"] is False

    canceled = store.cancel(record.id, actor="tester", reason="not needed")
    assert canceled.status == STATUS_CANCELED
    assert canceled.cancel_reason == "not needed"


def test_pending_action_store_rejects_invalid_transition(tmp_path):
    action = get_action("memory.manage")
    store = PendingActionStore(tmp_path / "actions.json")
    record = store.create(
        action,
        session_id="session-1",
        source_message="记住端口",
        summary="保存记忆",
        payload={
            "scope": "global",
            "content": "端口 8080",
        },
        steps=[
            {"tool": "add_memory", "description": "保存长期记忆"},
        ],
    )
    store.cancel(record.id)

    with pytest.raises(ValueError, match="canceled"):
        store.confirm(record.id)


def test_propose_action_creates_pending_record_and_notification(
    tmp_path,
    monkeypatch,
):
    agent = object.__new__(comprehensive.ComprehensiveAgent)
    agent.current_action = get_action("file.change")
    agent.session_id = "session-1"
    agent._last_user_query = "修改 config.yaml"
    agent.tool_context = ToolPolicyContext()
    agent.pending_action_store = PendingActionStore(tmp_path / "actions.json")
    agent._pending_action_notifications = []
    agent.tools = []
    agent.handlers = {}
    agent._register_default_tools = lambda: None
    agent._add_governance_tools()

    monkeypatch.setattr(comprehensive, "trigger_hooks", lambda *args: None)

    output = agent._handle_tool_call(
        SimpleNamespace(
            name="propose_action",
            input={
                "summary": "更新 config.yaml",
                "payload": {
                    "target_path": "config.yaml",
                    "change_summary": "更新端口",
                },
                "steps": [
                    {
                        "tool": "edit_file",
                        "description": "更新端口配置",
                    },
                ],
            },
        )
    )

    assert "Pending action created" in output
    assert len(agent._pending_action_notifications) == 1
    pending = agent._pending_action_notifications[0]
    assert pending["action_code"] == "file.change"
    assert pending["status"] == "pending"


def test_preflight_action_blocks_direct_approval_tool(
    tmp_path,
    monkeypatch,
):
    agent = object.__new__(comprehensive.ComprehensiveAgent)
    agent.current_action = get_action("file.change")
    agent.tool_context = ToolPolicyContext()
    agent.pending_action_store = PendingActionStore(tmp_path / "actions.json")
    agent._pending_action_notifications = []
    agent.tools = []
    agent.handlers = {}
    agent._register_default_tools = lambda: None
    agent._add_governance_tools()

    monkeypatch.setattr(comprehensive, "trigger_hooks", lambda *args: None)

    output = agent._handle_tool_call(
        SimpleNamespace(
            name="write_file",
            input={"path": "config.yaml", "content": "x"},
        )
    )

    assert output.startswith("Preflight required")


def test_agent_stream_emits_pending_action_event(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "agent.audit.AUDIT_EVENTS_PATH",
        tmp_path / "audit.jsonl",
    )
    agent = object.__new__(comprehensive.ComprehensiveAgent)
    agent.client = object()
    agent.model = "test-model"
    agent.recovery = SimpleNamespace(current_model="test-model")
    agent.messages = []
    agent.session_id = "stream-session"
    agent.audit_enabled = True
    agent.current_run_id = ""
    agent._last_user_query = ""
    agent._pending_compaction = False
    agent._pending_action_notifications = []
    agent.pending_action_store = PendingActionStore(tmp_path / "actions.json")
    agent.tools = []
    agent.handlers = {}
    agent._add_governance_tools()

    proposal = SimpleNamespace(
        type="tool_use",
        name="propose_action",
        id="call_propose",
        input={
            "summary": "更新 config.yaml",
            "payload": {
                "target_path": "config.yaml",
                "change_summary": "更新端口",
            },
            "steps": [
                {
                    "tool": "edit_file",
                    "description": "更新端口配置",
                },
            ],
        },
    )
    final = SimpleNamespace(type="text", text="已生成待审批动作")
    responses = iter([
        SimpleNamespace(content=[proposal]),
        SimpleNamespace(content=[final]),
    ])

    monkeypatch.setattr(comprehensive, "trigger_hooks", lambda *args: None)
    monkeypatch.setattr(comprehensive, "collect_background_results", lambda: [])
    monkeypatch.setattr(agent, "_compact_if_needed", lambda messages: messages)
    monkeypatch.setattr(agent, "_call_api", lambda messages: next(responses))

    events = list(agent.run_stream("修改 config.yaml"))
    pending_events = [
        event for event in events
        if event["type"] == "pending_action"
    ]

    assert len(pending_events) == 1
    assert pending_events[0]["pending_action"]["action_code"] == "file.change"
    assert agent.pending_action_store.list()[0].status == "pending"
    from agent.audit import AuditStore
    event_types = {
        event.event_type
        for event in AuditStore(tmp_path / "audit.jsonl").list_events(
            session_id="stream-session"
        )
    }
    assert {
        "run.started",
        "action.selected",
        "tool.started",
        "tool.completed",
        "preflight.completed",
        "pending_action.created",
        "run.completed",
    }.issubset(event_types)


def test_pending_action_api_lifecycle(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from api.main import app

    store_path = tmp_path / "api-actions.json"
    audit_path = tmp_path / "api-audit.jsonl"
    monkeypatch.setattr(
        "agent.pending_actions.PENDING_ACTIONS_PATH",
        store_path,
    )
    monkeypatch.setattr(
        "agent.audit.AUDIT_EVENTS_PATH",
        audit_path,
    )
    action = get_action("memory.manage")
    record = PendingActionStore(store_path).create(
        action,
        session_id="api-session",
        source_message="记住端口",
        summary="保存端口记忆",
        payload={
            "scope": "global",
            "content": "端口 8080",
        },
        steps=[
            {"tool": "add_memory", "description": "保存记忆"},
        ],
    )

    client = TestClient(app)
    listed = client.get("/api/actions/pending?session_id=api-session")
    assert listed.status_code == 200
    assert listed.json()["actions"][0]["id"] == record.id

    confirmed = client.post(
        f"/api/actions/pending/{record.id}/confirm",
        json={"actor": "api-test"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == STATUS_CONFIRMED

    canceled = client.post(
        f"/api/actions/pending/{record.id}/cancel",
        json={"actor": "api-test", "reason": "test complete"},
    )
    assert canceled.status_code == 200
    assert canceled.json()["status"] == STATUS_CANCELED

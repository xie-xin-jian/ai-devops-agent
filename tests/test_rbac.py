"""RBAC role resolution and API capability-filtering tests."""

from fastapi.testclient import TestClient

from agent import config
from agent.action_router import get_action
from agent.rbac import (
    ACTION_APPROVE,
    AGENT_CHAT,
    AUDIT_VIEW,
    FILESYSTEM_WRITE,
    SHELL_EXECUTE,
    principal_from_roles,
)
from agent.tool_policy import evaluate_tool_policy


def test_viewer_is_read_only():
    viewer = principal_from_roles("viewer-1", {"viewer"})
    context = viewer.to_tool_policy_context()

    assert viewer.has(AGENT_CHAT) is True
    assert viewer.has(AUDIT_VIEW) is False
    assert viewer.has(FILESYSTEM_WRITE) is False
    assert evaluate_tool_policy("read_file", context).allowed is True
    assert evaluate_tool_policy("write_file", context).allowed is False
    assert evaluate_tool_policy("bash", context).allowed is False


def test_developer_can_write_files_but_not_shell():
    developer = principal_from_roles("developer-1", {"developer"})
    context = developer.to_tool_policy_context()

    assert developer.has(FILESYSTEM_WRITE) is True
    assert developer.has(SHELL_EXECUTE) is False
    assert evaluate_tool_policy("write_file", context).allowed is True
    assert evaluate_tool_policy("bash", context).allowed is False


def test_operator_receives_governed_shell_capability():
    operator = principal_from_roles("operator-1", {"ops-operator"})
    context = operator.to_tool_policy_context()

    decision = evaluate_tool_policy("bash", context)

    assert decision.allowed is True
    assert decision.requires_approval is True


def test_viewer_missing_action_permission_is_reported():
    viewer = principal_from_roles("viewer-1", {"viewer"})
    command_action = get_action("command.execute")

    missing = viewer.missing(command_action.rbac_permissions)

    assert missing == [SHELL_EXECUTE]


def test_rbac_api_filters_viewer_capabilities(monkeypatch):
    monkeypatch.setattr(config, "API_AUTH_TOKEN", "viewer-token")
    monkeypatch.setattr(config, "API_AUTH_USER", "viewer-1")
    monkeypatch.setattr(config, "API_AUTH_ROLES", ["viewer"])

    from api.main import app
    client = TestClient(app)
    headers = {"Authorization": "Bearer viewer-token"}

    me = client.get("/api/rbac/me", headers=headers)
    tasks = client.get("/api/tasks/", headers=headers)
    create_task = client.post(
        "/api/tasks/",
        headers=headers,
        json={"subject": "denied"},
    )
    audit = client.get("/api/audit/events", headers=headers)

    assert me.status_code == 200
    assert me.json()["roles"] == ["viewer"]
    assert tasks.status_code == 200
    assert create_task.status_code == 403
    assert AUDIT_VIEW in audit.json()["detail"]["missing_permissions"]


def test_viewer_cannot_confirm_pending_action(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "API_AUTH_TOKEN", "viewer-token")
    monkeypatch.setattr(config, "API_AUTH_USER", "viewer-1")
    monkeypatch.setattr(config, "API_AUTH_ROLES", ["viewer"])
    monkeypatch.setattr(
        "agent.pending_actions.PENDING_ACTIONS_PATH",
        tmp_path / "actions.json",
    )

    from agent.pending_actions import PendingActionStore
    store = PendingActionStore(tmp_path / "actions.json")
    action = get_action("file.change")
    record = store.create(
        action,
        session_id="viewer-session",
        owner_id="viewer-1",
        source_message="修改文件",
        summary="修改文件",
        payload={
            "target_path": "config.yaml",
            "change_summary": "更新配置",
        },
        steps=[
            {"tool": "edit_file", "description": "更新配置"},
        ],
    )

    from api.main import app
    client = TestClient(app)
    response = client.post(
        f"/api/actions/pending/{record.id}/confirm",
        headers={"Authorization": "Bearer viewer-token"},
    )

    assert response.status_code == 403
    assert ACTION_APPROVE in response.json()["detail"]["missing_permissions"]

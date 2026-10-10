"""Isolated Sandbox workspace lifecycle and Bash boundary tests."""

from types import SimpleNamespace

import pytest

from agent.core import comprehensive
from agent.orchestration.pending_actions import PendingActionStore
from agent.orchestration.approval_coordinator import ToolApprovalRequired
from agent.platform.identity import system_admin_principal
from agent.sandbox.manager import (
    SandboxManager,
    SandboxUnavailable,
    cleanup_orphan_sandboxes,
    list_sandbox_sessions,
)
from agent.tools.executor import ToolExecutor
from agent.tools.registry import ToolRegistry


def test_sandbox_creates_isolated_workspace_copy(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.txt").write_text("copy me", encoding="utf-8")
    manager = SandboxManager(
        base_dir=tmp_path / "sandboxes",
        enabled=True,
    )

    session = manager.create("run-copy", source_workspace=source)

    workspace = tmp_path / "sandboxes" / "run-copy"
    assert session.workspace_host_path == str(workspace)
    assert (workspace / "app.txt").read_text(encoding="utf-8") == "copy me"
    assert session.status == "ready"


def test_sandbox_file_tools_modify_only_workspace(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.txt").write_text("original", encoding="utf-8")
    manager = SandboxManager(
        base_dir=tmp_path / "sandboxes",
        enabled=True,
    )
    manager.create("run-files", source_workspace=source)

    manager.write_file("run-files", "app.txt", "changed")
    assert manager.read_file("run-files", "app.txt") == "changed"
    assert (source / "app.txt").read_text(encoding="utf-8") == "original"

    manager.cleanup("run-files")
    assert not (tmp_path / "sandboxes" / "run-files").exists()


def test_sandbox_disabled_rejects_workspace_creation(tmp_path):
    manager = SandboxManager(
        base_dir=tmp_path,
        enabled=False,
    )

    with pytest.raises(SandboxUnavailable, match="disabled"):
        manager.create("run-disabled")


def test_sandbox_file_path_cannot_escape_workspace(tmp_path):
    manager = SandboxManager(
        base_dir=tmp_path / "sandboxes",
        enabled=True,
    )
    manager.create("run-path")

    output = manager.read_file("run-path", "../outside.txt")

    assert output.startswith("Error:")
    assert "escapes workspace" in output


def _make_agent(tmp_path, manager):
    agent = object.__new__(comprehensive.ComprehensiveAgent)
    agent.current_run_id = "run-agent"
    agent.session_id = "session-agent"
    agent.target_id = ""
    agent.principal = system_admin_principal()
    agent.pending_action_store = PendingActionStore(
        tmp_path / "agent-actions.json"
    )
    agent._last_user_query = "echo approved"
    agent.tool_context = None
    agent.audit_enabled = False
    agent.sandbox_manager = manager
    agent.tool_registry = ToolRegistry.builtin()
    agent.tool_executor = ToolExecutor(
        agent.tool_registry,
        sandbox_manager=manager,
        principal=agent.principal,
    )
    return agent


def test_agent_requires_approval_before_host_bash(tmp_path, monkeypatch):
    manager = SandboxManager(
        base_dir=tmp_path / "sandboxes",
        enabled=True,
    )
    agent = _make_agent(tmp_path, manager)
    monkeypatch.setattr(
        "agent.tools.executor.run_host_bash",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("host bash must not run before approval")
        ),
    )

    with pytest.raises(ToolApprovalRequired) as exc:
        agent._handle_tool_call(
            SimpleNamespace(
                name="bash",
                input={"command": "echo approved"},
            )
        )

    assert exc.value.record.payload["tool"] == "bash"
    assert agent.pending_action_store.list()[0].payload["tool"] == "bash"


def test_approved_bash_runs_on_host(tmp_path, monkeypatch):
    from agent.orchestration import pending_executor as pending_action_executor
    from agent.tools import executor as executor_module

    monkeypatch.setattr(
        executor_module,
        "run_host_bash",
        lambda *args, **kwargs: "exit_code=0\nhost ok",
    )
    action = SimpleNamespace(
        id="act_approved",
        session_id="session-agent",
        target_id="",
        steps=[{
            "tool": "bash",
            "input": {"command": "echo host-ok"},
        }],
    )

    result = pending_action_executor.execute_pending_action(
        action,
        system_admin_principal(),
    )

    assert result["success"] is True
    assert "host ok" in result["summary"]


def test_sandbox_status_api_lists_active_workspaces(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from api.routes import sandbox_route

    monkeypatch.setattr(
        sandbox_route,
        "list_sandbox_sessions",
        lambda: [{
            "id": "sbox-1",
            "run_id": "run-api",
            "source": "chat",
            "owner_id": "system",
            "status": "ready",
            "workspace_host_path": "/tmp/sandbox",
            "created_at": 1.0,
        }],
    )
    from api.main import app

    response = TestClient(app).get("/api/sandboxes/")

    assert response.status_code == 200
    assert response.json()["active"][0]["run_id"] == "run-api"


def test_list_sandbox_sessions_uses_registry(tmp_path):
    manager = SandboxManager(
        base_dir=tmp_path,
        enabled=True,
    )
    manager.create(
        "run-registry",
        owner_id="alice",
        source="background",
    )

    sessions = list_sandbox_sessions()

    assert any(
        item["run_id"] == "run-registry"
        and item["owner_id"] == "alice"
        and item["source"] == "background"
        for item in sessions
    )
    manager.cleanup("run-registry")


def test_cleanup_orphan_sandboxes_removes_workspaces(tmp_path):
    base_dir = tmp_path / ".sandboxes"
    (base_dir / "run-1").mkdir(parents=True)
    (base_dir / "run-1" / "file.txt").write_text("orphan", encoding="utf-8")

    result = cleanup_orphan_sandboxes(base_dir=base_dir)

    assert result["workspaces_removed"] == 1
    assert result["errors"] == []
    assert list(base_dir.iterdir()) == []

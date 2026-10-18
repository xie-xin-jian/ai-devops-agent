"""Memory scope, ownership, approval, and audit tests."""

from agent.core import comprehensive
from agent.memory import service as memory
from agent.platform import config
from agent.observability.audit import AuditStore
from agent.memory.policy import (
    can_read_scope,
    can_write_scope,
)
from agent.platform.identity import principal_from_roles
from agent.tools.registry import ToolRegistry


def _memory_agent(
    tmp_path,
    monkeypatch,
    principal,
    *,
    memory_scope,
):
    agent = object.__new__(comprehensive.ComprehensiveAgent)
    agent.memory = memory.MemorySystem()
    agent.memory_scope = memory_scope
    agent.principal = principal
    agent.session_id = "session-1"
    agent.current_run_id = "run-1"
    agent.audit_enabled = True
    agent.tool_registry = ToolRegistry.builtin()
    agent._add_memory_tools()
    return agent


def test_memory_record_persists_owner_session_and_run(tmp_path, monkeypatch):
    system = memory.MemorySystem()

    record = system.add(
        "Server A uses Nginx",
        scope="user:alice",
        owner_id="alice",
        session_id="session-1",
        run_id="run-1",
    )

    reloaded = memory.MemorySystem().get(record["id"])
    assert reloaded["owner_id"] == "alice"
    assert reloaded["session_id"] == "session-1"
    assert reloaded["run_id"] == "run-1"


def test_scope_policy_separates_users_and_sessions():
    developer = principal_from_roles("alice", {"developer"})

    assert can_read_scope(developer, "user:alice") is True
    assert can_read_scope(developer, "user:bob") is False
    assert can_read_scope(
        developer,
        "session:session-1",
        session_id="session-1",
    ) is True
    assert can_read_scope(
        developer,
        "session:session-2",
        session_id="session-1",
    ) is False
    assert can_write_scope(developer, "global") is False
    assert can_write_scope(developer, "user:alice") is True


def test_viewer_cannot_write_memory_or_read_private_scope(
    tmp_path,
    monkeypatch,
):
    viewer = principal_from_roles("viewer-1", {"viewer"})
    agent = _memory_agent(
        tmp_path,
        monkeypatch,
        viewer,
        memory_scope="global",
    )

    added = agent.handlers["add_memory"]("private value")
    searched = agent.handlers["search_memory"](
        "value",
        scope="user:other",
    )

    assert added.startswith("Permission denied")
    assert searched.startswith("Permission denied")
    assert agent.memory.memories == []


def test_developer_writes_own_scope_but_not_global(tmp_path, monkeypatch):
    developer = principal_from_roles("alice", {"developer"})
    agent = _memory_agent(
        tmp_path,
        monkeypatch,
        developer,
        memory_scope="user:alice",
    )

    added = agent.handlers["add_memory"]("alice preference")
    denied = agent.handlers["add_memory"](
        "shared production fact",
        scope="global",
    )

    assert added.startswith("Memory saved")
    assert denied.startswith("Permission denied")
    stored = agent.memory.memories[0]
    assert stored["scope"] == "user:alice"
    assert stored["owner_id"] == "alice"
    assert stored["session_id"] == "session-1"
    assert stored["run_id"] == "run-1"


def test_developer_cannot_manage_another_owners_memory(
    tmp_path,
    monkeypatch,
):
    developer = principal_from_roles("alice", {"developer"})
    agent = _memory_agent(
        tmp_path,
        monkeypatch,
        developer,
        memory_scope="user:alice",
    )
    record = agent.memory.add(
        "bob private memory",
        scope="user:bob",
        owner_id="bob",
    )

    archived = agent.handlers["archive_memory"](record["id"])

    assert archived.startswith("Permission denied")
    assert agent.memory.get(record["id"])["status"] == "active"


def test_candidate_approval_and_audit(tmp_path, monkeypatch):
    admin = principal_from_roles("admin", {"platform-admin"})
    agent = _memory_agent(
        tmp_path,
        monkeypatch,
        admin,
        memory_scope="global",
    )
    monkeypatch.setattr("agent.memory.lifecycle.MEMORY_NEAR_DUP_THRESHOLD", 0.60)
    monkeypatch.setattr("agent.memory.lifecycle.MEMORY_AUTO_MERGE_THRESHOLD", 0.99)
    agent.memory.add(
        "Server A uses Nginx",
        scope="global",
        owner_id="admin",
    )

    result = agent.handlers["add_memory"]("Server A uses Apache")
    candidate = next(
        item for item in agent.memory.memories
        if item["status"] == "candidate"
    )
    approved = agent.handlers["approve_memory"](candidate["id"])

    assert result.startswith("Memory saved as candidate")
    assert approved.startswith("Memory approved")
    assert agent.memory.get(candidate["id"])["status"] == "active"
    event_types = {
        event.event_type
        for event in AuditStore().list_events()
    }
    assert "memory.candidate_created" in event_types
    assert "memory.approved" in event_types


def test_memory_api_filters_scopes_and_approves_candidate(
    tmp_path,
    monkeypatch,
):
    from fastapi.testclient import TestClient
    from api.main import app

    monkeypatch.setattr(config, "API_AUTH_TOKEN", "developer-token")
    monkeypatch.setattr(config, "API_AUTH_USER", "alice")
    monkeypatch.setattr(config, "API_AUTH_ROLES", ["developer"])
    monkeypatch.setattr("agent.memory.lifecycle.MEMORY_NEAR_DUP_THRESHOLD", 0.60)
    monkeypatch.setattr("agent.memory.lifecycle.MEMORY_AUTO_MERGE_THRESHOLD", 0.99)

    system = memory.MemorySystem()
    system.add(
        "shared global fact",
        scope="global",
        owner_id="",
    )
    system.add(
        "alice private fact",
        scope="user:alice",
        owner_id="alice",
    )
    system.add(
        "bob private fact",
        scope="user:bob",
        owner_id="bob",
    )
    system.add(
        "alice server uses Nginx",
        scope="user:alice",
        owner_id="alice",
    )
    candidate = system.add(
        "alice server uses Apache",
        scope="user:alice",
        owner_id="alice",
    )
    assert candidate["status"] == "candidate"

    client = TestClient(app)
    headers = {"Authorization": "Bearer developer-token"}
    listed = client.get("/api/memory/", headers=headers)
    denied_scope = client.get(
        "/api/memory/?scope=user:bob",
        headers=headers,
    )
    approved = client.post(
        f"/api/memory/{candidate['id']}/approve",
        headers=headers,
    )

    assert listed.status_code == 200
    scopes = {item["scope"] for item in listed.json()["memories"]}
    assert scopes == {"global", "user:alice"}
    assert denied_scope.status_code == 403
    assert approved.status_code == 200
    assert approved.json()["status"] == "active"

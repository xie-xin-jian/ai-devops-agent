"""Cross-subsystem RunContext, checkpoint, and MCP isolation tests."""

import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from agent import background, config, cron, mcp
from agent.action_router import get_action
from agent.run_checkpoint import RunCheckpointStore
from agent.run_context import create_run_context, initialize_checkpoint


def test_task_claim_and_complete_update_run_checkpoint(
    isolated_tasks_dir,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(
        "agent.run_checkpoint.RUNS_DIR",
        tmp_path / "runs",
    )
    from api.main import app
    client = TestClient(app)

    created = client.post(
        "/api/tasks/",
        json={"subject": "inspect host"},
    )
    task_id = created.json()["id"]
    claimed = client.post(f"/api/tasks/{task_id}/claim", json={})
    task = claimed.json()
    completed = client.post(
        f"/api/tasks/{task_id}/complete",
        json={"result": "ok"},
    )

    assert claimed.status_code == 200
    assert task["run_id"]
    checkpoint = RunCheckpointStore(tmp_path / "runs").get(task["run_id"])
    assert checkpoint.source == "task"
    assert completed.status_code == 200
    assert checkpoint.status == "completed"


def test_cron_execution_uses_unified_run_context(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "agent.run_checkpoint.RUNS_DIR",
        tmp_path / "runs",
    )
    captured = {}
    saved = []

    class FakeAgent:
        def run(self, prompt):
            captured["context"] = cron._active_cron_context
            return "cron output"

    monkeypatch.setattr(
        cron,
        "_create_cron_agent",
        lambda: FakeAgent(),
    )
    monkeypatch.setattr(
        cron,
        "_save_cron_run_log",
        lambda *args, **kwargs: saved.append((args, kwargs)),
    )

    job = cron.CronJob(
        id="cron-run",
        cron="* * * * *",
        prompt="check disk",
    )
    cron._execute_cron_job_sync(
        job,
        cron.datetime(2026, 1, 1, 12, 0),
    )

    context = captured["context"]
    checkpoint = RunCheckpointStore(tmp_path / "runs").get(
        context.run_id
    )
    assert context.source == "cron"
    assert context.resource_id == "cron-run"
    assert checkpoint.source == "cron"
    assert saved[0][1]["run_id"] == context.run_id


def test_background_run_uses_checkpoint_and_sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(background, "BACKGROUND_DIR", tmp_path / "background")
    monkeypatch.setattr(
        "agent.run_checkpoint.RUNS_DIR",
        tmp_path / "runs",
    )
    background.BACKGROUND_DIR.mkdir(parents=True, exist_ok=True)

    class FakeSandboxManager:
        created = False
        cleaned = False

        def create(self, run_id, *, source_workspace=None, **kwargs):
            self.created = True
            return SimpleNamespace(run_id=run_id)

        def run(self, run_id, command, cwd=None):
            return "background output"

        def cleanup(self, run_id):
            self.cleaned = True

    monkeypatch.setattr(background, "SandboxManager", FakeSandboxManager)
    bg_id = background.start_background_task(
        SimpleNamespace(
            name="bash",
            input={"command": "echo bg"},
            id="call-bg",
        ),
        {},
        lambda *args: None,
        session_id="session-bg",
        parent_run_id="run-parent",
    )

    for _ in range(50):
        if background.background_tasks[bg_id]["status"] == "completed":
            break
        time.sleep(0.02)

    task = background.background_tasks[bg_id]
    checkpoint = RunCheckpointStore(tmp_path / "runs").get(task["run_id"])
    assert task["status"] == "completed"
    assert checkpoint.source == "background"
    assert checkpoint.parent_run_id == "run-parent"
    assert checkpoint.status == "completed"


def test_mcp_tools_are_filtered_by_owner_and_session(monkeypatch):
    clients = {}

    def make_client(name, owner_id, session_id):
        client = mcp.MCPClient(name)
        client.owner_id = owner_id
        client.session_id = session_id
        client.register(
            [{"name": "read", "inputSchema": {}}],
            {"read": lambda: name},
        )
        return client

    clients["alice"] = make_client("alice", "alice", "session-1")
    clients["bob"] = make_client("bob", "bob", "session-2")
    clients["shared"] = make_client("shared", "", "")
    monkeypatch.setattr(mcp, "mcp_clients", clients)

    tools, _ = mcp.assemble_tool_pool(
        [],
        {},
        {"owner_id": "alice", "session_id": "session-1"},
    )
    names = {tool["name"] for tool in tools}

    assert "mcp__alice__read" in names
    assert "mcp__shared__read" in names
    assert "mcp__bob__read" not in names


def test_chat_session_list_endpoint(monkeypatch):
    from datetime import datetime
    from api import main as api_main

    class FakeAgent:
        def get_messages(self):
            return [
                {"role": "user", "content": "inspect nginx"},
                {"role": "assistant", "content": "done"},
            ]

    monkeypatch.setattr(api_main, "_sessions", {
        "session-api": {
            "owner_id": "api-user",
            "last_used": datetime.now(),
            "agent": FakeAgent(),
        },
    })

    client = TestClient(api_main.app)
    response = client.get("/api/chat/sessions")

    assert response.status_code == 200
    assert response.json()["sessions"][0]["title"] == "inspect nginx"

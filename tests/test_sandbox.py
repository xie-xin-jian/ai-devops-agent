"""Docker sandbox lifecycle and isolation tests."""

import time
import sys
from types import SimpleNamespace

import pytest

from agent.core import comprehensive
from agent.platform import config
from agent.core import pipeline
from agent.sandbox.manager import (
    cleanup_orphan_sandboxes,
    DockerBackend,
    SandboxError,
    SandboxManager,
    SandboxTimeout,
    SandboxUnavailable,
)
from agent.sandbox.manager import list_sandbox_sessions
from agent.orchestration.pending_actions import PendingActionStore
from agent.platform.identity import system_admin_principal
from agent.tools.executor import ToolExecutor
from agent.tools.registry import ToolRegistry


class FakeContainerHandle:
    def __init__(self, container_id="container-1", output="ok", delay=0.0):
        self.id = container_id
        self.output = output
        self.delay = delay
        self.exec_calls = []
        self.killed = False
        self.removed = False

    def exec(self, command, cwd, timeout_seconds):
        self.exec_calls.append({
            "command": command,
            "cwd": cwd,
            "timeout_seconds": timeout_seconds,
        })
        if self.delay:
            time.sleep(self.delay)
        return 0, self.output

    def kill(self):
        self.killed = True

    def remove(self, force=True):
        self.removed = True


class FakeSandboxBackend:
    def __init__(self, *, available=True, handle=None):
        self.available = available
        self.handle = handle or FakeContainerHandle()
        self.create_calls = []

    def ping(self):
        return self.available

    def create(self, *, name, spec, workspace_host_path, labels):
        if not self.available:
            raise SandboxUnavailable("Docker unavailable")
        self.create_calls.append({
            "name": name,
            "spec": spec,
            "workspace_host_path": workspace_host_path,
            "labels": labels,
        })
        return self.handle


def test_sandbox_create_uses_isolated_workspace_and_hardening(tmp_path):
    backend = FakeSandboxBackend()
    manager = SandboxManager(
        backend=backend,
        base_dir=tmp_path,
        enabled=True,
    )

    session = manager.create("run-1")

    assert session.workspace_host_path.startswith(str(tmp_path))
    assert session.workspace_container_path == "/workspace"
    call = backend.create_calls[0]
    assert call["spec"].network_disabled is True
    assert call["spec"].user != "0:0"
    assert call["spec"].read_only_root is True
    assert call["spec"].pids_limit >= 16
    assert call["labels"]["run-id"] == "run-1"


def test_sandbox_runs_command_and_cleans_up(tmp_path):
    handle = FakeContainerHandle(output="hello")
    backend = FakeSandboxBackend(handle=handle)
    manager = SandboxManager(
        backend=backend,
        base_dir=tmp_path,
        enabled=True,
    )
    session = manager.create("run-2")

    output = manager.run("run-2", "echo hello")
    manager.cleanup("run-2")

    assert "hello" in output
    assert handle.exec_calls[0]["cwd"] == "/workspace"
    assert handle.removed is True
    assert manager.get("run-2") is None
    assert not (tmp_path / "run-2").exists()
    assert session.container_id == "container-1"


def test_sandbox_timeout_kills_container(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SANDBOX_TIMEOUT_SECONDS", 1)
    handle = FakeContainerHandle(delay=2.0)
    manager = SandboxManager(
        backend=FakeSandboxBackend(handle=handle),
        base_dir=tmp_path,
        enabled=True,
    )
    manager.create("run-timeout")

    with pytest.raises(SandboxTimeout, match="timed out"):
        manager.run("run-timeout", "sleep 10")

    assert handle.killed is True
    assert manager.get("run-timeout").status == "timed_out"


def test_sandbox_rejects_working_directory_escape(tmp_path):
    manager = SandboxManager(
        backend=FakeSandboxBackend(),
        base_dir=tmp_path,
        enabled=True,
    )
    manager.create("run-path")

    with pytest.raises(SandboxError, match="escapes"):
        manager.run("run-path", "pwd", cwd="../host")

    with pytest.raises(SandboxError, match="under /workspace"):
        manager.run("run-path", "pwd", cwd="/etc")


def test_docker_backend_requires_remote_host(monkeypatch):
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setattr(config, "SANDBOX_ALLOW_LOCAL_DOCKER", False)

    with pytest.raises(SandboxUnavailable, match="DOCKER_HOST"):
        DockerBackend().ping()


def test_docker_backend_uses_hardened_container_options(
    tmp_path,
    monkeypatch,
):
    captured = {}

    class FakeContainers:
        def run(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(id="docker-container")

    fake_client = SimpleNamespace(
        ping=lambda: True,
        containers=FakeContainers(),
    )
    monkeypatch.setenv("DOCKER_HOST", "tcp://docker.example:2376")
    monkeypatch.setitem(
        sys.modules,
        "docker",
        SimpleNamespace(from_env=lambda: fake_client),
    )

    manager = SandboxManager(
        backend=DockerBackend(),
        base_dir=tmp_path,
        enabled=True,
    )
    manager.create("run-docker")

    assert captured["network_disabled"] is True
    assert captured["user"] != "0:0"
    assert captured["read_only"] is True
    assert captured["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in captured["security_opt"]
    assert captured["pids_limit"] >= 16
    assert "/var/run/docker.sock" not in str(captured["volumes"])


def test_agent_requires_approval_before_sandbox_bash(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "source"
    source.mkdir()
    monkeypatch.setattr(comprehensive, "WORKDIR", source)
    handle = FakeContainerHandle(output="sandboxed")
    manager = SandboxManager(
        backend=FakeSandboxBackend(handle=handle),
        base_dir=tmp_path / "sandboxes",
        enabled=True,
    )
    agent = object.__new__(comprehensive.ComprehensiveAgent)
    agent.current_run_id = "run-agent"
    agent.session_id = "session-agent"
    agent.principal = system_admin_principal()
    agent.pending_action_store = PendingActionStore(
        tmp_path / "agent-actions.json"
    )
    agent._pending_action_notifications = []
    agent._last_user_query = "echo sandboxed"
    agent.tool_context = None
    agent.audit_enabled = False
    agent.sandbox_manager = manager
    agent.tool_registry = ToolRegistry.builtin()
    agent.tool_executor = ToolExecutor(
        agent.tool_registry,
        sandbox_manager=manager,
        principal=agent.principal,
    )

    monkeypatch.setattr(
        "agent.tools.shell.run_bash",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("host bash must not run")
        ),
    )

    output = agent._handle_tool_call(
        SimpleNamespace(
            name="bash",
            input={"command": "echo sandboxed"},
        )
    )
    monkeypatch.setattr(pipeline, "trigger_hooks", lambda *args: None)

    assert output.startswith("Approval required")
    assert handle.exec_calls == []
    assert agent.pending_action_store.list()[0].payload["tool"] == "bash"


def test_approved_bash_never_falls_back_to_host_when_sandbox_unavailable(
    tmp_path,
    monkeypatch,
):
    from agent.orchestration import pending_executor as pending_action_executor

    class UnavailableSandboxManager:
        def create(self, run_id, **kwargs):
            raise SandboxUnavailable("Docker unavailable")

        def cleanup(self, run_id):
            pass

    monkeypatch.setattr(
        "agent.tools.shell.run_bash",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("host bash must not run")
        ),
    )
    monkeypatch.setattr(
        pending_action_executor,
        "SandboxManager",
        UnavailableSandboxManager,
    )

    action = SimpleNamespace(
        id="act_denied",
        steps=[{
            "tool": "bash",
            "input": {"command": "echo should-not-run"},
        }],
    )
    with pytest.raises(SandboxUnavailable, match="Docker unavailable"):
        pending_action_executor.execute_pending_action(
            action,
            system_admin_principal(),
        )


def test_sandbox_status_api_lists_active_sessions(
    tmp_path,
    monkeypatch,
):
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
            "status": "running",
            "workspace_host_path": "/tmp/sandbox",
            "created_at": 1.0,
        }],
    )
    from api.main import app
    client = TestClient(app)
    response = client.get("/api/sandboxes/")

    assert response.status_code == 200
    assert response.json()["active"][0]["run_id"] == "run-api"


def test_list_sandbox_sessions_uses_registry(tmp_path):
    manager = SandboxManager(
        backend=FakeSandboxBackend(),
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


def test_cleanup_orphan_sandboxes_removes_containers_and_workspaces(
    tmp_path,
):
    base_dir = tmp_path / ".sandboxes"
    (base_dir / "run-1").mkdir(parents=True)
    (base_dir / "run-1" / "file.txt").write_text("orphan", encoding="utf-8")

    class FakeRecoveryBackend:
        def ping(self):
            return True

        def remove_managed_containers(self):
            return 2

    result = cleanup_orphan_sandboxes(
        backend=FakeRecoveryBackend(),
        base_dir=base_dir,
    )

    assert result["containers_removed"] == 2
    assert result["workspaces_removed"] == 1
    assert list(base_dir.iterdir()) == []

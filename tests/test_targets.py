"""Project target configuration, browsing, and tool tests."""

from pathlib import Path
from types import SimpleNamespace

import pytest

import agent.platform.config as config
from agent.targets.service import browse_directories
from agent.targets.store import TargetStore
from agent.targets.tools import (
    run_target_glob,
    run_target_list_files,
    run_target_read_file,
    run_target_edit_file,
    run_target_write_file,
)
from agent.tools.executor import ToolExecutor
from agent.tools.policy import evaluate_tool_policy
from agent.tools.registry import ToolRegistry


def _configure_roots(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(config, "TARGET_BROWSE_ROOTS", (root.resolve(),))


def _store(tmp_path: Path, monkeypatch) -> TargetStore:
    return TargetStore()


def test_target_store_crud_and_browser(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    project = root / "trip"
    project.mkdir(parents=True)
    _configure_roots(monkeypatch, root.parent)

    store = _store(tmp_path, monkeypatch)
    target = store.create({
        "name": "旅游助手",
        "root": str(project),
        "service": "trip-planner",
        "health_url": "http://127.0.0.1:8001/health",
    })

    assert store.get(target.id).name == "旅游助手"
    assert browse_directories(str(root))["entries"][0]["name"] == "trip"

    updated = store.update(target.id, {"name": "旅游项目"})
    assert updated.name == "旅游项目"
    store.delete(target.id)
    assert store.get(target.id) is None


def test_target_store_rejects_shell_injection_in_service(tmp_path, monkeypatch):
    root = tmp_path / "projects"
    project = root / "trip"
    project.mkdir(parents=True)
    _configure_roots(monkeypatch, root)
    store = _store(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="valid systemd unit name"):
        store.create({
            "name": "旅游助手",
            "root": str(project),
            "service": "nginx; touch /tmp/pwned",
        })


def test_target_browser_rejects_path_outside_roots(tmp_path, monkeypatch):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    _configure_roots(monkeypatch, allowed)

    with pytest.raises(ValueError, match="TARGET_BROWSE_ROOTS"):
        browse_directories(str(outside))


def test_target_file_tools_are_confined_to_target(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    (root / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "logs").mkdir()
    (root / "logs" / "app.log").write_text("first\nsecond\n", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    _configure_roots(monkeypatch, root.parent)

    store = _store(tmp_path, monkeypatch)
    target = store.create({"name": "项目", "root": str(root)})

    assert "print('ok')" in run_target_read_file(target.id, "main.py")
    assert "main.py" in run_target_list_files(target.id)
    assert "logs/app.log" in run_target_glob(target.id, "**/*.log")
    assert "escapes target root" in run_target_read_file(
        target.id,
        str(outside),
    )


def test_target_sensitive_file_is_blocked(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    (root / ".env").write_text("SECRET=1", encoding="utf-8")
    _configure_roots(monkeypatch, root.parent)
    store = _store(tmp_path, monkeypatch)
    target = store.create({"name": "项目", "root": str(root)})

    assert "Sensitive file" in run_target_read_file(target.id, ".env")


def test_target_mutation_policies_require_approval():
    assert evaluate_tool_policy("target_read_file").requires_approval is False
    assert evaluate_tool_policy("target_restart").requires_approval is True
    assert evaluate_tool_policy("target_deploy").requires_approval is True
    assert evaluate_tool_policy("target_write_file").requires_approval is True
    assert evaluate_tool_policy("target_edit_file").requires_approval is True


def test_tool_executor_injects_active_target(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    (root / "main.py").write_text("print('target')\n", encoding="utf-8")
    _configure_roots(monkeypatch, root.parent)
    store = _store(tmp_path, monkeypatch)
    target = store.create({"name": "项目", "root": str(root)})
    executor = ToolExecutor(
        ToolRegistry.builtin(),
        target_id=target.id,
    )

    result = executor.execute(
        "target_read_file",
        {"path": "main.py"},
        run_id="run-test",
    )

    assert "print('target')" in result.output


def test_bash_executor_runs_on_host_in_target_root(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    _configure_roots(monkeypatch, root.parent)
    store = _store(tmp_path, monkeypatch)
    target = store.create({"name": "项目", "root": str(root)})
    executor = ToolExecutor(
        ToolRegistry.builtin(),
        target_id=target.id,
    )

    result = executor.execute(
        "bash",
        {"command": "python -c \"from pathlib import Path; print(Path.cwd())\""},
        run_id="run-host-bash",
    )

    assert "exit_code=0" in result.output
    assert str(root) in result.output


def test_target_write_and_edit_files_with_backup(tmp_path, monkeypatch):
    from agent.targets import tools as target_tools

    root = tmp_path / "project"
    root.mkdir()
    _configure_roots(monkeypatch, root.parent)
    monkeypatch.setattr(
        target_tools,
        "TARGET_BACKUP_ROOT",
        tmp_path / ".target_backups",
    )
    store = _store(tmp_path, monkeypatch)
    target = store.create({"name": "项目", "root": str(root)})

    written = run_target_write_file(
        target.id,
        "config/app.txt",
        "mode=dev\n",
    )
    edited = run_target_edit_file(
        target.id,
        "config/app.txt",
        "mode=dev",
        "mode=prod",
    )

    assert "Wrote" in written
    assert "mode=prod" in edited
    assert (root / "config" / "app.txt").read_text(
        encoding="utf-8"
    ) == "mode=prod\n"
    backups = list((tmp_path / ".target_backups" / target.id).rglob("app.txt"))
    assert len(backups) == 1


def test_target_write_rejects_sensitive_and_escape(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    _configure_roots(monkeypatch, root.parent)
    store = _store(tmp_path, monkeypatch)
    target = store.create({"name": "项目", "root": str(root)})

    sensitive = run_target_write_file(
        target.id,
        ".env",
        "SECRET=1",
    )
    escaped = run_target_write_file(
        target.id,
        str(tmp_path / "outside.txt"),
        "outside",
    )

    assert "Sensitive file" in sensitive
    assert "escapes target root" in escaped


def test_target_restart_uses_systemctl_argv_without_shell(
    tmp_path,
    monkeypatch,
):
    from agent.targets import tools as target_tools

    root = tmp_path / "project"
    root.mkdir()
    _configure_roots(monkeypatch, root.parent)
    store = _store(tmp_path, monkeypatch)
    target = store.create({
        "name": "项目",
        "root": str(root),
        "service": "trip-planner.service",
    })
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return SimpleNamespace(
            returncode=0,
            stdout="restarted",
            stderr="",
        )

    monkeypatch.setattr(target_tools.subprocess, "run", fake_run)
    monkeypatch.setattr(target_tools.time, "sleep", lambda _: None)

    result = target_tools.run_target_restart(target.id)

    assert "exit_code=0" in result
    assert captured["cmd"] == [
        "systemctl",
        "restart",
        "trip-planner.service",
    ]
    assert "shell" not in captured["kwargs"]


def test_target_api_browse_and_create(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from api.main import app

    allowed = tmp_path / "projects"
    project = allowed / "trip"
    project.mkdir(parents=True)
    _configure_roots(monkeypatch, allowed)
    _store(tmp_path, monkeypatch)
    client = TestClient(app)

    browse = client.get("/api/targets/browse", params={"path": str(allowed)})
    created = client.post(
        "/api/targets/",
        json={"name": "旅游助手", "root": str(project)},
    )

    assert browse.status_code == 200
    assert browse.json()["entries"][0]["name"] == "trip"
    assert created.status_code == 200
    assert created.json()["name"] == "旅游助手"



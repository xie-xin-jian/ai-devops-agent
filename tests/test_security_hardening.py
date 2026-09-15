"""Security hardening regression tests."""

import pytest

import agent.config as config
from agent import mcp, permission
from agent.tools import shell


def test_api_requires_bearer_token_when_configured(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from api.main import app

    monkeypatch.setattr(config, "API_AUTH_TOKEN", "test-secret")
    client = TestClient(app)

    assert client.get("/health").status_code == 200
    assert client.get("/api/messages/").status_code == 401

    response = client.get(
        "/api/messages/",
        headers={"Authorization": "Bearer test-secret"},
    )
    assert response.status_code == 200


def test_bash_rejects_cwd_outside_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(shell, "WORKDIR", tmp_path)

    result = shell.run_bash("echo should-not-run", cwd=tmp_path.parent)

    assert "escapes workspace" in result


def test_permission_rejects_bash_cwd_outside_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(permission, "WORKDIR", tmp_path)
    block = {
        "name": "bash",
        "input": {"command": "echo hello", "cwd": str(tmp_path.parent)},
    }

    result = permission.permission_hook(block)

    assert result is not None
    assert "cwd escapes workspace" in result


def test_custom_mcp_shell_handler_is_disabled_by_default(monkeypatch):
    monkeypatch.setattr(mcp, "ENABLE_UNSAFE_MCP_SHELL", False)
    handler = mcp._build_handler({
        "name": "dangerous",
        "handler_type": "shell",
        "handler_config": {"command": "echo {value}"},
    })

    result = handler(value="test")

    assert "disabled" in result


def test_custom_mcp_shell_registration_is_rejected(monkeypatch):
    monkeypatch.setattr(mcp, "ENABLE_UNSAFE_MCP_SHELL", False)

    result = mcp.register_custom_server(
        "unsafe",
        "unsafe shell tools",
        [{
            "name": "run",
            "description": "run a command",
            "input_schema": {"type": "object", "properties": {}},
            "handler_type": "shell",
            "handler_config": {"command": "echo unsafe"},
        }],
    )

    assert result.startswith("Cannot register shell MCP tools")

"""Subagent tool-boundary tests."""

from types import SimpleNamespace

from agent.extensions.subagent import SUB_TOOLS, spawn_subagent


def _response(*blocks):
    return SimpleNamespace(content=list(blocks))


def test_subagent_does_not_expose_bash():
    names = {tool["name"] for tool in SUB_TOOLS}

    assert "bash" not in names
    assert names == {"read_file", "write_file", "edit_file", "glob"}


def test_subagent_bash_call_is_rejected_before_host_execution(monkeypatch):
    host_calls = []
    monkeypatch.setattr(
        "agent.tools.executor.run_host_bash",
        lambda *args, **kwargs: host_calls.append((args, kwargs)) or "HOST",
    )

    class Messages:
        def __init__(self):
            self.calls = 0
            self.second_request = None

        def create(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return _response(SimpleNamespace(
                    type="tool_use",
                    id="call_bash",
                    name="bash",
                    input={"command": "echo should-not-run"},
                ))
            self.second_request = kwargs
            return _response(SimpleNamespace(type="text", text="done"))

    messages = Messages()
    client = SimpleNamespace(messages=messages)

    result = spawn_subagent(client, "test-model", "try bash")

    assert result == "done"
    assert host_calls == []
    second_messages = messages.second_request["messages"]
    assert any(
        "not in the run allowlist" in str(message["content"])
        for message in second_messages
    )

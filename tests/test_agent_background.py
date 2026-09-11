"""Agent background-task integration tests."""

from types import SimpleNamespace

from agent import comprehensive


def test_background_result_hint_uses_registered_tool(monkeypatch):
    agent = object.__new__(comprehensive.ComprehensiveAgent)
    agent.tools = []
    agent.handlers = {}

    monkeypatch.setattr(comprehensive, "trigger_hooks", lambda *args: None)
    monkeypatch.setattr(
        comprehensive,
        "should_run_background",
        lambda tool_name, tool_input: True,
    )
    monkeypatch.setattr(
        comprehensive,
        "start_background_task",
        lambda *args: "bg_0001",
    )

    output = agent._handle_tool_call(
        SimpleNamespace(name="bash", input={"command": "npm install"})
    )

    assert "bg_0001" in output
    assert "list_background_tasks" in output

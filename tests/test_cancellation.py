"""Agent cancellation tests."""

import threading
from types import SimpleNamespace

from agent import comprehensive


def test_cancelled_tool_turns_keep_valid_message_pairing(monkeypatch):
    agent = object.__new__(comprehensive.ComprehensiveAgent)
    agent.messages = []
    agent.model = "test-model"
    agent.recovery = SimpleNamespace(current_model="test-model")

    cancel_event = threading.Event()
    tool_blocks = [
        SimpleNamespace(type="tool_use", name="first", input={}, id="call_1"),
        SimpleNamespace(type="tool_use", name="second", input={}, id="call_2"),
    ]

    monkeypatch.setattr(comprehensive, "trigger_hooks", lambda *args: None)
    monkeypatch.setattr(comprehensive, "collect_background_results", lambda: [])
    monkeypatch.setattr(agent, "_compact_if_needed", lambda messages: messages)
    monkeypatch.setattr(
        agent,
        "_call_api",
        lambda messages: SimpleNamespace(content=tool_blocks),
    )

    def handle_tool(block):
        cancel_event.set()
        return "first result"

    monkeypatch.setattr(agent, "_handle_tool_call", handle_tool)

    events = list(agent.run_stream("run two tools", cancel_event))

    assert events[-1]["type"] == "cancelled"
    assert [message["role"] for message in agent.messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    tool_results = agent.messages[2]["content"]
    assert [result["tool_use_id"] for result in tool_results] == ["call_1", "call_2"]
    assert tool_results[0]["content"] == "first result"
    assert tool_results[1]["content"] == "Error: cancelled by user"

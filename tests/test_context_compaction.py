"""Regression tests for context compaction boundaries."""

from copy import deepcopy
from types import SimpleNamespace

from agent import comprehensive


def test_compact_waits_for_tool_result_pair(monkeypatch):
    agent = object.__new__(comprehensive.ComprehensiveAgent)
    agent.client = object()
    agent.model = "test-model"
    agent.recovery = SimpleNamespace(current_model="test-model")
    agent.messages = []
    agent._last_user_query = ""
    agent._pending_compaction = False
    agent.tools = []
    agent.handlers = {}
    agent._add_compact_tool()

    compact_block = SimpleNamespace(
        type="tool_use",
        name="compact",
        input={},
        id="call_compact",
    )
    final_block = SimpleNamespace(type="text", text="done")
    responses = iter([
        SimpleNamespace(content=[compact_block]),
        SimpleNamespace(content=[final_block]),
    ])
    observed_history = []

    def fake_compact_history(messages, client, model):
        observed_history.append(deepcopy(messages))
        return [{"role": "user", "content": "[Compacted]\n\nsummary"}]

    monkeypatch.setattr(comprehensive, "trigger_hooks", lambda *args: None)
    monkeypatch.setattr(comprehensive, "collect_background_results", lambda: [])
    monkeypatch.setattr(comprehensive, "compact_history", fake_compact_history)
    monkeypatch.setattr(agent, "_compact_if_needed", lambda messages: messages)
    monkeypatch.setattr(agent, "_call_api", lambda messages: next(responses))

    events = list(agent.run_stream("compact now"))

    assert events[-1]["type"] == "done"
    assert len(observed_history) == 1
    messages = observed_history[0]
    assert messages[-2]["role"] == "assistant"
    assert messages[-2]["content"][0].id == "call_compact"
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == [{
        "type": "tool_result",
        "tool_use_id": "call_compact",
        "content": "History compaction scheduled for the next safe boundary.",
    }]
    assert agent.messages[0]["content"].startswith("[Compacted]")

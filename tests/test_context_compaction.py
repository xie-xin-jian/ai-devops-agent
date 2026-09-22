"""Regression tests for context compaction boundaries."""

from copy import deepcopy
from types import SimpleNamespace

from agent import comprehensive, context_compact, error_recovery


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


def test_recover_context_overflow_reports_reduction(monkeypatch):
    original = [
        {"role": "user", "content": "x" * 1000},
        {"role": "assistant", "content": "y" * 1000},
    ]
    compacted = [{"role": "user", "content": "[Compacted]\nsmall"}]

    monkeypatch.setattr(
        context_compact,
        "tool_result_budget",
        lambda messages: messages,
    )
    monkeypatch.setattr(
        context_compact,
        "micro_compact",
        lambda messages: messages,
    )
    monkeypatch.setattr(
        context_compact,
        "reactive_compact",
        lambda messages, client, model: compacted,
    )

    result, stats = error_recovery.recover_context_overflow(
        original,
        client=object(),
        model="test-model",
    )

    assert result == compacted
    assert stats["reduced"] is True
    assert stats["after"] < stats["before"]


def test_recover_context_overflow_falls_back_to_snip(monkeypatch):
    original = [{"role": "user", "content": "x" * 1000}]
    compacted = [{"role": "user", "content": "y" * 900}]
    snipped = [{"role": "user", "content": "z"}]

    monkeypatch.setattr(
        context_compact,
        "tool_result_budget",
        lambda messages: messages,
    )
    monkeypatch.setattr(
        context_compact,
        "micro_compact",
        lambda messages: messages,
    )
    monkeypatch.setattr(
        context_compact,
        "reactive_compact",
        lambda messages, client, model: compacted,
    )
    monkeypatch.setattr(
        context_compact,
        "snip_compact",
        lambda messages: snipped,
    )

    result, stats = error_recovery.recover_context_overflow(
        original,
        client=object(),
        model="test-model",
    )

    assert result == snipped
    assert stats["reduced"] is True


def test_output_limit_error_classification():
    assert error_recovery.is_output_limit_error(
        RuntimeError("maximum output tokens exceeded")
    )
    assert not error_recovery.is_output_limit_error(
        RuntimeError("context_length_exceeded")
    )


def test_agent_retries_once_after_context_recovery(monkeypatch):
    agent = object.__new__(comprehensive.ComprehensiveAgent)
    agent.client = object()
    agent.model = "test-model"
    agent.recovery = SimpleNamespace(current_model="test-model")
    agent.messages = []
    agent._last_user_query = ""
    agent._pending_compaction = False
    agent.tools = []
    agent.handlers = {}
    calls = 0

    def fake_call_api(messages):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("context_length_exceeded")
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="done")]
        )

    def fake_recover(messages, client, model):
        return (
            [{"role": "user", "content": "[Compacted]\nsmall"}],
            {"before": 1000, "after": 100, "reduced": True},
        )

    monkeypatch.setattr(comprehensive, "trigger_hooks", lambda *args: None)
    monkeypatch.setattr(comprehensive, "collect_background_results", lambda: [])
    monkeypatch.setattr(comprehensive, "recover_context_overflow", fake_recover)
    monkeypatch.setattr(agent, "_compact_if_needed", lambda messages: messages)
    monkeypatch.setattr(agent, "_call_api", fake_call_api)

    events = list(agent.run_stream("test recovery"))

    assert calls == 2
    assert events[-1]["type"] == "done"
    assert any(
        event.get("message") == "Prompt 过长，执行上下文恢复压缩..."
        for event in events
    )

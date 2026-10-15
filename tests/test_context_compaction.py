"""Regression tests for context compaction boundaries."""

from copy import deepcopy
from types import SimpleNamespace

from agent.core import comprehensive, context_compact, error_recovery
from agent.core import pipeline
from agent.platform.identity import system_admin_principal
from agent.sandbox.manager import SandboxManager
from agent.tools.executor import ToolExecutor
from agent.tools.registry import ToolRegistry
from agent.tools.policy import ToolPolicyContext


def test_compact_waits_for_tool_result_pair(monkeypatch):
    agent = object.__new__(comprehensive.ComprehensiveAgent)
    agent.client = object()
    agent.model = "test-model"
    agent.recovery = SimpleNamespace(current_model="test-model")
    agent.messages = []
    agent._last_user_query = ""
    agent._pending_compaction = False
    agent.principal = system_admin_principal()
    agent.tool_context = ToolPolicyContext()
    agent.tool_registry = ToolRegistry.builtin()
    agent.sandbox_manager = SandboxManager()
    agent.tool_executor = ToolExecutor(
        agent.tool_registry,
        sandbox_manager=agent.sandbox_manager,
        principal=agent.principal,
        tool_context=agent.tool_context,
    )
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

    monkeypatch.setattr(pipeline, "collect_background_results", lambda: [])
    monkeypatch.setattr(pipeline, "compact_history", fake_compact_history)
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

    monkeypatch.setattr(pipeline, "collect_background_results", lambda: [])
    monkeypatch.setattr(pipeline, "recover_context_overflow", fake_recover)
    monkeypatch.setattr(agent, "_compact_if_needed", lambda messages: messages)
    monkeypatch.setattr(agent, "_call_api", fake_call_api)

    events = list(agent.run_stream("test recovery"))

    assert calls == 2
    assert events[-1]["type"] == "done"
    assert any(
        event.get("message") == "Prompt 过长，执行上下文恢复压缩..."
        for event in events
    )


def test_head_tail_truncate_keeps_both_ends():
    text = "START" + "m" * 5000 + "END"
    result = context_compact.head_tail_truncate(text, 1000)

    assert len(result) < 1000 + 60
    assert result.startswith("START")
    assert result.endswith("END")
    assert "chars omitted" in result


def test_head_tail_truncate_passthrough_when_short():
    assert context_compact.head_tail_truncate("short output", 1000) == "short output"


def test_history_tool_content_keeps_small_output():
    assert context_compact.history_tool_content("t1", "ok") == "ok"


def test_history_tool_content_persists_large_output(tmp_path, monkeypatch):
    monkeypatch.setattr(context_compact, "TOOL_RESULTS_DIR", tmp_path)
    output = "LINE\n" * 4000

    result = context_compact.history_tool_content("toolu_big", output)

    assert "[Large tool output persisted to " in result
    assert str(tmp_path) in result
    assert len(result) < context_compact.HISTORY_TOOL_LIMIT
    assert list(tmp_path.glob("toolu_big_*.txt"))


def test_trim_by_size_keeps_head_and_recent_tail():
    messages = [{"role": "user", "content": "原始需求"}]
    messages += [
        {"role": "user", "content": f"m{i}" + "x" * 2000}
        for i in range(20)
    ]

    trimmed = context_compact.trim_by_size(messages, 5000)

    assert trimmed[0]["content"] == "原始需求"
    assert trimmed[-1]["content"].startswith("m19")
    assert any("earlier messages dropped" in str(m.get("content")) for m in trimmed)
    assert (
        context_compact.estimate_size(trimmed)
        <= 5000 + len(str(trimmed[-1]))
    )


def test_trim_by_size_noop_under_budget():
    messages = [{"role": "user", "content": "hi"}]
    assert context_compact.trim_by_size(messages, 5000) is messages


def test_compact_if_needed_bounds_spiky_history(tmp_path, monkeypatch):
    """复现服务器上 "每轮 ctx 冲到 24 万字节" 的场景，确认压缩后回到预算内。"""
    monkeypatch.setattr(context_compact, "TOOL_RESULTS_DIR", tmp_path)
    agent = object.__new__(comprehensive.ComprehensiveAgent)
    messages = [{"role": "user", "content": "deploy the project"}]
    for index in range(3):
        messages.append({
            "role": "assistant",
            "content": [{
                "type": "tool_use",
                "id": f"toolu_{index}",
                "name": "bash",
                "input": {"command": "make deploy"},
            }],
        })
        messages.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": f"toolu_{index}",
                "content": "L" * 60000,
            }],
        })

    assert context_compact.estimate_size(messages) > 120000

    compacted = agent._compact_if_needed(messages)

    assert context_compact.estimate_size(compacted) <= 120000

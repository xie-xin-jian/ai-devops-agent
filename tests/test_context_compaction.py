"""Regression tests for context compaction boundaries."""

from copy import deepcopy
from types import SimpleNamespace

from agent.core import comprehensive, context_compact, context_manager, error_recovery
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

    def fake_checkpoint(messages, client, model, *, goal=""):
        observed_history.append(deepcopy(messages))
        return [
            {
                "role": "user",
                "content": context_compact.SUMMARY_PREFIX + f"goal: {goal}",
            }
        ]

    monkeypatch.setattr(pipeline, "collect_background_results", lambda: [])
    monkeypatch.setattr(pipeline, "checkpoint_compact", fake_checkpoint)
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
    assert agent.messages[0]["content"].startswith(context_compact.SUMMARY_PREFIX)


def test_recover_context_overflow_reports_reduction(monkeypatch):
    original = [
        {"role": "user", "content": "x" * 1000},
        {"role": "assistant", "content": "y" * 1000},
    ]
    compacted = [{"role": "user", "content": context_compact.SUMMARY_PREFIX + "small"}]

    monkeypatch.setattr(
        context_compact,
        "checkpoint_compact",
        lambda messages, client, model, goal="": compacted,
    )

    result, stats = error_recovery.recover_context_overflow(
        original,
        client=object(),
        model="test-model",
    )

    assert result == compacted
    assert stats["reduced"] is True
    assert stats["after"] < stats["before"]


def test_recover_context_overflow_falls_back_to_trim(monkeypatch):
    original = [{"role": "user", "content": "x" * 1000}]
    checkpointed = [{"role": "user", "content": "y" * 900}]
    trimmed = [{"role": "user", "content": "z"}]

    monkeypatch.setattr(
        context_compact,
        "checkpoint_compact",
        lambda messages, client, model, goal="": checkpointed,
    )
    monkeypatch.setattr(
        context_compact,
        "tool_result_budget",
        lambda messages, max_bytes=None: messages,
    )
    monkeypatch.setattr(
        context_compact,
        "trim_by_size",
        lambda messages, max_bytes, keep_head=1: trimmed,
    )

    result, stats = error_recovery.recover_context_overflow(
        original,
        client=object(),
        model="test-model",
    )

    assert result == trimmed
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

    def fake_recover(messages, client, model, goal=""):
        return (
            [{"role": "user", "content": context_compact.SUMMARY_PREFIX + "small"}],
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
    # 裁剪只丢中段，不再往历史里插 "[N earlier messages dropped]" 占位符。
    assert not any(
        "earlier messages dropped" in str(m.get("content")) for m in trimmed
    )
    assert (
        context_compact.estimate_size(trimmed)
        <= 5000 + len(str(trimmed[-1]))
    )


def test_trim_by_size_noop_under_budget():
    messages = [{"role": "user", "content": "hi"}]
    assert context_compact.trim_by_size(messages, 5000) is messages


def test_checkpoint_compact_pins_goal_and_has_no_placeholder(tmp_path, monkeypatch):
    monkeypatch.setattr(context_compact, "TRANSCRIPT_DIR", tmp_path)
    monkeypatch.setattr(
        context_compact, "summarize_history", lambda messages, client, model: "done: x"
    )
    messages = [
        {"role": "user", "content": "deploy the project"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1"}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1"}]},
    ]

    compacted = context_compact.checkpoint_compact(
        messages, object(), "test-model", goal="deploy the project"
    )

    assert len(compacted) == 1
    text = compacted[0]["content"]
    assert "deploy the project" in text
    assert context_compact.SUMMARY_PREFIX in text
    assert "done: x" in text
    assert "[snipped" not in text
    assert "earlier messages dropped" not in text


def test_checkpoint_compact_truncates_when_user_message_exceeds_budget(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(context_compact, "TRANSCRIPT_DIR", tmp_path)
    monkeypatch.setattr(
        context_compact, "summarize_history", lambda messages, client, model: "done"
    )
    messages = [{"role": "user", "content": "x" * 20000}]

    compacted = context_compact.checkpoint_compact(
        messages, object(), "test-model", budget=4000
    )

    assert len(compacted) == 1
    assert len(compacted[0]["content"]) < 20000
    assert "truncated" in compacted[0]["content"]


def test_collect_real_user_messages_skips_summary_and_placeholders():
    messages = [
        {"role": "user", "content": "[Compacted]\nold summary"},
        {"role": "user", "content": "[snipped 12 messages: bash×3]"},
        {"role": "user", "content": "[5 earlier messages dropped to bound context size]"},
        {"role": "user", "content": "real request"},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t"}]},
    ]

    users = context_compact.collect_real_user_messages(messages)

    assert [context_compact.message_text(m) for m in users] == ["real request"]


def test_compact_if_needed_soft_limit_does_not_call_model(monkeypatch):
    """软水位只降级工具结果，不调模型、不产生压缩事件。"""
    agent = object.__new__(comprehensive.ComprehensiveAgent)
    agent.run_goal = "deploy"
    degraded = [{"role": "user", "content": "degraded"}]

    def fail_checkpoint(*args, **kwargs):
        raise AssertionError("软水位不应调用摘要模型")

    monkeypatch.setattr(context_manager, "checkpoint_compact", fail_checkpoint)
    monkeypatch.setattr(
        context_manager, "tool_result_budget", lambda messages, max_bytes=None: degraded
    )
    messages = [{"role": "user", "content": "x" * 40000}]

    result = agent._compact_if_needed(messages)

    assert result == degraded
    assert agent._last_compaction is None


def test_compact_if_needed_falls_back_to_fresh_window(monkeypatch):
    """摘要调用失败时开新窗口，而不是继续带着超窗历史。"""
    agent = object.__new__(comprehensive.ComprehensiveAgent)
    agent.run_goal = "deploy the project"
    agent.client = object()
    agent.recovery = SimpleNamespace(current_model="test-model")

    def broken_summary(*args, **kwargs):
        raise RuntimeError("context window exceeded")

    monkeypatch.setattr(context_manager, "checkpoint_compact", broken_summary)
    messages = [
        {"role": "user", "content": "deploy the project"},
        {"role": "assistant", "content": "y" * 60000},
    ]

    result = agent._compact_if_needed(messages)

    assert agent._last_compaction["status"] == "fresh_window"
    assert "deploy the project" in result[0]["content"]
    assert "[Compacted]" not in result[0]["content"]


def test_compact_if_needed_emits_windowed_events(monkeypatch):
    """每次硬压缩发出 started/finished 事件，窗口号递增。"""
    agent = object.__new__(comprehensive.ComprehensiveAgent)
    agent.run_goal = "deploy"
    agent.client = object()
    agent.recovery = SimpleNamespace(current_model="test-model")
    agent._compaction_window = 0

    monkeypatch.setattr(
        context_manager,
        "checkpoint_compact",
        lambda messages, client, model, goal="": [{"role": "user", "content": "small"}],
    )
    messages = [{"role": "user", "content": "x" * 60000}]

    agent._compact_if_needed(messages)
    first = agent._compaction_events

    assert [event["phase"] for event in first] == ["started", "finished"]
    assert {event["window"] for event in first} == {1}

    agent._compact_if_needed(messages)
    second = agent._compaction_events

    assert {event["window"] for event in second} == {2}


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


def _usage_response(input_tokens=0, output_tokens=0, cache_read=0, cache_write=0):
    return SimpleNamespace(
        content=[],
        usage=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_input_tokens=cache_read,
            cache_creation_input_tokens=cache_write,
        ),
    )


def _bare_agent():
    agent = object.__new__(comprehensive.ComprehensiveAgent)
    agent.model = "test-model"
    agent.recovery = SimpleNamespace(
        current_model="test-model",
        current_max_tokens=1000,
        consecutive_529=0,
    )
    agent.messages = []
    agent._last_user_query = ""
    agent._pending_compaction = False
    agent.principal = system_admin_principal()
    agent.tool_context = ToolPolicyContext()
    agent.tool_registry = ToolRegistry.builtin()
    return agent


def test_record_usage_accumulates_and_estimates_cost():
    agent = _bare_agent()
    agent._current_turn = 3

    for _ in range(2):
        agent._record_usage(
            _usage_response(input_tokens=1_000_000, output_tokens=100_000)
        )

    summary = agent._usage_summary()

    assert summary["calls"] == 2
    assert summary["input"] == 2_000_000
    assert summary["output"] == 200_000
    assert summary["est_cost_cny"] == 5.6


def test_usage_summary_reports_compaction_count():
    """压缩次数进入 run 汇总，done 事件可据此展示。"""
    agent = _bare_agent()
    agent._compaction_window = 3

    assert agent._usage_summary()["compactions"] == 3


def test_record_usage_ignores_response_without_usage():
    agent = _bare_agent()

    agent._record_usage(SimpleNamespace(content=[]))

    assert agent._usage_summary()["calls"] == 0
    assert agent._usage_summary()["est_cost_cny"] == 0.0


def test_call_api_records_usage():
    agent = _bare_agent()
    agent.client = SimpleNamespace(
        messages=SimpleNamespace(
            create=lambda **_kwargs: _usage_response(
                input_tokens=1200,
                output_tokens=340,
                cache_read=800,
                cache_write=64,
            )
        )
    )

    agent._call_api([{"role": "user", "content": "hi"}])

    assert agent._usage_total == {
        "calls": 1,
        "input": 1200,
        "output": 340,
        "cache_read": 800,
        "cache_write": 64,
    }


def test_done_event_carries_usage_and_resets_per_run(monkeypatch):
    agent = _bare_agent()
    agent.client = object()
    agent.sandbox_manager = SandboxManager()
    agent.tool_executor = ToolExecutor(
        agent.tool_registry,
        sandbox_manager=agent.sandbox_manager,
        principal=agent.principal,
        tool_context=agent.tool_context,
    )

    def fake_call_api(_messages):
        response = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="all good")],
            usage=SimpleNamespace(
                input_tokens=1500,
                output_tokens=200,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )
        agent._record_usage(response)
        return response

    monkeypatch.setattr(pipeline, "collect_background_results", lambda: [])
    monkeypatch.setattr(agent, "_compact_if_needed", lambda messages: messages)
    monkeypatch.setattr(agent, "_call_api", fake_call_api)

    first = list(agent.run_stream("check disk"))
    second = list(agent.run_stream("check disk again"))

    assert first[-1]["type"] == "done"
    assert first[-1]["usage"]["calls"] == 1
    assert first[-1]["usage"]["input"] == 1500
    assert first[-1]["usage"]["est_cost_cny"] == 0.0046
    # 新 run 重置累计，不把上一次的开销带进来
    assert second[-1]["usage"]["calls"] == 1
    assert second[-1]["usage"]["input"] == 1500

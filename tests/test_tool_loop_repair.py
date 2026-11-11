"""Tool message pairing repair tests."""

from types import SimpleNamespace

from agent.core.tool_loop import ToolLoopMixin


def _tool_use(tool_use_id: str):
    return {
        "type": "tool_use",
        "id": tool_use_id,
        "name": "bash",
        "input": {"command": "echo ok"},
    }


def _tool_result(tool_use_id: str, content: str = "ok"):
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
    }


def test_repair_inserts_missing_tool_result_immediately():
    messages = [
        {"role": "assistant", "content": [_tool_use("call_1")]},
        {"role": "assistant", "content": [{"type": "text", "text": "next"}]},
    ]

    repaired = ToolLoopMixin()._repair_message_sequence(messages)

    assert repaired[1]["role"] == "user"
    assert repaired[1]["content"][0]["tool_use_id"] == "call_1"
    assert repaired[2] == messages[1]


def test_repair_merges_missing_results_into_existing_user_message():
    messages = [
        {
            "role": "assistant",
            "content": [_tool_use("call_1"), _tool_use("call_2")],
        },
        {
            "role": "user",
            "content": [_tool_result("call_1", "first")],
        },
    ]

    repaired = ToolLoopMixin()._repair_message_sequence(messages)

    assert len(repaired) == 2
    ids = [
        block["tool_use_id"]
        for block in repaired[1]["content"]
        if block["type"] == "tool_result"
    ]
    assert ids == ["call_2", "call_1"]


def test_repair_preserves_text_in_next_user_message():
    messages = [
        {"role": "assistant", "content": [_tool_use("call_1")]},
        {"role": "user", "content": "continue with this"},
    ]

    repaired = ToolLoopMixin()._repair_message_sequence(messages)

    assert repaired[1]["content"][0]["type"] == "tool_result"
    assert repaired[1]["content"][1] == {
        "type": "text",
        "text": "continue with this",
    }


def test_repair_detects_sdk_style_block_objects():
    assistant = SimpleNamespace(
        role="assistant",
        content=[
            SimpleNamespace(
                type="tool_use",
                id="call_obj",
                name="bash",
                input={},
            )
        ],
    )
    messages = [
        {
            "role": assistant.role,
            "content": assistant.content,
        }
    ]

    repaired = ToolLoopMixin()._repair_message_sequence(messages)

    assert repaired[1]["role"] == "user"
    assert repaired[1]["content"][0]["tool_use_id"] == "call_obj"


def test_result_later_in_history_does_not_count_as_adjacent():
    messages = [
        {"role": "assistant", "content": [_tool_use("call_late")]},
        {"role": "assistant", "content": [{"type": "text", "text": "next"}]},
        {"role": "user", "content": [_tool_result("call_late")]},
    ]

    repaired = ToolLoopMixin()._repair_message_sequence(messages)

    assert repaired[1]["role"] == "user"
    assert repaired[1]["content"][0]["tool_use_id"] == "call_late"


class _LoopAgent(ToolLoopMixin):
    def __init__(self):
        self.audited = []
        self.current_run_id = "run_test"

    def _audit(self, event_type, message, **kwargs):
        self.audited.append((event_type, message, kwargs))


def _call(name="bash", **tool_input):
    return SimpleNamespace(name=name, input=tool_input or {"command": "df -h"})


def _attempt(agent, block):
    """模拟一次真实执行：先检查，未拦截则记一次执行。"""
    blocked = agent._check_repeated_call(block)
    if blocked:
        return blocked
    agent._note_executed_call(block)
    return ""


def test_repeated_identical_call_is_blocked_on_third_attempt():
    agent = _LoopAgent()
    block = _call(command="df -h")

    assert _attempt(agent, block) == ""
    assert _attempt(agent, block) == ""

    blocked = _attempt(agent, block)

    assert blocked.startswith("Blocked:")
    assert agent.audited[-1][0] == "loop.blocked"
    assert agent.audited[-1][2]["payload"]["count"] == 2


def test_different_arguments_are_not_blocked():
    agent = _LoopAgent()

    for _ in range(2):
        _attempt(agent, _call(command="df -h"))

    assert _attempt(agent, _call(command="free -h")) == ""
    assert _attempt(agent, _call(name="disk_usage", path="/")) == ""


def test_input_key_is_order_independent():
    agent = _LoopAgent()

    _attempt(agent, _call(command="df -h", timeout=5))
    _attempt(agent, _call(timeout=5, command="df -h"))

    assert _attempt(agent, _call(command="df -h", timeout=5)).startswith("Blocked:")


def test_polling_tools_are_exempt_from_repeat_guard():
    agent = _LoopAgent()

    for _ in range(6):
        assert _attempt(agent, _call(name="list_background_tasks")) == ""


def test_policy_blocked_call_does_not_count():
    agent = _LoopAgent()
    block = _call(command="rm -rf /")

    for _ in range(3):
        assert agent._check_repeated_call(block) == ""

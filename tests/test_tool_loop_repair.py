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

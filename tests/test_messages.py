"""Chat history serialization tests."""

from types import SimpleNamespace

from agent.messages import serialize_visible_messages


def test_serialize_visible_messages_keeps_only_text_dialogue():
    messages = [
        {"role": "user", "content": "check disk"},
        {
            "role": "assistant",
            "content": [
                SimpleNamespace(type="text", text="I will check it."),
                SimpleNamespace(type="tool_use", name="disk_usage", input={}),
            ],
        },
        {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "call_1",
                "content": "disk ok",
            }],
        },
        {"role": "assistant", "content": [{"type": "text", "text": "Disk is healthy."}]},
    ]

    assert serialize_visible_messages(messages) == [
        {"role": "user", "content": "check disk"},
        {"role": "assistant", "content": "I will check it."},
        {"role": "assistant", "content": "Disk is healthy."},
    ]


def test_serialize_visible_messages_skips_internal_messages():
    messages = [
        {"role": "user", "content": "[Compacted]\n\nsummary"},
        {"role": "user", "content": "<task_notification>done</task_notification>"},
        {"role": "user", "content": "visible question"},
    ]

    assert serialize_visible_messages(messages) == [
        {"role": "user", "content": "visible question"},
    ]

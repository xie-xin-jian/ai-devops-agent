"""Convert internal Agent messages into user-visible chat history."""

import re


_INTERNAL_PREFIXES = (
    "[Compacted]",
    "[snipped",
    "以下内容是对此前对话的压缩摘要",
    "<task_notification>",
    "<cron_job>",
)
_INTERNAL_PATTERNS = (re.compile(r"^\[\d+ earlier messages dropped"),)


def _get_value(block, key: str, default=""):
    if isinstance(block, dict):
        return block.get(key, default)
    return getattr(block, key, default)


def _extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)

    parts = []
    for block in content:
        if _get_value(block, "type") == "text":
            text = _get_value(block, "text")
            if text:
                parts.append(str(text))
    return "\n".join(parts).strip()


def _has_tool_use(content) -> bool:
    if not isinstance(content, list):
        return False
    return any(
        _get_value(block, "type") == "tool_use"
        for block in content
    )


def serialize_visible_messages(messages: list) -> list[dict]:
    """Return only user/assistant text messages that belong in the chat UI."""
    visible = []
    for message in messages:
        role = message.get("role")
        if role not in ("user", "assistant"):
            continue

        content = _extract_text(message.get("content", ""))
        if (
            not content
            or content.startswith(_INTERNAL_PREFIXES)
            or any(pattern.match(content) for pattern in _INTERNAL_PATTERNS)
        ):
            continue
        # A response with tool_use is an intermediate narration. The loop
        # continues after the tool result and stores the user-facing answer in
        # a later assistant message. Showing both makes one run look like
        # several concatenated conversations during history replay.
        if role == "assistant" and _has_tool_use(message.get("content")):
            continue

        visible.append({
            "role": role,
            "content": content,
        })
    return visible

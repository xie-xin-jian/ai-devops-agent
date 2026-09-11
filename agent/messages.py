"""Convert internal Agent messages into user-visible chat history."""


_INTERNAL_PREFIXES = ("[Compacted]", "<task_notification>", "<cron_job>")


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


def serialize_visible_messages(messages: list) -> list[dict]:
    """Return only user/assistant text messages that belong in the chat UI."""
    visible = []
    for message in messages:
        role = message.get("role")
        if role not in ("user", "assistant"):
            continue

        content = _extract_text(message.get("content", ""))
        if not content or content.startswith(_INTERNAL_PREFIXES):
            continue

        visible.append({
            "role": role,
            "content": content,
        })
    return visible

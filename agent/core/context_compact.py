import json
import re
import time
from datetime import datetime
from pathlib import Path

from agent.platform.config import (
    HISTORY_TOOL_LIMIT,
    PERSIST_THRESHOLD,
    TOOL_RESULTS_DIR,
    TRANSCRIPT_DIR,
)

# 压缩后重建历史用的固定标记。历史里只允许出现这一种"压缩消息"，
# 不允许 [snipped ...] / [N earlier messages dropped ...] 之类的占位符，
# 否则前端会把它们当成用户说的话渲染出来。
SUMMARY_PREFIX = (
    "以下内容是对此前对话的压缩摘要，不是用户原话。"
    "若摘要与用户原话冲突，以用户原话和本轮目标为准。\n\n"
)
GOAL_SECTION = "## 本轮目标"
COMPACT_USER_MESSAGE_BUDGET = 12000
_DROPPED_RE = re.compile(r"^\[\d+ earlier messages dropped")


def estimate_size(messages: list) -> int:
    return len(json.dumps(messages, default=str))


def block_type(block) -> str:
    if isinstance(block, dict):
        return block.get("type", "")
    return getattr(block, "type", "")


def field(block, key: str, default=None):
    """同时兼容 dict 与 anthropic SDK 的 pydantic block。"""
    if isinstance(block, dict):
        return block.get(key, default)
    return getattr(block, key, default)


def message_has_tool_use(message: dict) -> bool:
    if message.get("role") != "assistant":
        return False
    content = message.get("content", [])
    if isinstance(content, str):
        return False
    for block in content:
        if block_type(block) == "tool_use":
            return True
    return False


def is_tool_result_message(message: dict) -> bool:
    if message.get("role") != "user":
        return False
    content = message.get("content", [])
    if isinstance(content, str):
        return False
    for block in content:
        if block_type(block) == "tool_result":
            return True
    return False


def collect_tool_results(messages: list) -> list[tuple]:
    results = []
    for msg_idx, message in enumerate(messages):
        content = message.get("content", [])
        if isinstance(content, str):
            continue
        for block_idx, block in enumerate(content):
            if block_type(block) == "tool_result":
                results.append((msg_idx, block_idx, block))
    return results


def persist_large_output(tool_use_id: str, output: str) -> str:
    if len(output) < PERSIST_THRESHOLD:
        return output

    TOOL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    safe_id = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in tool_use_id)
    file_path = TOOL_RESULTS_DIR / f"{safe_id}_{int(time.time())}.txt"

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(output)

    preview = output[:500]
    return (
        f"[Large tool output persisted to {file_path}]\n"
        f"Size: {len(output)} bytes\n"
        f"Preview:\n{preview}..."
    )


def head_tail_truncate(text: str, limit: int) -> str:
    """保留首尾各一半，中间省略。开头含命令回显、结尾含报错，最有用。"""
    text = str(text)
    if len(text) <= limit:
        return text
    head = limit // 2
    tail = limit - head
    omitted = len(text) - limit
    return (
        text[:head]
        + f"\n... ({omitted} chars omitted) ...\n"
        + text[-tail:]
    )


def history_tool_content(
    tool_use_id: str,
    output: str,
    limit: int = HISTORY_TOOL_LIMIT,
) -> str:
    """限制单条工具输出进入消息历史的体积。

    超阈值的输出落盘保存（历史里只留预览和文件路径），因此 Agent 需要
    细节时仍可用 target_read_file 取回，而不是每轮都重发整个 payload。
    """
    text = str(output)
    if len(text) >= PERSIST_THRESHOLD:
        text = persist_large_output(tool_use_id, text)
    return head_tail_truncate(text, limit)


def tool_result_budget(messages: list, max_bytes: int = 60000) -> list:
    messages = [
        json.loads(json.dumps(m, default=str)) if not isinstance(m, dict) else m
        for m in messages
    ]

    tool_results = collect_tool_results(messages)
    total_size = 0
    result_sizes = []

    for msg_idx, block_idx, block in tool_results:
        content = block.get("content", "")
        if isinstance(content, list):
            size = sum(
                len(c.get("text", "") if isinstance(c, dict) else str(c))
                for c in content
            )
        else:
            size = len(str(content))
        result_sizes.append((msg_idx, block_idx, size, block))
        total_size += size

    if total_size <= max_bytes:
        return messages

    result_sizes.sort(key=lambda x: x[2], reverse=True)

    for msg_idx, block_idx, size, block in result_sizes:
        if total_size <= max_bytes:
            break

        content = block.get("content", "")
        if isinstance(content, list):
            output = "".join(
                c.get("text", "") if isinstance(c, dict) else str(c) for c in content
            )
        else:
            output = str(content)

        tool_use_id = block.get("tool_use_id", "unknown")
        persisted = persist_large_output(tool_use_id, output)

        if isinstance(block.get("content"), list):
            messages[msg_idx]["content"][block_idx]["content"] = [
                {"type": "text", "text": persisted}
            ]
        else:
            messages[msg_idx]["content"][block_idx]["content"] = persisted

        total_size = total_size - size + len(persisted)

    return messages


def _message_size(message) -> int:
    return len(json.dumps(message, default=str))


def trim_by_size(messages: list, max_bytes: int, keep_head: int = 1) -> list:
    """按字节预算硬裁剪：保留头部和最近的尾部，不插入任何占位符。

    这是压缩失败或压不下去时的降级手段。裁剪点会避开 tool_use 与
    tool_result 的配对边界，避免留下孤立的工具调用或工具结果。
    """
    sizes = [_message_size(message) for message in messages]
    total = sum(sizes)
    if total <= max_bytes or len(messages) <= keep_head + 1:
        return messages

    # 头部不能停在一条带 tool_use 的 assistant 消息上。
    head = min(keep_head, len(messages) - 1)
    while head < len(messages) and message_has_tool_use(messages[head - 1]):
        head += 1
        if head >= len(messages) - 1:
            break

    head_size = sum(sizes[:head])
    start = head
    suffix_size = total - head_size
    while start < len(messages) - 1 and head_size + suffix_size > max_bytes:
        suffix_size -= sizes[start]
        start += 1

    # 剩余的尾部不能以 tool_result 开头
    while start < len(messages) - 1 and (
        is_tool_result_message(messages[start])
        or (start > 0 and message_has_tool_use(messages[start - 1]))
    ):
        start += 1

    if start <= head:
        return messages
    if start >= len(messages):
        return messages[:head]
    return messages[:head] + messages[start:]


def message_text(message) -> str:
    """提取一条消息里的纯文本，忽略 tool_use / tool_result 块。"""
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if block_type(block) == "text":
            parts.append(field(block, "text", "") or "")
    return "\n".join(part for part in parts if part)


def is_internal_message(message) -> bool:
    """判断是否是压缩/裁剪产生的内部消息，不参与"真实用户原话"收集。"""
    text = message_text(message).strip()
    if not text:
        return True
    return (
        text.startswith("[snipped")
        or text.startswith("[Compacted]")
        or text.startswith(GOAL_SECTION)
        or text.startswith(SUMMARY_PREFIX.strip())
        or bool(_DROPPED_RE.match(text))
    )


def collect_real_user_messages(messages: list) -> list:
    """收集真实用户消息：排除工具结果消息、旧摘要和压缩占位符。

    旧摘要必须排除，否则多次压缩会出现"摘要套摘要"，越压越失真。
    """
    result = []
    for message in messages:
        if message.get("role") != "user":
            continue
        if is_tool_result_message(message) or is_internal_message(message):
            continue
        result.append(message)
    return result


def _select_user_messages(
    messages: list,
    budget: int = COMPACT_USER_MESSAGE_BUDGET,
    goal: str = "",
) -> list:
    """按预算从新到旧挑选用户原话，装不下就截断该条后停止。

    与按条数保留不同，这里保证"最近说了什么"一定在预算内，
    不会出现保留了 3 条但其中一条把预算吃光的情况。
    """
    selected = []
    remaining = budget
    goal_text = goal.strip()
    for message in reversed(collect_real_user_messages(messages)):
        if remaining <= 0:
            break
        text = message_text(message).strip()
        if not text:
            continue
        if goal_text and text == goal_text:
            # 本轮目标会单独钉在历史开头，这里不重复占预算。
            continue
        size = _message_size(message)
        if size <= remaining:
            selected.append(text)
            remaining -= size
            continue
        if remaining > 80:
            selected.append(text[: remaining - 60] + "\n...(truncated)")
        break
    selected.reverse()
    return selected


def checkpoint_compact(
    messages: list,
    client,
    model,
    *,
    goal: str = "",
    budget: int = COMPACT_USER_MESSAGE_BUDGET,
) -> list:
    """用一份交接摘要整体替换历史。

    重建顺序：本轮目标 → 最近用户原话（预算内）→ 摘要（末尾）。
    只产出一条消息，历史里不留任何占位符；压缩前后体积只通过事件暴露。
    """
    write_transcript(messages)
    summary = summarize_history(messages, client, model)
    retained = _select_user_messages(messages, budget=budget, goal=goal)

    sections = []
    if goal.strip():
        sections.append(f"{GOAL_SECTION}\n{goal.strip()}")
    if retained:
        sections.append(
            "## 最近用户原话\n" + "\n".join(f"USER: {text}" for text in retained)
        )
    body = "\n\n".join(sections)
    if body:
        body += "\n\n"
    body += "## 交接摘要\n" + summary.strip()
    return [{"role": "user", "content": SUMMARY_PREFIX + body}]


def fresh_window(
    messages: list,
    *,
    goal: str = "",
    reason: str = "summary_unavailable",
    budget: int = COMPACT_USER_MESSAGE_BUDGET,
) -> list:
    """摘要不可用时直接开启新窗口：只保留目标和最近用户原话。

    这是 L4 降级路径：不调用模型，因此不会因为摘要请求失败而继续带着
    超窗历史调用 API。
    """
    retained = _select_user_messages(messages, budget=budget, goal=goal)
    sections = []
    if goal.strip():
        sections.append(f"{GOAL_SECTION}\n{goal.strip()}")
    if retained:
        sections.append(
            "## 最近用户原话\n" + "\n".join(f"USER: {text}" for text in retained)
        )
    sections.append(
        f"## 交接说明\n摘要生成失败（{reason}），已开启新的上下文窗口，"
        "仅保留本轮目标与最近用户原话。"
    )
    return [{"role": "user", "content": SUMMARY_PREFIX + "\n\n".join(sections)}]


def write_transcript(messages: list) -> Path:
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    transcript_path = TRANSCRIPT_DIR / f"transcript_{timestamp}.jsonl"

    with open(transcript_path, "w", encoding="utf-8") as f:
        for message in messages:
            f.write(json.dumps(message, default=str, ensure_ascii=False) + "\n")

    return transcript_path


def summarize_history(messages: list, client, model) -> str:
    conversation_text = ""
    total_chars = 0

    for message in messages:
        role = message.get("role", "unknown")
        content = message.get("content", "")

        if isinstance(content, list):
            text_parts = []
            for block in content:
                if block_type(block) == "text":
                    if isinstance(block, dict):
                        text_parts.append(block.get("text", ""))
                    else:
                        text_parts.append(getattr(block, "text", ""))
                elif block_type(block) == "tool_use":
                    if isinstance(block, dict):
                        name = block.get("name", "")
                        text_parts.append(f"[Tool use: {name}]")
                    else:
                        text_parts.append(f"[Tool use: {getattr(block, 'name', '')}]")
                elif block_type(block) == "tool_result":
                    if isinstance(block, dict):
                        tool_content = block.get("content", "")
                        if isinstance(tool_content, str) and len(tool_content) > 200:
                            tool_content = tool_content[:200] + "..."
                        text_parts.append(f"[Tool result: {str(tool_content)[:200]}]")
                    else:
                        text_parts.append("[Tool result]")
            content_str = "\n".join(text_parts)
        else:
            content_str = str(content)

        line = f"{role.upper()}: {content_str}\n\n"
        if total_chars + len(line) > 80000:
            remaining = 80000 - total_chars
            if remaining > 0:
                conversation_text += line[:remaining]
            break
        conversation_text += line
        total_chars += len(line)

    prompt = (
        "You are performing a CONTEXT CHECKPOINT COMPACTION. "
        "Create a handoff summary for another LLM that will resume the task.\n"
        "Output EXACTLY these sections:\n"
        "Goal / Done / Decisions / Constraints / Files touched / "
        "Failed attempts (commands or paths already tried and failed - do not retry) / "
        "Remaining\n"
        "Be concise. Do not invent facts. Do not include tool output verbatim.\n\n"
        "Conversation history:\n"
        "---\n"
        f"{conversation_text}\n"
        "---\n\n"
        "Handoff summary:"
    )

    response = client.messages.create(
        model=model,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )

    summary_parts = []
    for block in response.content:
        if block_type(block) == "text":
            if isinstance(block, dict):
                summary_parts.append(block.get("text", ""))
            else:
                summary_parts.append(getattr(block, "text", ""))

    return "".join(summary_parts)

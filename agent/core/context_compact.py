import json
import time
from datetime import datetime
from pathlib import Path

from agent.platform.config import (
    HISTORY_TOOL_LIMIT,
    KEEP_RECENT_TOOL_RESULTS,
    PERSIST_THRESHOLD,
    TOOL_RESULTS_DIR,
    TRANSCRIPT_DIR,
)


def estimate_size(messages: list) -> int:
    return len(json.dumps(messages, default=str))


def block_type(block) -> str:
    if isinstance(block, dict):
        return block.get("type", "")
    return getattr(block, "type", "")


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


def snip_compact(messages: list, max_messages: int = 50) -> list:
    if len(messages) <= max_messages:
        return messages

    head_count = 3
    tail_count = max_messages - head_count - 1

    if tail_count < 1:
        tail_count = 1
        head_count = max_messages - tail_count - 1

    head = messages[:head_count]
    tail = messages[-tail_count:]

    snipped_start = head_count
    snipped_end = len(messages) - tail_count

    while snipped_start < len(messages) and message_has_tool_use(
        messages[snipped_start - 1]
    ):
        head.append(messages[snipped_start])
        snipped_start += 1
        if len(head) + len(tail) >= max_messages:
            break

    while snipped_end > snipped_start and is_tool_result_message(messages[snipped_end]):
        tail.insert(0, messages[snipped_end - 1])
        snipped_end -= 1
        if len(head) + len(tail) >= max_messages:
            break

    snipped_count = snipped_end - snipped_start

    snip_message = {
        "role": "user",
        "content": f"[snipped {snipped_count} messages]",
    }

    return head + [snip_message] + tail


def _message_size(message) -> int:
    return len(json.dumps(message, default=str))


def trim_by_size(messages: list, max_bytes: int, keep_head: int = 1) -> list:
    """按字节预算裁剪历史：保留首条用户消息和最近的尾部。

    与只按消息条数裁剪的 snip_compact 不同，这里直接控制字节量，避免
    "消息数没超但每条都很大" 导致每轮 API 调用都在重发几十万字节。
    """
    sizes = [_message_size(message) for message in messages]
    total = sum(sizes)
    if total <= max_bytes or len(messages) <= keep_head + 1:
        return messages

    head_size = sum(sizes[:keep_head])
    start = keep_head
    suffix_size = total - head_size
    while start < len(messages) - 1 and head_size + suffix_size > max_bytes:
        suffix_size -= sizes[start]
        start += 1

    if start <= keep_head:
        return messages

    dropped = start - keep_head
    marker = {
        "role": "user",
        "content": (
            f"[{dropped} earlier messages dropped to bound context size]"
        ),
    }
    return messages[:keep_head] + [marker] + messages[start:]


def micro_compact(messages: list) -> list:
    messages = [
        json.loads(json.dumps(m, default=str)) if not isinstance(m, dict) else m
        for m in messages
    ]

    tool_results = collect_tool_results(messages)

    if len(tool_results) <= KEEP_RECENT_TOOL_RESULTS:
        return messages

    to_compact = tool_results[:-KEEP_RECENT_TOOL_RESULTS]

    for msg_idx, block_idx, block in to_compact:
        if isinstance(messages[msg_idx]["content"][block_idx], dict):
            messages[msg_idx]["content"][block_idx][
                "content"
            ] = "[Earlier tool result compacted.]"
        else:
            messages[msg_idx]["content"][block_idx] = {
                "type": "tool_result",
                "tool_use_id": block.get("tool_use_id", ""),
                "content": "[Earlier tool result compacted.]",
            }

    return messages


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
        "Please summarize the following conversation history. Focus on:\n"
        "1. The user's goals and objectives\n"
        "2. Key findings and discoveries\n"
        "3. Files that were modified or created\n"
        "4. Remaining work or open issues\n\n"
        "Be concise but thorough. This summary will be used to continue the conversation.\n\n"
        "Conversation history:\n"
        "---\n"
        f"{conversation_text}\n"
        "---\n\n"
        "Summary:"
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


def compact_history(messages: list, client, model) -> list:
    write_transcript(messages)
    summary = summarize_history(messages, client, model)
    return [{"role": "user", "content": "[Compacted]\n\n" + summary}]


def reactive_compact(messages: list, client, model) -> list:
    if len(messages) <= 5:
        return messages

    keep_count = 5
    while keep_count < len(messages) and message_has_tool_use(
        messages[-keep_count - 1]
    ):
        keep_count += 1
    while keep_count < len(messages) and is_tool_result_message(
        messages[-keep_count - 1]
    ):
        keep_count += 1

    if keep_count >= len(messages):
        return messages

    history_to_summarize = messages[:-keep_count]
    tail = messages[-keep_count:]

    write_transcript(messages)
    summary = summarize_history(history_to_summarize, client, model)

    compacted_message = {"role": "user", "content": "[Compacted]\n\n" + summary}

    return [compacted_message] + tail

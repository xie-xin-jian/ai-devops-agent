import json
import os
import time
from datetime import datetime
from pathlib import Path

from agent.config import (
    CONTEXT_LIMIT,
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


def tool_result_budget(messages: list, max_bytes: int = 200000) -> list:
    messages = [json.loads(json.dumps(m, default=str)) if not isinstance(m, dict) else m for m in messages]

    tool_results = collect_tool_results(messages)
    total_size = 0
    result_sizes = []

    for msg_idx, block_idx, block in tool_results:
        content = block.get("content", "")
        if isinstance(content, list):
            size = sum(len(c.get("text", "") if isinstance(c, dict) else str(c)) for c in content)
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
            output = "".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
        else:
            output = str(content)

        tool_use_id = block.get("tool_use_id", "unknown")
        persisted = persist_large_output(tool_use_id, output)

        if isinstance(block.get("content"), list):
            messages[msg_idx]["content"][block_idx]["content"] = [{"type": "text", "text": persisted}]
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

    while snipped_start < len(messages) and message_has_tool_use(messages[snipped_start - 1]):
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


def micro_compact(messages: list) -> list:
    messages = [json.loads(json.dumps(m, default=str)) if not isinstance(m, dict) else m for m in messages]

    tool_results = collect_tool_results(messages)

    if len(tool_results) <= KEEP_RECENT_TOOL_RESULTS:
        return messages

    to_compact = tool_results[:-KEEP_RECENT_TOOL_RESULTS]

    for msg_idx, block_idx, block in to_compact:
        if isinstance(messages[msg_idx]["content"][block_idx], dict):
            messages[msg_idx]["content"][block_idx]["content"] = "[Earlier tool result compacted.]"
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
    while keep_count < len(messages) and message_has_tool_use(messages[-keep_count - 1]):
        keep_count += 1
    while keep_count < len(messages) and is_tool_result_message(messages[-keep_count - 1]):
        keep_count += 1

    if keep_count >= len(messages):
        return messages

    history_to_summarize = messages[:-keep_count]
    tail = messages[-keep_count:]

    write_transcript(messages)
    summary = summarize_history(history_to_summarize, client, model)

    compacted_message = {"role": "user", "content": "[Compacted]\n\n" + summary}

    return [compacted_message] + tail

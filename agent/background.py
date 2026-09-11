import threading
import time

_bg_counter = 0
background_tasks: dict[str, dict] = {}
background_results: dict[str, str] = {}
background_lock = threading.Lock()


def _truncate_output(output: str, head: int = 10, tail: int = 20) -> str:
    if not output:
        return ""
    output = output.replace("\r", "\n")
    lines = [l for l in output.split("\n") if l.strip()]
    if len(lines) <= head + tail:
        return "\n".join(lines)
    return "\n".join(
        lines[:head] + ["... (中间省略) ..."] + lines[-tail:]
    )


def is_slow_operation(tool_name: str, tool_input: dict) -> bool:
    if tool_name != "bash":
        return False
    command = tool_input.get("command", "").lower()
    slow_keywords = ["install", "build", "test", "deploy", "compile",
                     "docker build", "pip install", "npm install",
                     "cargo build", "pytest", "make",
                     "bits", "invoke-webrequest", "curl", "wget",
                     "download", "scp", "rsync"]
    return any(keyword in command for keyword in slow_keywords)


def should_run_background(tool_name: str, tool_input: dict) -> bool:
    if tool_name != "bash":
        return False
    return bool(tool_input.get("run_in_background")) or is_slow_operation(tool_name, tool_input)


def start_background_task(block, handlers: dict, trigger_post_hook) -> str:
    global _bg_counter
    _bg_counter += 1
    bg_id = f"bg_{_bg_counter:04d}"
    block_name = block.name if hasattr(block, 'name') else block.get('name', '')
    block_input = block.input if hasattr(block, 'input') else block.get('input', {})
    command = block_input.get("command", block_name)

    def worker():
        try:
            if block_name == "bash":
                from agent.tools.shell import run_bash_long
                result = run_bash_long(command, block_input.get("cwd"))
            else:
                handler = handlers.get(block_name)
                result = handler(**(block_input or {}))
        except Exception as e:
            result = f"Error: {e}"
        trigger_post_hook(block, result)
        with background_lock:
            background_tasks[bg_id]["status"] = "completed"
            background_results[bg_id] = str(result)

    with background_lock:
        background_tasks[bg_id] = {
            "tool_use_id": block.id if hasattr(block, 'id') else block.get('id', ''),
            "command": command,
            "status": "running",
        }
    threading.Thread(target=worker, daemon=True).start()
    return bg_id


def collect_background_results() -> list[str]:
    with background_lock:
        ready = [bg_id for bg_id, task in background_tasks.items()
                 if task["status"] == "completed" and not task.get("notified")]
    notifications = []
    for bg_id in ready:
        with background_lock:
            task = background_tasks[bg_id]
            task["notified"] = True
            output = background_results.get(bg_id, "")
        summary = _truncate_output(output, head=3, tail=10)
        notifications.append(
            f"<task_notification>\n"
            f"  <task_id>{bg_id}</task_id>\n"
            f"  <status>completed</status>\n"
            f"  <command>{task['command']}</command>\n"
            f"  <summary>{summary}</summary>\n"
            f"</task_notification>")
    return notifications


def list_background_tasks() -> str:
    """列出所有后台任务状态及完整输出（不消费，可重复查询）。"""
    with background_lock:
        items = list(background_tasks.items())
    if not items:
        return "No background tasks."
    lines = []
    for bg_id, task in items:
        status = task.get("status", "unknown")
        output = background_results.get(bg_id, "")
        output = _truncate_output(output, head=10, tail=20)
        cmd = task.get("command", "")[:120]
        lines.append(f"[{bg_id}] status={status}")
        lines.append(f"  command: {cmd}")
        if output:
            lines.append(f"  output:\n{output}")
        else:
            lines.append("  output: (none yet)")
        lines.append("")
    return "\n".join(lines)

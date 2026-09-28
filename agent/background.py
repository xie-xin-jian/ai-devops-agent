"""Persistent background runs executed through the shared sandbox model."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from agent.audit import record_event
from agent.config import BACKGROUND_DIR, WORKDIR
from agent.rbac import Principal, system_admin_principal
from agent.run_checkpoint import (
    PHASE_COMPLETED,
    PHASE_FAILED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    RunCheckpointStore,
)
from agent.run_context import create_run_context, initialize_checkpoint
from agent.sandbox import SandboxManager, SandboxTimeout, SandboxUnavailable
from agent.storage import atomic_write_json


BACKGROUND_DIR.mkdir(parents=True, exist_ok=True)

_bg_counter = 0
background_tasks: dict[str, dict] = {}
background_results: dict[str, str] = {}
background_lock = threading.Lock()


def _truncate_output(output: str, head: int = 10, tail: int = 20) -> str:
    if not output:
        return ""
    output = output.replace("\r", "\n")
    lines = [line for line in output.split("\n") if line.strip()]
    if len(lines) <= head + tail:
        return "\n".join(lines)
    return "\n".join(
        lines[:head] + ["... (中间省略) ..."] + lines[-tail:]
    )


def is_slow_operation(tool_name: str, tool_input: dict) -> bool:
    if tool_name != "bash":
        return False
    command = str(tool_input.get("command", "")).lower()
    slow_keywords = [
        "install",
        "build",
        "test",
        "deploy",
        "compile",
        "docker build",
        "pip install",
        "npm install",
        "cargo build",
        "pytest",
        "make",
        "curl",
        "wget",
        "download",
        "scp",
        "rsync",
    ]
    return any(keyword in command for keyword in slow_keywords)


def should_run_background(tool_name: str, tool_input: dict) -> bool:
    if tool_name != "bash":
        return False
    return bool(tool_input.get("run_in_background")) or is_slow_operation(
        tool_name,
        tool_input,
    )


def _background_path(bg_id: str) -> Path:
    return BACKGROUND_DIR / f"{bg_id}.json"


def _persist_task(bg_id: str) -> None:
    with background_lock:
        task = dict(background_tasks.get(bg_id) or {})
        output = background_results.get(bg_id, "")
    if not task:
        return
    payload = {
        **task,
        "background_id": bg_id,
        "output": output,
        "updated_at": time.time(),
    }
    atomic_write_json(_background_path(bg_id), payload)


def _load_persisted_tasks() -> dict[str, dict]:
    tasks = {}
    for path in sorted(
        BACKGROUND_DIR.glob("bg_*.json"),
        reverse=True,
    ):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        bg_id = str(data.get("background_id") or path.stem)
        tasks[bg_id] = data
    return tasks


def start_background_task(
    block,
    handlers: dict,
    trigger_post_hook,
    *,
    principal: Principal | None = None,
    session_id: str = "",
    parent_run_id: str = "",
) -> str:
    global _bg_counter
    _bg_counter += 1
    bg_id = f"bg_{int(time.time())}_{_bg_counter:04d}"
    block_name = (
        block.name if hasattr(block, "name")
        else block.get("name", "")
    )
    block_input = (
        block.input if hasattr(block, "input")
        else block.get("input", {})
    )
    command = str(block_input.get("command", block_name))
    principal = principal or system_admin_principal()
    context = create_run_context(
        source="background",
        session_id=session_id,
        owner_id=principal.id,
        principal=principal,
        parent_run_id=parent_run_id,
        resource_id=bg_id,
        metadata={
            "background_id": bg_id,
            "tool": block_name,
            "command": command,
        },
    )
    initialize_checkpoint(context, user_message=command)

    def worker():
        manager = None
        try:
            record_event(
                "background.run.started",
                f"Background run started: {bg_id}",
                result="success",
                severity="info",
                actor=context.owner_id,
                session_id=context.session_id,
                run_id=context.run_id,
                action_code="command.execute",
                correlation_id=context.run_id,
                payload={"command": command},
            )
            if block_name == "bash":
                manager = SandboxManager()
                manager.create(
                    context.run_id,
                    source_workspace=WORKDIR,
                    owner_id=context.owner_id,
                    source="background",
                )
                result = manager.run(
                    context.run_id,
                    command,
                    cwd=block_input.get("cwd"),
                )
            else:
                handler = handlers.get(block_name)
                if handler is None:
                    raise RuntimeError(
                        f"Unknown background tool: {block_name}"
                    )
                result = handler(**(block_input or {}))
            trigger_post_hook(block, result)
            _finish_background_run(
                context,
                bg_id,
                str(result),
                error="",
            )
        except Exception as exc:
            result = f"Error: {exc}"
            _finish_background_run(
                context,
                bg_id,
                result,
                error=str(exc),
            )
        finally:
            if manager is not None:
                manager.cleanup(context.run_id)
            _persist_task(bg_id)

    with background_lock:
        background_tasks[bg_id] = {
            "tool_use_id": (
                block.id if hasattr(block, "id")
                else block.get("id", "")
            ),
            "command": command,
            "status": "running",
            "run_id": context.run_id,
            "session_id": context.session_id,
            "owner_id": context.owner_id,
            "source": "background",
        }
    _persist_task(bg_id)
    threading.Thread(
        target=worker,
        daemon=True,
        name=f"background-{bg_id}",
    ).start()
    return bg_id


def _finish_background_run(
    context,
    bg_id: str,
    result: str,
    *,
    error: str,
) -> None:
    store = RunCheckpointStore()
    checkpoint = store.get(context.run_id)
    if checkpoint is not None:
        checkpoint.status = STATUS_FAILED if error else STATUS_COMPLETED
        checkpoint.phase = PHASE_FAILED if error else PHASE_COMPLETED
        checkpoint.last_error = error
        checkpoint.metadata = {
            **checkpoint.metadata,
            "output": str(result)[:10000],
            "background_id": bg_id,
        }
        store.save(checkpoint)
    record_event(
        "background.run.failed" if error else "background.run.completed",
        (
            f"Background run failed: {bg_id}"
            if error
            else f"Background run completed: {bg_id}"
        ),
        summary=str(result)[:500],
        result="failed" if error else "success",
        severity="high" if error else "info",
        actor=context.owner_id,
        session_id=context.session_id,
        run_id=context.run_id,
        action_code="command.execute",
        correlation_id=context.run_id,
        payload={"error": error, "output": str(result)[:2000]},
    )
    with background_lock:
        background_tasks[bg_id]["status"] = "completed"
        background_results[bg_id] = str(result)


def collect_background_results() -> list[str]:
    with background_lock:
        ready = [
            bg_id
            for bg_id, task in background_tasks.items()
            if task["status"] == "completed"
            and not task.get("notified")
        ]
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
            f"  <run_id>{task.get('run_id', '')}</run_id>\n"
            f"  <status>completed</status>\n"
            f"  <command>{task['command']}</command>\n"
            f"  <summary>{summary}</summary>\n"
            f"</task_notification>"
        )
    return notifications


def list_background_tasks(full: bool = False) -> str:
    with background_lock:
        items = dict(background_tasks)
    for bg_id, task in _load_persisted_tasks().items():
        items.setdefault(bg_id, task)
    if not items:
        return "No background tasks."
    lines = []
    for bg_id, task in items.items():
        status = task.get("status", "unknown")
        output = (
            background_results.get(bg_id)
            or task.get("output", "")
        )
        if not full:
            output = _truncate_output(output, head=10, tail=20)
        command = str(task.get("command", ""))[:120]
        lines.append(
            f"[{bg_id}] status={status} run_id="
            f"{task.get('run_id', '')}"
        )
        lines.append(f"  command: {command}")
        if output:
            lines.append(f"  output:\n{output}")
        else:
            lines.append("  output: (none yet)")
        lines.append("")
    return "\n".join(lines)


__all__ = [
    "background_lock",
    "background_results",
    "background_tasks",
    "collect_background_results",
    "is_slow_operation",
    "list_background_tasks",
    "should_run_background",
    "start_background_task",
]

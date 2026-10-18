"""Persistent background runs executed through the shared sandbox model."""

from __future__ import annotations

import threading
import time
import uuid

from agent.observability.audit import record_event
from agent.persistence.repositories import background as background_repo
from agent.platform.identity import Principal, system_admin_principal
from agent.tools.executor import ToolExecutor
from agent.tools.registry import ToolRegistry


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
    background_repo.upsert_background_task(payload, force=True)


def _load_persisted_tasks() -> dict[str, dict]:
    return {
        str(item.get("background_id") or ""): dict(item)
        for item in background_repo.fetch_background_tasks()
        if item.get("background_id")
    }


def load_persisted_background_tasks() -> dict[str, dict]:
    """Persisted background task records keyed by background id."""
    return _load_persisted_tasks()


def recover_interrupted_background_tasks(reason: str) -> list[dict]:
    """Mark tasks that were running when the process stopped as failed."""
    recovered = []
    for data in background_repo.fetch_background_tasks():
        if not isinstance(data, dict) or data.get("status") != "running":
            continue
        bg_id = str(data.get("background_id") or "")
        if not bg_id:
            continue
        now = time.time()
        background_repo.mark_background_interrupted(
            bg_id,
            reason=str(reason),
            at=now,
        )
        updated = background_repo.fetch_background_task(bg_id) or {
            **data,
            "status": "failed",
            "error": str(reason),
            "interruption_reason": str(reason),
            "updated_at": now,
        }
        recovered.append(updated)
        record_event(
            "background.run.interrupted",
            f"Background run interrupted: {bg_id}",
            summary=reason,
            result="failed",
            severity="high",
            actor=str(data.get("owner_id") or "system"),
            session_id=str(data.get("session_id") or ""),
            run_id=str(data.get("run_id") or ""),
            action_code="command.execute",
            correlation_id=str(data.get("run_id") or bg_id),
            payload={"background_id": bg_id, "reason": reason},
        )
    return recovered


def start_background_task(
    block,
    handlers: dict,
    trigger_post_hook,
    *,
    principal: Principal | None = None,
    session_id: str = "",
    parent_run_id: str = "",
    target_id: str = "",
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
    run_id = f"run_{uuid.uuid4().hex}"
    owner_id = principal.id

    def worker():
        try:
            record_event(
                "background.run.started",
                f"Background run started: {bg_id}",
                result="success",
                severity="info",
                actor=owner_id,
                session_id=session_id,
                run_id=run_id,
                action_code="command.execute",
                correlation_id=run_id,
                payload={
                    "background_id": bg_id,
                    "parent_run_id": parent_run_id,
                    "tool": block_name,
                    "command": command,
                },
            )
            if block_name == "bash":
                executor = ToolExecutor(
                    ToolRegistry.builtin(),
                    principal=principal,
                    target_id=target_id,
                )
                result = executor.execute(
                    "bash",
                    block_input,
                    run_id=run_id,
                    source="background",
                ).output
            else:
                handler = handlers.get(block_name)
                if handler is None:
                    raise RuntimeError(
                        f"Unknown background tool: {block_name}"
                    )
                result = handler(**(block_input or {}))
            trigger_post_hook(block, result)
            _finish_background_run(
                bg_id,
                str(result),
                error="",
                run_id=run_id,
                session_id=session_id,
                owner_id=owner_id,
            )
        except Exception as exc:
            result = f"Error: {exc}"
            _finish_background_run(
                bg_id,
                result,
                error=str(exc),
                run_id=run_id,
                session_id=session_id,
                owner_id=owner_id,
            )
        finally:
            _persist_task(bg_id)

    with background_lock:
        created_at = time.time()
        background_tasks[bg_id] = {
            "tool_use_id": (
                block.id if hasattr(block, "id")
                else block.get("id", "")
            ),
            "command": command,
            "status": "running",
            "run_id": run_id,
            "parent_run_id": parent_run_id,
            "session_id": session_id,
            "owner_id": owner_id,
            "source": "background",
            "created_at": created_at,
        }
    _persist_task(bg_id)
    threading.Thread(
        target=worker,
        daemon=True,
        name=f"background-{bg_id}",
    ).start()
    return bg_id


def _finish_background_run(
    bg_id: str,
    result: str,
    *,
    error: str,
    run_id: str,
    session_id: str,
    owner_id: str,
) -> None:
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
        actor=owner_id,
        session_id=session_id,
        run_id=run_id,
        action_code="command.execute",
        correlation_id=run_id,
        payload={
            "background_id": bg_id,
            "error": error,
            "output": str(result)[:2000],
        },
    )
    with background_lock:
        background_tasks[bg_id]["status"] = (
            "failed" if error else "completed"
        )
        if error:
            background_tasks[bg_id]["error"] = str(error)
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
        if task.get("error") or task.get("interruption_reason"):
            lines.append(
                "  error: "
                + str(
                    task.get("error")
                    or task.get("interruption_reason")
                )
            )
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
    "load_persisted_background_tasks",
    "list_background_tasks",
    "recover_interrupted_background_tasks",
    "should_run_background",
    "start_background_task",
]

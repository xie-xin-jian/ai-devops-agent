import json
import time
import random
import threading
from dataclasses import dataclass, asdict, field
from pathlib import Path
from agent.persistence import writer as persistence_writer
from agent.persistence.routing import pg_read, shadow_compare
from agent.persistence.repositories import tasks as task_repo
from agent.platform.config import TASKS_DIR
from agent.platform.storage import atomic_write_json

TASKS_DIR.mkdir(parents=True, exist_ok=True)
VALID_PRIORITIES = {"low", "medium", "high"}
_tasks_lock = threading.RLock()


def _console(message: str) -> None:
    """Print progress without letting console encoding break the write.

    The status lines contain non-ASCII markers; on a Windows console using a
    legacy code page, ``print`` raises UnicodeEncodeError, which would abort
    a task transition that has nothing to do with console output.
    """
    try:
        print(message)
    except (UnicodeEncodeError, OSError):
        pass


@dataclass
class Task:
    id: str
    subject: str
    description: str
    status: str
    owner: str | None
    blockedBy: list[str]
    run_id: str = ""
    source: str = "task"
    metadata: dict = field(default_factory=dict)
    priority: str = "medium"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    result: str = ""


def _task_path(task_id: str) -> Path:
    return TASKS_DIR / f"{task_id}.json"


def _task_from_dict(data: dict) -> Task:
    """兼容旧任务文件，缺失的新字段使用默认值。"""
    created_at = data.get("created_at") or time.time()
    priority = data.get("priority", "medium")
    if priority not in VALID_PRIORITIES:
        priority = "medium"
    return Task(
        id=data["id"],
        subject=data["subject"],
        description=data.get("description", ""),
        status=data.get("status", "pending"),
        owner=data.get("owner"),
        blockedBy=data.get("blockedBy") or [],
        run_id=data.get("run_id", ""),
        source=data.get("source", "task"),
        metadata=data.get("metadata") or {},
        priority=priority,
        created_at=created_at,
        updated_at=data.get("updated_at") or created_at,
        result=data.get("result", ""),
    )


def create_task(subject: str, description: str = "",
                blockedBy: list[str] | None = None,
                priority: str = "medium",
                *,
                source: str = "task",
                metadata: dict | None = None) -> Task:
    with _tasks_lock:
        if priority not in VALID_PRIORITIES:
            priority = "medium"
        now = time.time()
        task = Task(
            id=f"task_{int(time.time())}_{random.randint(0, 9999):04d}",
            subject=subject, description=description,
            status="pending", owner=None,
            blockedBy=blockedBy or [],
            source=source,
            metadata=dict(metadata or {}),
            priority=priority,
            created_at=now,
            updated_at=now,
        )
        save_task(task)
        return task


def save_task(task: Task):
    with _tasks_lock:
        task.updated_at = time.time()
        atomic_write_json(_task_path(task.id), asdict(task))
        persistence_writer.persist_task(asdict(task))


def delete_task(task_id: str) -> None:
    """Remove a task file and its mirror row."""
    path = _task_path(task_id)
    with _tasks_lock:
        if not path.exists():
            raise FileNotFoundError(task_id)
        path.unlink()
    persistence_writer.delete_task(task_id)


def load_task(task_id: str) -> Task:
    used_postgres, record = pg_read(
        "tasks",
        lambda: task_repo.fetch_task(task_id),
    )
    if used_postgres:
        task = _task_from_dict(record) if record is not None else None
        shadow_compare(
            "tasks",
            str(task_id or ""),
            postgres_value=task,
            json_reader=lambda: _local_load_task(task_id),
        )
        if task is None:
            raise FileNotFoundError(task_id)
        return task

    return _local_load_task(task_id)


def _local_load_task(task_id: str) -> Task:
    with _tasks_lock:
        data = json.loads(_task_path(task_id).read_text(encoding="utf-8"))
        return _task_from_dict(data)


def list_tasks() -> list[Task]:
    used_postgres, records = pg_read(
        "tasks",
        lambda: task_repo.fetch_tasks(),
    )
    if used_postgres:
        return [_task_from_dict(item) for item in records or []]

    with _tasks_lock:
        return [
            _task_from_dict(json.loads(p.read_text(encoding="utf-8")))
            for p in sorted(TASKS_DIR.glob("task_*.json"))
        ]


def _task_exists(task_id: str) -> bool:
    """Whether a task record exists on the active read path."""
    used_postgres, record = pg_read(
        "tasks",
        lambda: task_repo.fetch_task(task_id),
    )
    if used_postgres:
        exists = record is not None
        shadow_compare(
            "tasks",
            str(task_id or ""),
            postgres_value=(_task_from_dict(record) if exists else None),
            json_reader=lambda: _local_task_or_none(task_id),
        )
        return exists
    return _task_path(task_id).exists()


def _local_task_or_none(task_id: str) -> Task | None:
    try:
        return _local_load_task(task_id)
    except (FileNotFoundError, OSError, ValueError):
        return None


def get_task_json(task_id: str) -> str:
    return json.dumps(asdict(load_task(task_id)), indent=2)


def can_start(task_id: str) -> bool:
    task = load_task(task_id)
    for dep_id in task.blockedBy:
        if not _task_exists(dep_id):
            return False
        if load_task(dep_id).status != "completed":
            return False
    return True


def claim_task(
    task_id: str,
    owner: str = "agent",
    *,
    run_id: str = "",
) -> str:
    with _tasks_lock:
        task = load_task(task_id)
        if task.status != "pending":
            return f"Task {task_id} is {task.status}, cannot claim"
        if task.owner:
            return f"Task {task_id} already owned by {task.owner}"
        if not can_start(task_id):
            deps = [d for d in task.blockedBy
                    if _task_exists(d) and load_task(d).status != "completed"]
            missing = [d for d in task.blockedBy if not _task_exists(d)]
            parts = []
            if deps:
                parts.append(f"blocked by: {deps}")
            if missing:
                parts.append(f"missing deps: {missing}")
            return "Cannot start — " + ", ".join(parts)
        task.owner = owner
        task.status = "in_progress"
        if run_id:
            task.run_id = run_id
        save_task(task)
        _console(f"  \033[36m[claim] {task.subject} → in_progress\033[0m")
        return f"Claimed {task.id} ({task.subject})"


def complete_task(task_id: str, result: str = "") -> str:
    with _tasks_lock:
        task = load_task(task_id)
        if task.status != "in_progress":
            return f"Task {task_id} is {task.status}, cannot complete"
        task.status = "completed"
        task.result = result
        save_task(task)
        unblocked = [t.subject for t in list_tasks()
                     if t.status == "pending" and t.blockedBy and can_start(t.id)]
        _console(f"  \033[32m[complete] {task.subject} ✓\033[0m")
        msg = f"Completed {task.id} ({task.subject})"
        if unblocked:
            msg += f"\nUnblocked: {', '.join(unblocked)}"
        return msg

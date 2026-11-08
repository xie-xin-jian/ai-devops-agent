import json
import time
import uuid
import threading
from dataclasses import dataclass, asdict, field
from agent.persistence.repositories import tasks as task_repo

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


def _task_from_dict(data: dict) -> Task:
    """Normalize one repository record."""
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
                metadata: dict | None = None,
                session_id: str = "",
                owner_id: str = "",
                run_id: str = "") -> Task:
    with _tasks_lock:
        if priority not in VALID_PRIORITIES:
            priority = "medium"
        now = time.time()
        meta = dict(metadata or {})
        if session_id:
            meta["session_id"] = session_id
        if owner_id:
            meta["owner_id"] = owner_id
        task = Task(
            id=f"task_{int(time.time())}_{uuid.uuid4().hex[:8]}",
            subject=subject, description=description,
            status="pending", owner=None,
            blockedBy=blockedBy or [],
            run_id=run_id,
            source=source,
            metadata=meta,
            priority=priority,
            created_at=now,
            updated_at=now,
        )
        save_task(task)
        return task


def save_task(task: Task):
    with _tasks_lock:
        task.updated_at = time.time()
        if not task_repo.upsert_task(asdict(task), force=True):
            raise RuntimeError(f"Failed to save task {task.id}")


def delete_task(task_id: str) -> None:
    """Remove a task and its dependency edges."""
    with _tasks_lock:
        if not task_repo.delete_task(task_id):
            raise FileNotFoundError(task_id)


def load_task(task_id: str) -> Task:
    record = task_repo.fetch_task(task_id)
    if record is None:
        raise FileNotFoundError(task_id)
    return _task_from_dict(record)


def _task_session_id(task: Task) -> str:
    return str((task.metadata or {}).get("session_id") or "")


def list_tasks(
    *,
    session_id: str | None = None,
    statuses: tuple[str, ...] | None = None,
    limit: int | None = None,
) -> list[Task]:
    """List tasks, optionally scoped to a session.

    Tasks created by the agent carry ``metadata.session_id``; UI tasks have
    ``source == "ui"`` and no session, and stay visible from every session.
    Legacy tasks (``source == "task"`` without a session) are not exposed to
    the agent, which prevents old plans from leaking into new conversations.
    """
    tasks = [_task_from_dict(item) for item in task_repo.fetch_tasks()]
    if session_id is not None:
        tasks = [
            task for task in tasks
            if _task_session_id(task) == session_id
            or (task.source == "ui" and not _task_session_id(task))
        ]
    if statuses is not None:
        allowed = set(statuses)
        tasks = [task for task in tasks if task.status in allowed]
    if limit is not None:
        tasks = tasks[:limit]
    return tasks


def _task_exists(task_id: str) -> bool:
    """Whether a task record exists."""
    return task_repo.fetch_task(task_id) is not None


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
        if task.status == "completed":
            return f"Task {task.id} already completed"
        if task.status == "pending":
            if not can_start(task_id):
                return (f"Cannot complete {task.id} — "
                        "blocked by unfinished dependencies")
            task.owner = task.owner or "agent"
            task.status = "in_progress"
        elif task.status != "in_progress":
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


def release_run_tasks(run_id: str, reason: str = "") -> int:
    """Return tasks left in_progress by a finished run to the pending pool."""
    if not run_id:
        return 0
    with _tasks_lock:
        released = 0
        for task in list_tasks(statuses=("in_progress",)):
            if task.run_id != run_id:
                continue
            task.status = "pending"
            task.owner = None
            task.metadata = {
                **(task.metadata or {}),
                "last_run_id": run_id,
                "last_interruption": reason,
            }
            save_task(task)
            released += 1
        return released

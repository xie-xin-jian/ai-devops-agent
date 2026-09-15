import json
import time
import random
import threading
from dataclasses import dataclass, asdict, field
from pathlib import Path
from agent.config import TASKS_DIR
from agent.storage import atomic_write_json

TASKS_DIR.mkdir(parents=True, exist_ok=True)
VALID_PRIORITIES = {"low", "medium", "high"}
_tasks_lock = threading.RLock()


@dataclass
class Task:
    id: str
    subject: str
    description: str
    status: str
    owner: str | None
    blockedBy: list[str]
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
        priority=priority,
        created_at=created_at,
        updated_at=data.get("updated_at") or created_at,
        result=data.get("result", ""),
    )


def create_task(subject: str, description: str = "",
                blockedBy: list[str] | None = None,
                priority: str = "medium") -> Task:
    with _tasks_lock:
        if priority not in VALID_PRIORITIES:
            priority = "medium"
        now = time.time()
        task = Task(
            id=f"task_{int(time.time())}_{random.randint(0, 9999):04d}",
            subject=subject, description=description,
            status="pending", owner=None,
            blockedBy=blockedBy or [],
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


def load_task(task_id: str) -> Task:
    with _tasks_lock:
        data = json.loads(_task_path(task_id).read_text(encoding="utf-8"))
        return _task_from_dict(data)


def list_tasks() -> list[Task]:
    with _tasks_lock:
        return [
            _task_from_dict(json.loads(p.read_text(encoding="utf-8")))
            for p in sorted(TASKS_DIR.glob("task_*.json"))
        ]


def get_task_json(task_id: str) -> str:
    return json.dumps(asdict(load_task(task_id)), indent=2)


def can_start(task_id: str) -> bool:
    task = load_task(task_id)
    for dep_id in task.blockedBy:
        if not _task_path(dep_id).exists():
            return False
        if load_task(dep_id).status != "completed":
            return False
    return True


def claim_task(task_id: str, owner: str = "agent") -> str:
    with _tasks_lock:
        task = load_task(task_id)
        if task.status != "pending":
            return f"Task {task_id} is {task.status}, cannot claim"
        if task.owner:
            return f"Task {task_id} already owned by {task.owner}"
        if not can_start(task_id):
            deps = [d for d in task.blockedBy
                    if _task_path(d).exists() and load_task(d).status != "completed"]
            missing = [d for d in task.blockedBy if not _task_path(d).exists()]
            parts = []
            if deps: parts.append(f"blocked by: {deps}")
            if missing: parts.append(f"missing deps: {missing}")
            return "Cannot start — " + ", ".join(parts)
        task.owner = owner
        task.status = "in_progress"
        save_task(task)
        print(f"  \033[36m[claim] {task.subject} → in_progress\033[0m")
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
        print(f"  \033[32m[complete] {task.subject} ✓\033[0m")
        msg = f"Completed {task.id} ({task.subject})"
        if unblocked:
            msg += f"\nUnblocked: {', '.join(unblocked)}"
        return msg

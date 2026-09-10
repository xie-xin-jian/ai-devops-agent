import json
import time
import random
from dataclasses import dataclass, asdict
from agent.db import (
    task_create, task_save, task_load, task_list,
)


@dataclass
class Task:
    id: str
    subject: str
    description: str
    status: str
    owner: str | None
    blockedBy: list[str]


def _row_to_task(row) -> Task:
    """把 SQLite Row 转成 Task dataclass。"""
    return Task(
        id=row["id"],
        subject=row["subject"],
        description=row["description"] or "",
        status=row["status"],
        owner=row["owner"],
        blockedBy=json.loads(row["blocked_by"]),
    )


def create_task(subject: str, description: str = "",
                blockedBy: list[str] | None = None) -> Task:
    task = Task(
        id=f"task_{int(time.time())}_{random.randint(0, 9999):04d}",
        subject=subject, description=description,
        status="pending", owner=None,
        blockedBy=blockedBy or [],
    )
    task_create(task.id, task.subject, task.description,
                task.status, task.owner, json.dumps(task.blockedBy))
    return task


def save_task(task: Task):
    task_save(task.id, task.subject, task.description,
              task.status, task.owner, json.dumps(task.blockedBy))


def load_task(task_id: str) -> Task:
    row = task_load(task_id)
    if row is None:
        raise FileNotFoundError(f"Task {task_id} not found")
    return _row_to_task(row)


def list_tasks() -> list[Task]:
    return [_row_to_task(r) for r in task_list()]


def get_task_json(task_id: str) -> str:
    return json.dumps(asdict(load_task(task_id)), indent=2)


def can_start(task_id: str) -> bool:
    row = task_load(task_id)
    if row is None:
        return False
    blocked_by = json.loads(row["blocked_by"])
    for dep_id in blocked_by:
        dep = task_load(dep_id)
        if dep is None or dep["status"] != "completed":
            return False
    return True


def claim_task(task_id: str, owner: str = "agent") -> str:
    task = load_task(task_id)
    if task.status != "pending":
        return f"Task {task_id} is {task.status}, cannot claim"
    if task.owner:
        return f"Task {task_id} already owned by {task.owner}"
    if not can_start(task_id):
        blocked_by = json.loads(task_load(task_id)["blocked_by"])
        deps = [d for d in blocked_by
                if task_load(d) and task_load(d)["status"] != "completed"]
        missing = [d for d in blocked_by if task_load(d) is None]
        parts = []
        if deps: parts.append(f"blocked by: {deps}")
        if missing: parts.append(f"missing deps: {missing}")
        return "Cannot start — " + ", ".join(parts)
    task.owner = owner
    task.status = "in_progress"
    save_task(task)
    print(f"  \033[36m[claim] {task.subject} → in_progress\033[0m")
    return f"Claimed {task.id} ({task.subject})"


def complete_task(task_id: str) -> str:
    task = load_task(task_id)
    if task.status != "in_progress":
        return f"Task {task_id} is {task.status}, cannot complete"
    task.status = "completed"
    save_task(task)
    unblocked = [t.subject for t in list_tasks()
                 if t.status == "pending" and t.blockedBy and can_start(t.id)]
    print(f"  \033[32m[complete] {task.subject} ✓\033[0m")
    msg = f"Completed {task.id} ({task.subject})"
    if unblocked:
        msg += f"\nUnblocked: {', '.join(unblocked)}"
    return msg

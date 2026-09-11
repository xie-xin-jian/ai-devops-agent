from fastapi import APIRouter
from dataclasses import asdict

from agent.task_system import (
    Task, create_task, list_tasks, load_task, claim_task, complete_task,
    TASKS_DIR, VALID_PRIORITIES,
)

router = APIRouter()


def _task_dict(t: Task) -> dict:
    """把 Task 对象转换为 API 字典。"""
    d = asdict(t)
    d.setdefault("details", "")
    d.setdefault("assignee", t.owner)
    return d


@router.get("/")
async def list_all_tasks():
    tasks = list_tasks()
    return {"tasks": [_task_dict(t) for t in tasks]}


@router.post("/")
async def create_new_task(payload: dict):
    subject = payload.get("subject", "")
    description = payload.get("description", "")
    blockedBy = payload.get("blockedBy", None)
    priority = payload.get("priority", "medium")
    if not subject:
        return {"error": "subject is required"}
    if priority not in VALID_PRIORITIES:
        return {"error": "priority must be one of: low, medium, high"}
    task = create_task(subject, description, blockedBy, priority)
    return _task_dict(task)


@router.get("/{task_id}")
async def get_task(task_id: str):
    try:
        return _task_dict(load_task(task_id))
    except Exception as e:
        return {"error": str(e)}


@router.post("/{task_id}/claim")
async def claim(task_id: str, payload: dict = None):
    owner = (payload or {}).get("owner", "agent")
    result = claim_task(task_id, owner)
    try:
        return _task_dict(load_task(task_id))
    except Exception:
        return {"result": result}


@router.post("/{task_id}/complete")
async def complete(task_id: str, payload: dict = None):
    result_text = (payload or {}).get("result", "")
    msg = complete_task(task_id, result_text)
    try:
        return _task_dict(load_task(task_id))
    except Exception:
        return {"result": msg}


@router.delete("/{task_id}")
async def delete_task(task_id: str):
    """删除任务（直接删 JSON 文件）。"""
    path = TASKS_DIR / f"{task_id}.json"
    if not path.exists():
        return {"error": f"task {task_id} not found"}
    try:
        path.unlink()
        return {"success": True, "deleted": task_id}
    except Exception as e:
        return {"error": str(e)}

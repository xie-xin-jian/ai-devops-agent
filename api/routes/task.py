from fastapi import APIRouter
from dataclasses import asdict
from pathlib import Path
import json

from agent.task_system import (
    Task, create_task, list_tasks, load_task, claim_task, complete_task,
    save_task, TASKS_DIR,
)

router = APIRouter()


def _task_dict(t: Task) -> dict:
    """把 Task 对象转为字典，补全前端可能期望的字段（做兜底）。"""
    d = asdict(t)
    # 前端可能期望这些字段，后端 dataclass 没有，给默认值
    d.setdefault("priority", "medium")
    d.setdefault("details", "")
    d.setdefault("result", "")
    d.setdefault("created_at", 0)
    d.setdefault("updated_at", 0)
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
    if not subject:
        return {"error": "subject is required"}
    task = create_task(subject, description, blockedBy)
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
    # 可选记录完成结果（存到 details 字段，因为 dataclass 没有 result 字段）
    result_text = (payload or {}).get("result", "")
    if result_text:
        try:
            t = load_task(task_id)
            t.description = f"{t.description}\n[完成结果] {result_text}".strip()
            save_task(t)
        except Exception:
            pass
    msg = complete_task(task_id)
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

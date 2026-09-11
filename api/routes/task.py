from fastapi import APIRouter, HTTPException
from dataclasses import asdict

from api.schemas import TaskClaimRequest, TaskCompleteRequest, TaskCreateRequest
from agent.task_system import (
    Task, create_task, list_tasks, load_task, claim_task, complete_task,
    TASKS_DIR,
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
async def create_new_task(payload: TaskCreateRequest):
    task = create_task(
        payload.subject,
        payload.description,
        payload.blockedBy,
        payload.priority,
    )
    return _task_dict(task)


@router.get("/{task_id}")
async def get_task(task_id: str):
    try:
        return _task_dict(load_task(task_id))
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/{task_id}/claim")
async def claim(task_id: str, payload: TaskClaimRequest | None = None):
    owner = payload.owner if payload else "agent"
    try:
        result = claim_task(task_id, owner)
        if not result.startswith("Claimed"):
            raise HTTPException(status_code=409, detail=result)
        return _task_dict(load_task(task_id))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/{task_id}/complete")
async def complete(task_id: str, payload: TaskCompleteRequest | None = None):
    result_text = payload.result if payload else ""
    try:
        msg = complete_task(task_id, result_text)
        if not msg.startswith("Completed"):
            raise HTTPException(status_code=409, detail=msg)
        return _task_dict(load_task(task_id))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/{task_id}")
async def delete_task(task_id: str):
    """删除任务（直接删 JSON 文件）。"""
    path = TASKS_DIR / f"{task_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"task {task_id} not found")
    try:
        path.unlink()
        return {"success": True, "deleted": task_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

from fastapi import APIRouter, Depends, HTTPException
from dataclasses import asdict
import uuid

from agent.platform.identity import TASK_READ, TASK_WRITE, Principal
from api.auth import require_permissions
from api.schemas import TaskClaimRequest, TaskCompleteRequest, TaskCreateRequest
from agent.orchestration.tasks import (
    Task, create_task, list_tasks, load_task, claim_task, complete_task,
    delete_task as remove_task,
)
from agent.observability.audit import record_event

router = APIRouter()


def _task_dict(t: Task) -> dict:
    """把 Task 对象转换为 API 字典。"""
    d = asdict(t)
    d.setdefault("details", "")
    d.setdefault("assignee", t.owner)
    return d


@router.get("/")
async def list_all_tasks(
    _principal: Principal = Depends(require_permissions(TASK_READ)),
):
    tasks = list_tasks()
    return {"tasks": [_task_dict(t) for t in tasks]}


@router.post("/")
async def create_new_task(
    payload: TaskCreateRequest,
    _principal: Principal = Depends(require_permissions(TASK_WRITE)),
):
    task = create_task(
        payload.subject,
        payload.description,
        payload.blockedBy,
        payload.priority,
    )
    return _task_dict(task)


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    _principal: Principal = Depends(require_permissions(TASK_READ)),
):
    try:
        return _task_dict(load_task(task_id))
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/{task_id}/claim")
async def claim(
    task_id: str,
    payload: TaskClaimRequest | None = None,
    _principal: Principal = Depends(require_permissions(TASK_WRITE)),
):
    owner = payload.owner if payload else "agent"
    run_id = f"run_{uuid.uuid4().hex}"
    session_id = f"task:{task_id}"
    try:
        result = claim_task(
            task_id,
            owner,
            run_id=run_id,
        )
        if not result.startswith("Claimed"):
            raise HTTPException(status_code=409, detail=result)
        record_event(
            "task.claimed",
            f"Task claimed: {task_id}",
            result="success",
            severity="info",
            actor=_principal.id,
            session_id=session_id,
            run_id=run_id,
            action_code="task.manage",
            correlation_id=run_id,
            payload={"task_id": task_id, "owner": owner},
        )
        return _task_dict(load_task(task_id))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.post("/{task_id}/complete")
async def complete(
    task_id: str,
    payload: TaskCompleteRequest | None = None,
    _principal: Principal = Depends(require_permissions(TASK_WRITE)),
):
    result_text = payload.result if payload else ""
    try:
        task_before = load_task(task_id)
        run_id = task_before.run_id
        msg = complete_task(task_id, result_text)
        if not msg.startswith("Completed"):
            raise HTTPException(status_code=409, detail=msg)
        if run_id:
            record_event(
                "task.completed",
                f"Task completed: {task_id}",
                result="success",
                severity="info",
                actor=_principal.id,
                session_id=f"task:{task_id}",
                run_id=run_id,
                action_code="task.manage",
                correlation_id=run_id,
                payload={"task_id": task_id, "result": result_text},
            )
        return _task_dict(load_task(task_id))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    _principal: Principal = Depends(require_permissions(TASK_WRITE)),
):
    """删除任务及其依赖关系。"""
    try:
        remove_task(task_id)
        return {"success": True, "deleted": task_id}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"task {task_id} not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

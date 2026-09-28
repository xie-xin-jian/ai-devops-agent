from fastapi import APIRouter, Depends, HTTPException
from dataclasses import asdict

from agent.rbac import TASK_READ, TASK_WRITE, Principal
from api.auth import require_permissions
from api.schemas import TaskClaimRequest, TaskCompleteRequest, TaskCreateRequest
from agent.task_system import (
    Task, create_task, list_tasks, load_task, claim_task, complete_task,
    TASKS_DIR,
)
from agent.run_context import create_run_context, initialize_checkpoint
from agent.run_checkpoint import (
    PHASE_COMPLETED,
    PHASE_FAILED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    RunCheckpointStore,
)
from agent.audit import record_event

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
    run_context = create_run_context(
        source="task",
        session_id=f"task:{task_id}",
        owner_id=_principal.id,
        principal=_principal,
        resource_id=task_id,
        metadata={"task_id": task_id},
    )
    initialize_checkpoint(run_context)
    try:
        result = claim_task(
            task_id,
            owner,
            run_id=run_context.run_id,
        )
        if not result.startswith("Claimed"):
            checkpoint = RunCheckpointStore().get(run_context.run_id)
            if checkpoint is not None:
                checkpoint.status = STATUS_FAILED
                checkpoint.phase = PHASE_FAILED
                checkpoint.last_error = result
                RunCheckpointStore().save(checkpoint)
            raise HTTPException(status_code=409, detail=result)
        record_event(
            "task.claimed",
            f"Task claimed: {task_id}",
            result="success",
            severity="info",
            actor=_principal.id,
            session_id=run_context.session_id,
            run_id=run_context.run_id,
            action_code="task.manage",
            correlation_id=run_context.run_id,
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
            store = RunCheckpointStore()
            checkpoint = store.get(run_id)
            if checkpoint is not None:
                checkpoint.status = STATUS_COMPLETED
                checkpoint.phase = PHASE_COMPLETED
                checkpoint.metadata = {
                    **checkpoint.metadata,
                    "result": result_text,
                }
                store.save(checkpoint)
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
    """删除任务（直接删 JSON 文件）。"""
    path = TASKS_DIR / f"{task_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"task {task_id} not found")
    try:
        path.unlink()
        return {"success": True, "deleted": task_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

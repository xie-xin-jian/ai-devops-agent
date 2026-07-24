from fastapi import APIRouter
from agent.cron import (
    schedule_job, cancel_job, scheduled_jobs, validate_cron,
)

router = APIRouter()


@router.get("/")
async def list_cron_jobs():
    jobs = []
    for job in scheduled_jobs.values():
        jobs.append({
            "id": job.id,
            "cron": job.cron,
            "prompt": job.prompt,
            "recurring": job.recurring,
        })
    return jobs


@router.post("/")
async def create_cron_job(payload: dict):
    cron = payload.get("cron", "")
    prompt = payload.get("prompt", "")
    recurring = payload.get("recurring", True)
    if not cron or not prompt:
        return {"error": "cron and prompt are required"}
    if not validate_cron(cron):
        return {"error": "Invalid cron expression"}
    job, msg = schedule_job(cron, prompt, recurring)
    if job is not None:
        return {"id": job.id, "cron": job.cron}
    return {"error": msg}


@router.delete("/{job_id}")
async def delete_cron_job(job_id: str):
    result = cancel_job(job_id)
    return {"result": result}

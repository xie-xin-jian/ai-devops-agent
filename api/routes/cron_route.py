from fastapi import APIRouter
from agent.cron import (
    schedule_job, cancel_job, scheduled_jobs, validate_cron,
    list_cron_run_logs, _last_fired,
)

router = APIRouter()


@router.get("/")
async def list_cron_jobs():
    # 每个 job 把最近一次执行信息也带上，方便前端展示
    logs_by_job: dict[str, dict] = {}
    for log in list_cron_run_logs(limit=100):
        jid = log.get("job_id")
        if jid and jid not in logs_by_job:
            logs_by_job[jid] = log

    jobs = []
    for job in scheduled_jobs.values():
        last_log = logs_by_job.get(job.id, {})
        jobs.append({
            "id": job.id,
            "cron": job.cron,
            "prompt": job.prompt,
            "recurring": job.recurring,
            "last_run_at": _last_fired.get(job.id).isoformat(timespec="seconds") if _last_fired.get(job.id) else None,
            "last_success": last_log.get("success"),
            "last_finished_at": last_log.get("finished_at"),
        })
    return jobs


@router.get("/logs")
async def get_cron_logs(job_id: str = None, limit: int = 20):
    return list_cron_run_logs(job_id=job_id, limit=limit)


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

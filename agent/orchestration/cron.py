import time
import random
import threading
import queue
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Optional
from agent.persistence.repositories import cron as cron_repo


@dataclass
class CronJob:
    id: str
    cron: str
    prompt: str
    recurring: bool = True
    durable: bool = True
    name: str = ""
    description: str = ""
    enabled: bool = True
    created_at: float = field(default_factory=time.time)


scheduled_jobs: dict[str, CronJob] = {}
cron_lock = threading.RLock()
_last_fired: dict[str, datetime] = {}

# 后台执行用：防止同一个 job_id 在排队或运行期间被重复触发。
_pending_job_ids: set[str] = set()
_pending_lock = threading.Lock()

# Cron 任务统一进入单执行器，避免多个 Agent 实例并发访问共享工具和文件。
_cron_execution_queue: queue.Queue[tuple[CronJob, datetime]] = queue.Queue()
_cron_worker_thread: Optional[threading.Thread] = None
_cron_worker_lock = threading.Lock()

def _cron_field_matches(field: str, value: int) -> bool:
    if field == "*":
        return True

    for part in field.split(","):
        step = 1
        if "*/" in part:
            step = int(part.split("*/")[1])
            return value % step == 0
        if "/" in part:
            range_part, step_str = part.split("/")
            step = int(step_str)
            if "-" in range_part:
                start, end = map(int, range_part.split("-"))
                if start <= value <= end and (value - start) % step == 0:
                    return True
            else:
                start = int(range_part)
                if value >= start and (value - start) % step == 0:
                    return True
        elif "-" in part:
            start, end = map(int, part.split("-"))
            if start <= value <= end:
                return True
        else:
            if int(part) == value:
                return True

    return False


def cron_matches(cron_expr: str, dt: datetime) -> bool:
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return False

    minute, hour, day, month, weekday = parts

    if not _cron_field_matches(minute, dt.minute):
        return False
    if not _cron_field_matches(hour, dt.hour):
        return False
    if not _cron_field_matches(month, dt.month):
        return False

    day_matches = _cron_field_matches(day, dt.day)
    cron_weekday = (dt.weekday() + 1) % 7
    weekday_matches = _cron_field_matches(weekday, cron_weekday)
    if cron_weekday == 0:
        weekday_matches = weekday_matches or _cron_field_matches(weekday, 7)

    # Standard cron uses OR when both day-of-month and day-of-week are restricted.
    if day == "*" or weekday == "*":
        return day_matches and weekday_matches
    return day_matches or weekday_matches


def _validate_cron_field(field: str, min_val: int, max_val: int) -> bool:
    if field == "*":
        return True

    for part in field.split(","):
        try:
            if "*/" in part:
                step = int(part.split("*/")[1])
                if step < 1:
                    return False
            elif "/" in part:
                range_part, step_str = part.split("/")
                step = int(step_str)
                if step < 1:
                    return False
                if "-" in range_part:
                    start, end = map(int, range_part.split("-"))
                    if start < min_val or end > max_val or start > end:
                        return False
                else:
                    start = int(range_part)
                    if start < min_val or start > max_val:
                        return False
            elif "-" in part:
                start, end = map(int, part.split("-"))
                if start < min_val or end > max_val or start > end:
                    return False
            else:
                val = int(part)
                if val < min_val or val > max_val:
                    return False
        except ValueError:
            return False

    return True


def validate_cron(cron_expr: str) -> bool:
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return False

    minute, hour, day, month, weekday = parts

    if not _validate_cron_field(minute, 0, 59):
        return False
    if not _validate_cron_field(hour, 0, 23):
        return False
    if not _validate_cron_field(day, 1, 31):
        return False
    if not _validate_cron_field(month, 1, 12):
        return False
    if not _validate_cron_field(weekday, 0, 7):
        return False

    return True


def save_durable_jobs():
    try:
        with cron_lock:
            jobs = [
                asdict(job)
                for job in scheduled_jobs.values()
                if job.durable
            ]
        cron_repo.upsert_cron_jobs(jobs, force=True)
    except Exception:
        pass


def load_durable_jobs():
    try:
        records = cron_repo.fetch_cron_jobs()
        with cron_lock:
            for job_data in records:
                jid = str(job_data.get("id") or "")
                job = CronJob(
                    id=job_data.get("id", jid),
                    cron=job_data["cron"],
                    prompt=job_data["prompt"],
                    recurring=job_data.get("recurring", True),
                    durable=job_data.get("durable", True),
                    name=job_data.get("name", ""),
                    description=job_data.get("description", ""),
                    enabled=job_data.get("enabled", True),
                    created_at=job_data.get("created_at", time.time()),
                )
                scheduled_jobs[jid] = job
    except Exception:
        pass


def schedule_job(
    cron: str,
    prompt: str,
    recurring: bool = True,
    durable: bool = True,
    *,
    name: str = "",
    description: str = "",
    enabled: bool = True,
) -> tuple[Optional[CronJob], str]:
    if not validate_cron(cron):
        return None, "Invalid cron expression"

    job_id = f"cron_{int(time.time()*1000)}_{random.randint(1000,9999)}"
    job = CronJob(
        id=job_id,
        cron=cron,
        prompt=prompt,
        recurring=recurring,
        durable=durable,
        name=name,
        description=description,
        enabled=enabled,
    )

    with cron_lock:
        scheduled_jobs[job_id] = job

    if durable:
        save_durable_jobs()
    else:
        cron_repo.upsert_cron_job(asdict(job), force=True)

    return job, f"Job {job_id} scheduled"


def cancel_job(job_id: str) -> str:
    with cron_lock:
        if job_id in scheduled_jobs:
            del scheduled_jobs[job_id]
            _last_fired.pop(job_id, None)
        else:
            return f"Job {job_id} not found"

    save_durable_jobs()
    cron_repo.delete_cron_job(job_id)
    return f"Job {job_id} cancelled"


def _create_cron_agent(session_id: str = "cron:manual"):
    """为单次 Cron 执行创建独立 Agent，隔离对话上下文。"""
    from agent.core.comprehensive import ComprehensiveAgent
    from agent.mcp.client import load_all_custom_servers

    load_all_custom_servers()
    return ComprehensiveAgent(
        session_id=session_id,
    )


def _save_cron_run_log(
    job: CronJob,
    fired_at: datetime,
    output: str,
    error: Optional[str] = None,
    *,
    run_id: str = "",
    session_id: str = "",
):
    """把 Cron 执行结果落盘，方便用户之后查历史。"""
    try:
        ts = fired_at.strftime("%Y%m%d_%H%M%S")
        log = {
            "id": f"{job.id}__{ts}",
            "job_id": job.id,
            "cron": job.cron,
            "prompt": job.prompt,
            "fired_at": fired_at.isoformat(timespec="seconds"),
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "success": error is None,
            "output": output,
            "error": error,
            "run_id": run_id,
            "session_id": session_id,
        }
        cron_repo.upsert_cron_log(log)
    except Exception:
        pass


def _reserve_job(job_id: str) -> bool:
    """预留任务执行权。已有同任务排队或运行时返回 False。"""
    with _pending_lock:
        if job_id in _pending_job_ids:
            return False
        _pending_job_ids.add(job_id)
        return True


def _release_job(job_id: str):
    with _pending_lock:
        _pending_job_ids.discard(job_id)


def is_job_pending(job_id: str) -> bool:
    """Return whether a job is currently queued or running."""
    with _pending_lock:
        return job_id in _pending_job_ids


def _execute_cron_job_sync(job: CronJob, fired_at: datetime):
    """执行单个 Cron 任务，每次执行使用全新的 Agent 上下文。"""
    from agent.observability.audit import record_event

    run_id = f"run_{uuid.uuid4().hex}"
    session_id = f"cron:{job.id}"
    record_event(
        "cron.run.started",
        f"Cron run started: {job.id}",
        result="success",
        severity="info",
        actor="cron",
        session_id=session_id,
        run_id=run_id,
        action_code="automation.schedule",
        correlation_id=run_id,
        payload={
            "job_id": job.id,
            "cron": job.cron,
            "name": job.name,
            "scheduled_at": fired_at.isoformat(),
        },
    )
    try:
        agent = _create_cron_agent(session_id)
        output = agent.run(job.prompt)
        _save_cron_run_log(
            job,
            fired_at,
            output,
            run_id=run_id,
            session_id=session_id,
        )
        record_event(
            "cron.run.completed",
            f"Cron run completed: {job.id}",
            result="success",
            severity="info",
            actor="cron",
            session_id=session_id,
            run_id=run_id,
            action_code="automation.schedule",
            correlation_id=run_id,
            payload={"output": output[:1000]},
        )
    except Exception as e:
        _save_cron_run_log(
            job,
            fired_at,
            "",
            error=str(e),
            run_id=run_id,
            session_id=session_id,
        )
        record_event(
            "cron.run.failed",
            f"Cron run failed: {job.id}",
            summary=str(e),
            result="failed",
            severity="high",
            actor="cron",
            session_id=session_id,
            run_id=run_id,
            action_code="automation.schedule",
            correlation_id=run_id,
        )


def _cron_worker_loop():
    """串行消费 Cron 执行队列，保证任务之间不会并发污染上下文。"""
    while True:
        job, fired_at = _cron_execution_queue.get()
        try:
            _execute_cron_job_sync(job, fired_at)
        finally:
            _release_job(job.id)
            _cron_execution_queue.task_done()


def _ensure_cron_worker_started():
    """全局只启动一个 Cron 执行线程。"""
    global _cron_worker_thread
    if _cron_worker_thread is not None and _cron_worker_thread.is_alive():
        return
    with _cron_worker_lock:
        if _cron_worker_thread is not None and _cron_worker_thread.is_alive():
            return
        _cron_worker_thread = threading.Thread(
            target=_cron_worker_loop,
            daemon=True,
            name="cron-worker",
        )
        _cron_worker_thread.start()


def cron_scheduler_loop():
    _ensure_cron_worker_started()
    while True:
        now = datetime.now()
        now_truncated = now.replace(second=0, microsecond=0)
        schedule_changed = False

        with cron_lock:
            enabled_jobs = [
                (job_id, job)
                for job_id, job in scheduled_jobs.items()
                if job.enabled
            ]

        due_jobs = [
            (job_id, job)
            for job_id, job in enabled_jobs
            if cron_matches(job.cron, now_truncated)
        ]

        # Durable jobs are claimed in PostgreSQL so that restarts and extra
        # worker processes cannot fire the same job twice. Non-durable jobs
        # only exist in memory, so they keep the process-local gate.
        claimed = cron_repo.claim_due_cron_jobs(
            [job_id for job_id, job in due_jobs if job.durable],
            minute_epoch=now_truncated.timestamp(),
        )

        for job_id, job in due_jobs:
            if job.durable and claimed is not None:
                if job_id not in claimed:
                    continue
                _last_fired[job_id] = now_truncated
            else:
                last = _last_fired.get(job_id)
                if last is not None and last >= now_truncated:
                    continue
                _last_fired[job_id] = now_truncated

            if not job.recurring:
                with cron_lock:
                    scheduled_jobs.pop(job_id, None)
                _last_fired.pop(job_id, None)
                schedule_changed = True
                cron_repo.delete_cron_job(job_id)

            if _reserve_job(job_id):
                _cron_execution_queue.put((job, now_truncated))

        if schedule_changed:
            save_durable_jobs()

        time.sleep(1)


def list_cron_run_logs(job_id: Optional[str] = None, limit: int = 20) -> list[dict]:
    """查看 Cron 执行历史。不传 job_id 则查所有。"""
    return cron_repo.fetch_cron_logs(job_id=job_id, limit=limit)

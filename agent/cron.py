import time
import random
import threading
import json
from pathlib import Path
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from typing import Optional
from agent.config import DURABLE_CRON_PATH, WORKDIR


@dataclass
class CronJob:
    id: str
    cron: str
    prompt: str
    recurring: bool = True
    durable: bool = True


scheduled_jobs: dict[str, CronJob] = {}
cron_queue: list[CronJob] = []
cron_lock = threading.Lock()
_last_fired: dict[str, datetime] = {}

# 后台执行用：防止同一个 job_id 重入（前一次没跑完，下一分钟又触发）
_running_job_ids: set[str] = set()
_running_lock = threading.Lock()

# 后台 Agent 单例（懒加载，避免循环 import）
_bg_agent = None
_bg_agent_lock = threading.Lock()

CRON_LOG_DIR = WORKDIR / ".cron_logs"


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
    if not _cron_field_matches(day, dt.day):
        return False
    if not _cron_field_matches(month, dt.month):
        return False

    weekday_value = dt.weekday()
    if _cron_field_matches(weekday, weekday_value):
        return True

    return False


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
    if not _validate_cron_field(weekday, 0, 6):
        return False

    return True


def save_durable_jobs():
    durable = {jid: job for jid, job in scheduled_jobs.items() if job.durable}
    data = {jid: asdict(job) for jid, job in durable.items()}
    try:
        DURABLE_CRON_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(DURABLE_CRON_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def load_durable_jobs():
    try:
        if not DURABLE_CRON_PATH.exists():
            return
        with open(DURABLE_CRON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for jid, job_data in data.items():
            job = CronJob(**job_data)
            scheduled_jobs[jid] = job
    except Exception:
        pass


def schedule_job(cron: str, prompt: str, recurring: bool = True, durable: bool = True) -> tuple[Optional[CronJob], str]:
    if not validate_cron(cron):
        return None, "Invalid cron expression"

    job_id = f"cron_{int(time.time()*1000)}_{random.randint(1000,9999)}"
    job = CronJob(
        id=job_id,
        cron=cron,
        prompt=prompt,
        recurring=recurring,
        durable=durable,
    )

    with cron_lock:
        scheduled_jobs[job_id] = job

    if durable:
        save_durable_jobs()

    return job, f"Job {job_id} scheduled"


def cancel_job(job_id: str) -> str:
    with cron_lock:
        if job_id in scheduled_jobs:
            del scheduled_jobs[job_id]
            _last_fired.pop(job_id, None)
        else:
            return f"Job {job_id} not found"

    save_durable_jobs()
    return f"Job {job_id} cancelled"


def _get_bg_agent():
    """获取后台专用的 Agent 单例（懒加载，避免与用户 session 串话）。"""
    global _bg_agent
    if _bg_agent is not None:
        return _bg_agent
    with _bg_agent_lock:
        if _bg_agent is not None:
            return _bg_agent
        from agent.comprehensive import ComprehensiveAgent
        from agent.mcp import load_all_custom_servers
        load_all_custom_servers()
        _bg_agent = ComprehensiveAgent()
    return _bg_agent


def _save_cron_run_log(job: CronJob, fired_at: datetime, output: str, error: Optional[str] = None):
    """把 Cron 执行结果落盘，方便用户之后查历史。"""
    try:
        CRON_LOG_DIR.mkdir(parents=True, exist_ok=True)
        ts = fired_at.strftime("%Y%m%d_%H%M%S")
        log_path = CRON_LOG_DIR / f"{job.id}__{ts}.json"
        log = {
            "job_id": job.id,
            "cron": job.cron,
            "prompt": job.prompt,
            "fired_at": fired_at.isoformat(timespec="seconds"),
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "success": error is None,
            "output": output,
            "error": error,
        }
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _execute_cron_job_sync(job: CronJob, fired_at: datetime):
    """真正在后台线程执行 Cron 任务。阻塞函数，由外层 threading.Thread 调用。"""
    # 防重入
    with _running_lock:
        if job.id in _running_job_ids:
            return
        _running_job_ids.add(job.id)
    try:
        agent = _get_bg_agent()
        output = agent.run(job.prompt)
        _save_cron_run_log(job, fired_at, output)
    except Exception as e:
        _save_cron_run_log(job, fired_at, "", error=str(e))
    finally:
        with _running_lock:
            _running_job_ids.discard(job.id)


def cron_scheduler_loop():
    while True:
        now = datetime.now()
        now_truncated = now.replace(second=0, microsecond=0)

        with cron_lock:
            for job_id, job in list(scheduled_jobs.items()):
                if cron_matches(job.cron, now_truncated):
                    last = _last_fired.get(job_id)
                    if last is None or last < now_truncated:
                        # 兼容逻辑：也放进队列，用户下次发消息时会收到"有个 cron 执行了"的提示
                        cron_queue.append(job)
                        _last_fired[job_id] = now_truncated

                        if not job.recurring:
                            del scheduled_jobs[job_id]
                            _last_fired.pop(job_id, None)

                        # 真正的自动执行：起一个后台线程跑 Agent，不等用户发消息
                        t = threading.Thread(
                            target=_execute_cron_job_sync,
                            args=(job, now_truncated),
                            daemon=True,
                            name=f"cron-exec-{job.id}",
                        )
                        t.start()

            if any(job.durable for job in cron_queue) or not all(
                jid in scheduled_jobs for jid in list(_last_fired.keys())
            ):
                save_durable_jobs()

        time.sleep(1)


def consume_cron_queue() -> list[CronJob]:
    with cron_lock:
        jobs = list(cron_queue)
        cron_queue.clear()
        return jobs


def list_cron_run_logs(job_id: Optional[str] = None, limit: int = 20) -> list[dict]:
    """查看 Cron 执行历史。不传 job_id 则查所有。"""
    try:
        if not CRON_LOG_DIR.exists():
            return []
        files = sorted(CRON_LOG_DIR.glob("*.json"), reverse=True)
        result = []
        for p in files[:limit]:
            try:
                with open(p, "r", encoding="utf-8") as f:
                    log = json.load(f)
                if job_id and log.get("job_id") != job_id:
                    continue
                result.append(log)
            except Exception:
                pass
        return result
    except Exception:
        return []

"""Cron 调度与执行隔离测试。"""

import json
import queue
from datetime import datetime

import pytest

from agent import cron


@pytest.fixture(autouse=True)
def isolated_cron_state(tmp_path, monkeypatch):
    """隔离 Cron 全局状态、日志目录和执行队列。"""
    monkeypatch.setattr(cron, "CRON_LOG_DIR", tmp_path / ".cron_logs")
    monkeypatch.setattr(cron, "DURABLE_CRON_PATH", tmp_path / ".scheduled_tasks.json")
    monkeypatch.setattr(cron, "_cron_execution_queue", queue.Queue())
    monkeypatch.setattr(cron, "_cron_worker_thread", None)

    with cron.cron_lock:
        cron.scheduled_jobs.clear()
        cron._last_fired.clear()
    with cron._pending_lock:
        cron._pending_job_ids.clear()

    yield

    with cron.cron_lock:
        cron.scheduled_jobs.clear()
        cron._last_fired.clear()
    with cron._pending_lock:
        cron._pending_job_ids.clear()


def test_execute_uses_fresh_agent_for_each_run(monkeypatch):
    """同一任务重复执行时，不应复用上一个 Agent 的对话上下文。"""
    created_agents = []

    class FakeAgent:
        def __init__(self):
            self.messages = []
            self.prompts = []

        def run(self, prompt):
            self.prompts.append(prompt)
            self.messages.append({"role": "user", "content": prompt})
            return f"ok: {prompt}"

    def create_agent():
        agent = FakeAgent()
        created_agents.append(agent)
        return agent

    saved_logs = []
    monkeypatch.setattr(cron, "_create_cron_agent", create_agent)
    monkeypatch.setattr(
        cron,
        "_save_cron_run_log",
        lambda job, fired_at, output, error=None: saved_logs.append((output, error)),
    )

    job = cron.CronJob(id="cron_test", cron="* * * * *", prompt="check disk")
    fired_at = datetime(2026, 9, 11, 10, 0)

    cron._execute_cron_job_sync(job, fired_at)
    cron._execute_cron_job_sync(job, fired_at)

    assert len(created_agents) == 2
    assert created_agents[0] is not created_agents[1]
    assert created_agents[0].messages == [{"role": "user", "content": "check disk"}]
    assert created_agents[1].messages == [{"role": "user", "content": "check disk"}]
    assert saved_logs == [("ok: check disk", None), ("ok: check disk", None)]


def test_scheduler_enqueues_job_without_running_inline(monkeypatch):
    """调度器只负责入队，实际执行交给唯一的 Cron worker。"""
    monkeypatch.setattr(cron, "_ensure_cron_worker_started", lambda: None)
    monkeypatch.setattr(cron, "cron_matches", lambda cron_expr, dt: True)
    monkeypatch.setattr(
        cron,
        "_execute_cron_job_sync",
        lambda job, fired_at: pytest.fail("scheduler must not execute jobs inline"),
    )

    def stop_loop(_seconds):
        raise StopIteration

    monkeypatch.setattr(cron.time, "sleep", stop_loop)

    job = cron.CronJob(
        id="cron_test",
        cron="* * * * *",
        prompt="check disk",
        recurring=True,
    )
    with cron.cron_lock:
        cron.scheduled_jobs[job.id] = job

    with pytest.raises(StopIteration):
        cron.cron_scheduler_loop()

    queued_job, queued_at = cron._cron_execution_queue.get_nowait()
    assert queued_job.id == job.id
    assert queued_at.minute == datetime.now().minute
    assert cron._cron_execution_queue.qsize() == 0


def test_one_shot_job_is_removed_and_persisted_once(monkeypatch):
    """一次性任务触发后应移出调度表，并立即持久化变更。"""
    monkeypatch.setattr(cron, "_ensure_cron_worker_started", lambda: None)
    monkeypatch.setattr(cron, "cron_matches", lambda cron_expr, dt: True)

    save_calls = []
    monkeypatch.setattr(cron, "save_durable_jobs", lambda: save_calls.append(True))

    def stop_loop(_seconds):
        raise StopIteration

    monkeypatch.setattr(cron.time, "sleep", stop_loop)

    job = cron.CronJob(
        id="cron_once",
        cron="* * * * *",
        prompt="run once",
        recurring=False,
    )
    with cron.cron_lock:
        cron.scheduled_jobs[job.id] = job

    with pytest.raises(StopIteration):
        cron.cron_scheduler_loop()

    assert job.id not in cron.scheduled_jobs
    assert save_calls == [True]
    queued_job, _ = cron._cron_execution_queue.get_nowait()
    assert queued_job.id == job.id


def test_scheduler_skips_job_that_is_already_pending(monkeypatch):
    """长任务尚未完成时，同任务的后续触发不应继续堆积到队列。"""
    monkeypatch.setattr(cron, "_ensure_cron_worker_started", lambda: None)
    monkeypatch.setattr(cron, "cron_matches", lambda cron_expr, dt: True)

    def stop_loop(_seconds):
        raise StopIteration

    monkeypatch.setattr(cron.time, "sleep", stop_loop)

    job = cron.CronJob(
        id="cron_long",
        cron="* * * * *",
        prompt="long task",
        recurring=True,
    )
    with cron.cron_lock:
        cron.scheduled_jobs[job.id] = job
    assert cron._reserve_job(job.id) is True

    with pytest.raises(StopIteration):
        cron.cron_scheduler_loop()

    assert cron._cron_execution_queue.qsize() == 0


def test_cron_job_persists_metadata():
    """创建 Cron 任务时应保存前端填写的名称和描述。"""
    job, message = cron.schedule_job(
        "0 9 * * *",
        "daily inspection",
        name="Daily inspection",
        description="Check disk and services",
    )

    assert job is not None
    assert "scheduled" in message
    assert job.name == "Daily inspection"
    assert job.description == "Check disk and services"
    assert job.enabled is True
    assert job.created_at > 0

    data = json.loads(cron.DURABLE_CRON_PATH.read_text(encoding="utf-8"))
    assert data[job.id]["name"] == "Daily inspection"
    assert data[job.id]["description"] == "Check disk and services"


def test_legacy_cron_job_defaults():
    """缺少新字段的旧 Cron 数据应使用默认值加载。"""
    cron.DURABLE_CRON_PATH.write_text(
        json.dumps({
            "cron_legacy": {
                "id": "cron_legacy",
                "cron": "0 9 * * *",
                "prompt": "legacy task",
                "recurring": True,
                "durable": True,
            }
        }),
        encoding="utf-8",
    )

    cron.load_durable_jobs()
    job = cron.scheduled_jobs["cron_legacy"]
    assert job.name == ""
    assert job.description == ""
    assert job.enabled is True
    assert job.created_at > 0


@pytest.mark.asyncio
async def test_cron_api_preserves_metadata():
    """Cron API 应返回并保存前端填写的完整字段。"""
    pytest.importorskip("fastapi")
    from api.routes.cron_route import create_cron_job, list_cron_jobs

    response = await create_cron_job({
        "name": "Disk inspection",
        "description": "Runs every morning",
        "cron": "0 9 * * *",
        "prompt": "check disk",
        "enabled": True,
    })

    assert response["name"] == "Disk inspection"
    assert response["description"] == "Runs every morning"
    assert response["enabled"] is True
    assert response["created_at"] > 0

    jobs = await list_cron_jobs()
    saved = next(job for job in jobs if job["id"] == response["id"])
    assert saved["name"] == "Disk inspection"
    assert saved["description"] == "Runs every morning"
    assert saved["enabled"] is True


def test_scheduler_skips_disabled_job(monkeypatch):
    """禁用任务不应进入执行队列。"""
    monkeypatch.setattr(cron, "_ensure_cron_worker_started", lambda: None)
    monkeypatch.setattr(cron, "cron_matches", lambda cron_expr, dt: True)

    def stop_loop(_seconds):
        raise StopIteration

    monkeypatch.setattr(cron.time, "sleep", stop_loop)

    job = cron.CronJob(
        id="cron_disabled",
        cron="* * * * *",
        prompt="disabled task",
        enabled=False,
    )
    with cron.cron_lock:
        cron.scheduled_jobs[job.id] = job

    with pytest.raises(StopIteration):
        cron.cron_scheduler_loop()

    assert cron._cron_execution_queue.qsize() == 0


def test_cron_weekday_uses_standard_sunday_zero_mapping():
    """Cron 1 应匹配周一，0 和 7 都应匹配周日。"""
    monday = datetime(2026, 9, 14, 9, 0)
    tuesday = datetime(2026, 9, 15, 9, 0)
    sunday = datetime(2026, 9, 13, 9, 0)

    assert cron.cron_matches("0 9 * * 1", monday) is True
    assert cron.cron_matches("0 9 * * 1", tuesday) is False
    assert cron.cron_matches("0 9 * * 0", sunday) is True
    assert cron.cron_matches("0 9 * * 7", sunday) is True
    assert cron.validate_cron("0 9 * * 7") is True


def test_cron_day_and_weekday_use_or_when_both_restricted():
    """日期和星期同时受限时应满足任意一个即可。"""
    monday_the_14th = datetime(2026, 9, 14, 9, 0)
    tuesday_the_15th = datetime(2026, 9, 15, 9, 0)
    wednesday_the_16th = datetime(2026, 9, 16, 9, 0)

    assert cron.cron_matches("0 9 15 * 1", monday_the_14th) is True
    assert cron.cron_matches("0 9 15 * 1", tuesday_the_15th) is True
    assert cron.cron_matches("0 9 15 * 1", wednesday_the_16th) is False

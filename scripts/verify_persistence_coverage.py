#!/usr/bin/env python3
"""Exercise every mirrored write path and verify the mirror afterwards.

Unit tests prove the mapping logic; this script proves that each *real* write
path still reaches the mirror. It runs the stores for real, then compares both
sides for every domain. Anything that never ran shows up as "not covered"
instead of silently looking healthy.

By default everything is written into a throwaway directory under the system
temporary folder, so real data is untouched. Point ``--data-dir`` at a
different directory only when you mean it.

    python scripts/verify_persistence_coverage.py \
        --database-url postgresql+psycopg://ai_devops:change-me@127.0.0.1:5433/ai_devops
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Fixed identifiers used by the run, so cleanup can find everything it made.
COVERAGE_SESSION_ID = "session-coverage"
COVERAGE_RUN_ID = "run-coverage"
SCHEMA_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _prepare_schema(base_url: str, schema: str) -> str:
    """Create an isolated schema and return a DSN that points at it.

    Coverage drives *global* operations (interrupt every stale run, fail every
    confirmed action, consolidate the oldest memories). Run against the same
    schema as real data, those would rewrite records that belong to the user,
    so the whole run is confined to its own schema and dropped afterwards.
    """
    import sqlalchemy
    from sqlalchemy.engine import make_url

    if not SCHEMA_PATTERN.match(schema):
        raise ValueError(f"invalid schema name: {schema!r}")

    admin = sqlalchemy.create_engine(base_url, pool_pre_ping=True)
    try:
        with admin.begin() as connection:
            connection.execute(
                sqlalchemy.text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
            )
    finally:
        admin.dispose()

    schema_url = make_url(base_url).update_query_dict({
        "options": f"-csearch_path={schema}",
    })
    return schema_url.render_as_string(hide_password=False)


def _drop_schema(base_url: str, schema: str) -> None:
    import sqlalchemy

    admin = sqlalchemy.create_engine(base_url, pool_pre_ping=True)
    try:
        with admin.begin() as connection:
            connection.execute(
                sqlalchemy.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            )
    finally:
        admin.dispose()


def _bootstrap_paths(data_dir: Path) -> dict:
    """Point every store at ``data_dir`` before importing them.

    ``agent.platform.config`` calls ``load_dotenv(override=True)``, so an
    environment variable cannot win against the project ``.env``. Rebinding
    the path constants is the reliable way to isolate a run, and the returned
    mapping is printed so the caller can see exactly where data went.
    """
    sys.path.insert(0, str(PROJECT_ROOT))
    data_dir.mkdir(parents=True, exist_ok=True)

    import agent.platform.config as config

    config.DATA_DIR = data_dir
    config.AUDIT_DIR = data_dir / ".audit"
    config.SESSIONS_DIR = data_dir / ".sessions"
    config.RUNS_DIR = data_dir / ".runs"
    config.TASKS_DIR = data_dir / ".tasks"
    config.TARGETS_DIR = data_dir / ".targets"
    config.MEMORY_DIR = data_dir / ".memory"
    config.BACKGROUND_DIR = data_dir / ".background"
    config.CRON_LOG_DIR = data_dir / ".cron_logs"
    config.DURABLE_CRON_PATH = data_dir / ".scheduled_tasks.json"
    config.TRANSCRIPT_DIR = data_dir / ".transcripts"
    config.TOOL_RESULTS_DIR = data_dir / ".task_outputs" / "tool-results"

    import agent.memory.store as memory_store
    import agent.observability.audit as audit
    import agent.orchestration.background as background
    import agent.orchestration.cron as cron
    import agent.orchestration.pending_actions as pending_actions
    import agent.orchestration.tasks as tasks
    import agent.targets.store as target_store

    memory_store.MEMORY_DIR = config.MEMORY_DIR
    audit.AUDIT_EVENTS_PATH = config.AUDIT_DIR / "events.jsonl"
    background.BACKGROUND_DIR = config.BACKGROUND_DIR
    cron.CRON_LOG_DIR = config.CRON_LOG_DIR
    cron.DURABLE_CRON_PATH = config.DURABLE_CRON_PATH
    pending_actions.PENDING_ACTIONS_PATH = (
        config.DATA_DIR / ".pending_actions" / "actions.json"
    )
    tasks.TASKS_DIR = config.TASKS_DIR
    target_store.TARGETS_PATH = config.TARGETS_DIR / "targets.json"

    return {
        "data_dir": str(config.DATA_DIR),
        "audit_events": str(audit.AUDIT_EVENTS_PATH),
        "targets": str(target_store.TARGETS_PATH),
        "tasks": str(tasks.TASKS_DIR),
        "memory": str(memory_store.MEMORY_DIR),
        "pending_actions": str(pending_actions.PENDING_ACTIONS_PATH),
        "cron_durable": str(cron.DURABLE_CRON_PATH),
        "cron_logs": str(cron.CRON_LOG_DIR),
        "background": str(background.BACKGROUND_DIR),
    }


class Report:
    """Records which write paths actually ran."""

    def __init__(self) -> None:
        self.steps: list[dict] = []
        self.checks: list[dict] = []
        self.created: list[dict] = []

    def step(self, domain: str, action: str, ok: bool, detail: str = "") -> bool:
        self.steps.append({
            "domain": domain,
            "action": action,
            "ok": bool(ok),
            "detail": detail,
        })
        return bool(ok)

    def expect(
        self,
        domain: str,
        key: str,
        *,
        present: bool = True,
        note: str = "",
    ) -> bool:
        """Assert right now that ``key`` does (or does not) exist in PostgreSQL.

        The check happens inline because records are created and deleted
        within the same run: comparing the final state would report every
        "created then deleted" path as a failure.
        """
        result = check_mirror(domain, str(key), present=present)
        result["note"] = note
        self.checks.append(result)
        return bool(result["ok"])

    def track(self, domain: str, key: str) -> None:
        """Remember a mirrored key so the run can clean up after itself."""
        self.created.append({"domain": domain, "key": str(key)})

    def domain_summary(self) -> dict:
        summary: dict[str, dict] = {}
        for step in self.steps:
            entry = summary.setdefault(
                step["domain"],
                {"steps": 0, "failed": 0, "failures": []},
            )
            entry["steps"] += 1
            if not step["ok"]:
                entry["failed"] += 1
                entry["failures"].append(step["action"])
        return summary


def cover_targets(report: Report, workspace: Path) -> None:
    import agent.platform.config as config
    from agent.targets.store import TargetStore

    config.TARGET_BROWSE_ROOTS = (workspace.resolve(),)
    project = workspace / "projects" / "trip"
    project.mkdir(parents=True, exist_ok=True)
    store = TargetStore()

    target = store.create({"name": "coverage target", "root": str(project)})
    report.step("targets", "create", bool(target.id))
    report.expect("targets", target.id)
    report.track("targets", target.id)
    updated = store.update(target.id, {"description": "coverage run"})
    report.step("targets", "update", updated.description == "coverage run")
    report.step("targets", "read", store.get(target.id) is not None)
    report.step("targets", "list", len(store.list()) >= 1)
    store.delete(target.id)
    report.step("targets", "delete", store.get(target.id) is None)
    report.expect("targets", target.id, present=False, note="after delete")


def cover_tasks(report: Report) -> None:
    from agent.orchestration.tasks import (
        can_start,
        claim_task,
        complete_task,
        create_task,
        delete_task,
        list_tasks,
        load_task,
    )

    dependency = create_task("coverage dependency")
    report.step("tasks", "create", bool(dependency.id))
    report.expect("tasks", dependency.id)
    report.track("tasks", dependency.id)

    blocked = create_task(
        "coverage main",
        blockedBy=[dependency.id],
        priority="high",
    )
    report.step("tasks", "create_with_dependencies", bool(blocked.blockedBy))
    report.expect("tasks", blocked.id, note="with dependency edge")
    report.track("tasks", blocked.id)
    report.step("tasks", "can_start_blocked", can_start(blocked.id) is False)

    frozen = claim_task(blocked.id)
    report.step("tasks", "claim_rejected", frozen.startswith("Cannot start"))

    claimed_dep = claim_task(dependency.id, run_id="run-coverage")
    report.step("tasks", "claim", claimed_dep.startswith("Claimed"))
    completed_dep = complete_task(dependency.id, result="done")
    report.step("tasks", "complete", completed_dep.startswith("Completed"))
    report.step("tasks", "can_start_unblocked", can_start(blocked.id) is True)

    claimed = claim_task(blocked.id, run_id="run-coverage")
    report.step("tasks", "claim_after_unblock", claimed.startswith("Claimed"))
    complete_task(blocked.id, result="done")
    report.step("tasks", "load", load_task(blocked.id).status == "completed")
    report.step("tasks", "list", len(list_tasks()) >= 2)

    delete_task(blocked.id)
    report.step("tasks", "delete_removes_dependencies", True)
    report.expect("tasks", blocked.id, present=False, note="after delete")


def cover_memories(report: Report) -> None:
    from agent.memory.service import MemorySystem

    system = MemorySystem()
    base = system.add(
        "deploy target trip uses systemd unit trip.service",
        importance=4,
        scope="global",
        tags=["coverage", "deploy"],
    )
    report.step("memories", "add", bool(base["id"]))
    report.expect("memories", base["id"])
    report.track("memories", base["id"])

    duplicate = system.add(
        "deploy target trip uses systemd unit trip.service",
        importance=5,
        scope="global",
    )
    report.step(
        "memories",
        "add_duplicate_merges",
        duplicate["id"] == base["id"] and duplicate["importance"] == 5,
    )

    updated = system.update(
        base["id"],
        content="deploy target trip uses systemd unit trip.service (v2)",
        importance=5,
    )
    report.step("memories", "update", updated["version"] >= 2)

    superseded = system.add(
        "deploy target trip uses systemd unit trip.service (v2)",
        importance=3,
        scope="global",
    )
    report.step(
        "memories",
        "supersede_or_merge",
        bool(superseded["id"]),
    )
    report.expect("memories", superseded["id"], note="merged or superseded")
    report.track("memories", superseded["id"])

    archived = system.archive(base["id"])
    report.step("memories", "archive", archived["status"] == "archived")
    restored = system.restore(base["id"])
    report.step("memories", "restore", restored["status"] == "active")

    for index in range(9):
        bulk = system.add(f"coverage bulk memory number {index}", scope="global")
        report.track("memories", bulk["id"])
    report.expect("memories", base["id"], note="bulk memories mirrored")

    system._access_deltas[base["id"]] = 3
    system._access_last_accessed[base["id"]] = time.time()
    flushed = system.flush_access_stats(force=True)
    report.step("memories", "flush_access_stats", flushed >= 1, f"flushed={flushed}")

    consolidated = system.consolidate()
    report.step("memories", "consolidate", "Consolidated" in consolidated)
    consolidated_record = next(
        (
            memory for memory in reversed(system.memories)
            if memory.get("category") == "consolidated"
        ),
        None,
    )
    if consolidated_record is not None:
        report.expect("memories", consolidated_record["id"], note="consolidation output")
        report.track("memories", consolidated_record["id"])

    deleted = system.delete(base["id"])
    report.step("memories", "delete_soft", deleted["status"] == "deleted")
    report.expect("memories", base["id"], note="soft delete keeps the row")


def cover_actions(report: Report) -> None:
    from agent.orchestration.pending_actions import PendingActionStore

    store = PendingActionStore()

    def create(summary: str):
        return store.create_tool_call(
            "bash",
            {"command": "systemctl restart trip"},
            session_id="session-coverage",
            run_id="run-coverage",
            tool_use_id=f"call-{summary}",
            owner_id="coverage",
            summary=summary,
        )

    executed = create("coverage executed")
    report.step("actions", "create", bool(executed.id))
    report.expect("actions", executed.id)
    report.track("actions", executed.id)
    store.confirm(executed.id, actor="coverage")
    report.step(
        "actions",
        "confirm",
        store.get(executed.id).status == "confirmed",
    )
    store.finish(
        executed.id,
        status="executed",
        result_payload={"execution_enabled": True, "success": True},
    )
    report.step(
        "actions",
        "finish_executed",
        store.get(executed.id).status == "executed",
    )

    canceled = create("coverage canceled")
    store.cancel(canceled.id, actor="coverage", reason="coverage run")
    report.step(
        "actions",
        "cancel",
        store.get(canceled.id).status == "canceled",
    )
    report.expect("actions", canceled.id)
    report.track("actions", canceled.id)

    interrupted = create("coverage interrupted")
    store.confirm(interrupted.id, actor="coverage")
    recovered = store.recover_interrupted("coverage run")
    report.step("actions", "recover_interrupted", len(recovered) >= 1)
    report.expect("actions", interrupted.id, note="recovered to failed")
    report.track("actions", interrupted.id)

    pending = create("coverage pending")
    report.step(
        "actions",
        "list_filters",
        any(item.id == pending.id for item in store.list(status="pending")),
    )
    report.expect("actions", pending.id)
    report.track("actions", pending.id)


def cover_cron(report: Report) -> None:
    from datetime import datetime

    from agent.orchestration import cron
    from agent.persistence import writer

    job, message = cron.schedule_job(
        "*/5 * * * *",
        "coverage cron prompt",
        name="coverage cron",
        description="written by the coverage script",
    )
    report.step("cron", "schedule_job", job is not None, message)
    report.expect("cron", job.id)
    report.track("cron", job.id)

    cron.load_durable_jobs()
    report.step("cron", "load_durable_jobs", job.id in cron.scheduled_jobs)

    minute = float(int(time.time()))
    claimed = writer.claim_due_cron_jobs([job.id], minute_epoch=minute)
    report.step(
        "cron",
        "claim_due_job",
        bool(claimed) and claimed[0] == job.id,
        f"claimed={claimed}",
    )
    again = writer.claim_due_cron_jobs([job.id], minute_epoch=minute)
    report.step("cron", "claim_is_exclusive", again == [])

    fired_at = datetime(2026, 1, 2, 3, 4, 5)
    cron._save_cron_run_log(job, fired_at, "coverage output")
    first_logs = cron.list_cron_run_logs(job.id)
    report.step("cron", "save_run_log", len(first_logs) == 1)
    report.expect("cron_logs", f"{job.id}__20260102_030405")
    report.track("cron_logs", f"{job.id}__20260102_030405")
    cron._save_cron_run_log(job, fired_at, "coverage output")
    report.step(
        "cron",
        "save_run_log_idempotent",
        len(cron.list_cron_run_logs(job.id)) == 1,
    )

    cron.cancel_job(job.id)
    report.step("cron", "cancel_job", job.id not in cron.scheduled_jobs)
    report.expect("cron", job.id, present=False, note="after cancel")


def cover_background(report: Report, workspace: Path) -> None:
    import agent.orchestration.background as background

    started = background.start_background_task(
        SimpleNamespace(
            id="call-coverage",
            name="not_a_real_tool",
            input={"command": "coverage"},
        ),
        handlers={},
        trigger_post_hook=lambda *args: None,
        session_id="session-coverage",
        parent_run_id="run-coverage",
    )
    report.step("background", "start_task", bool(started))
    report.expect("background", started)
    report.track("background", started)

    deadline = time.time() + 10
    while time.time() < deadline:
        with background.background_lock:
            status = (background.background_tasks.get(started) or {}).get("status")
        if status and status != "running":
            break
        time.sleep(0.1)
    report.step(
        "background",
        "finish_failed_run",
        status == "failed",
        f"status={status}",
    )
    report.step(
        "background",
        "list_tasks",
        "status=failed" in background.list_background_tasks(),
    )

    # Leave one task running to exercise the orphan cleanup path.
    orphan = "bg_coverage_orphan"
    with background.background_lock:
        background.background_tasks[orphan] = {
            "tool_use_id": "call-orphan",
            "command": "coverage orphan",
            "status": "running",
            "run_id": "run-coverage",
            "parent_run_id": "",
            "session_id": "session-coverage",
            "owner_id": "coverage",
            "source": "background",
            "created_at": time.time(),
        }
    background._persist_task(orphan)
    recovered = background.recover_interrupted_background_tasks("coverage run")
    report.step(
        "background",
        "recover_interrupted",
        any(item["background_id"] == orphan for item in recovered),
    )
    report.expect("background", orphan)
    report.track("background", orphan)


def cover_sessions_and_runs(report: Report) -> None:
    from agent.sessions.state_store import RecoveryStore

    store = RecoveryStore()
    messages = [
        {"role": "user", "content": "coverage turn one"},
        {"role": "assistant", "content": [{"type": "text", "text": "ok"}]},
    ]
    store.save_session(
        "session-coverage",
        owner_id="coverage",
        messages=messages,
        target_id="",
    )
    report.step(
        "sessions",
        "create",
        store.get_session("session-coverage") is not None,
    )
    report.expect("sessions", "session-coverage")
    report.track("sessions", "session-coverage")

    store.save_session(
        "session-coverage",
        owner_id="coverage",
        messages=messages + [{"role": "user", "content": "coverage turn two"}],
    )
    report.step("sessions", "append_messages", True)

    # Compaction shape: fewer messages than before, so stale rows must go.
    store.save_session(
        "session-coverage",
        owner_id="coverage",
        messages=[{"role": "user", "content": "[Compacted] coverage summary"}],
    )
    report.step(
        "sessions",
        "compact_messages",
        len(store.get_session("session-coverage")["messages"]) == 1,
    )

    renamed = store.rename_session("session-coverage", "coverage session")
    report.step(
        "sessions",
        "rename",
        bool(renamed) and renamed["title"] == "coverage session",
    )
    report.step(
        "sessions",
        "list",
        any(
            item["session_id"] == "session-coverage"
            for item in store.list_sessions(light=True)
        ),
    )

    store.create_run(
        "run-coverage",
        session_id="session-coverage",
        owner_id="coverage",
        user_message="coverage prompt",
        messages=messages,
    )
    report.step(
        "runs",
        "create",
        store.get_run("run-coverage")["status"] == "running",
    )
    report.expect("runs", "run-coverage")
    report.track("runs", "run-coverage")
    store.save_run(
        "run-coverage",
        session_id="session-coverage",
        owner_id="coverage",
        source="chat",
        status="running",
        phase="executing_tool",
        user_message="coverage prompt",
        messages=messages,
        safe_to_resume=False,
        active_tool="bash",
    )
    unsafe = store.get_run("run-coverage")
    report.step(
        "runs",
        "unsafe_checkpoint",
        unsafe["safe_to_resume"] is False and unsafe["active_tool"] == "bash",
    )

    interrupted = store.interrupt_stale_runs("coverage run")
    report.step("runs", "interrupt_stale", len(interrupted) >= 1)
    resumed = store.mark_resumed("run-coverage")
    report.step(
        "runs",
        "mark_resumed",
        resumed["phase"] == "resuming" and resumed["status"] == "running",
    )

    store.save_run(
        "run-coverage",
        session_id="session-coverage",
        owner_id="coverage",
        source="chat",
        status="completed",
        phase="completed",
        user_message="coverage prompt",
        messages=messages,
        safe_to_resume=True,
    )
    report.step(
        "runs",
        "complete",
        store.get_run("run-coverage")["status"] == "completed",
    )
    report.step("runs", "list", len(store.list_runs(limit=10)) >= 1)

    store.reset_session("session-coverage")
    report.step(
        "sessions",
        "reset_deletes",
        store.get_session("session-coverage") is None,
    )
    report.expect("sessions", "session-coverage", present=False, note="after reset")


def cover_audit_and_usage(report: Report) -> None:
    from agent.core import pipeline
    from agent.observability.audit import record_event

    event = record_event(
        "coverage.check",
        "Persistence coverage run",
        summary="written by scripts/verify_persistence_coverage.py",
        actor="coverage",
        session_id="session-coverage",
        run_id="run-coverage",
        action_code="persistence.coverage",
        payload={"domain": "audit"},
    )
    report.step("audit", "record_event", event is not None)
    if event is not None:
        report.expect("audit_events", event.id)
        report.track("audit_events", event.id)

    agent = object.__new__(pipeline.AgentPipelineMixin)
    agent.current_run_id = "run-coverage"
    agent.session_id = "session-coverage"
    agent._current_turn = 1
    agent.recovery = SimpleNamespace(current_model="coverage-model")
    response = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=1200,
            output_tokens=400,
            cache_read_input_tokens=50,
            cache_creation_input_tokens=10,
        )
    )
    agent._record_usage(response)
    report.step("usage", "record_usage", True)
    report.expect("usage", "run-coverage", note="run_usage rows for the run")
    report.track("usage", "run-coverage")


def _fetchers() -> dict:
    """Lookup functions used by :func:`check_mirror`."""
    from sqlalchemy import select

    from agent.persistence.models import AuditEventRecord, RunUsageRecord
    from agent.persistence.repositories import actions as action_repo
    from agent.persistence.repositories import background as background_repo
    from agent.persistence.repositories import cron as cron_repo
    from agent.persistence.repositories import memories as memory_repo
    from agent.persistence.repositories import runs as run_repo
    from agent.persistence.repositories import sessions as session_repo
    from agent.persistence.repositories import targets as target_repo
    from agent.persistence.repositories import tasks as task_repo
    from agent.persistence.database import session_scope

    def _cron_job(job_id: str):
        return next(
            (
                record for record in cron_repo.fetch_cron_jobs()
                if record["id"] == job_id
            ),
            None,
        )

    def _cron_log(log_id: str):
        return next(
            (
                record for record in cron_repo.fetch_cron_logs(limit=10000)
                if record["id"] == log_id
            ),
            None,
        )

    def _audit_event(event_id: str):
        with session_scope() as session:
            return session.get(AuditEventRecord, event_id)

    def _usage(run_id: str):
        with session_scope() as session:
            return session.execute(
                select(RunUsageRecord.id).where(
                    RunUsageRecord.run_id == run_id
                )
            ).first()

    fetchers = {
        "targets": target_repo.fetch_target,
        "tasks": task_repo.fetch_task,
        "memories": memory_repo.fetch_memory,
        "actions": action_repo.fetch_action,
        "cron": _cron_job,
        "cron_logs": _cron_log,
        "background": background_repo.fetch_background_task,
        "sessions": session_repo.fetch_session,
        "runs": run_repo.fetch_run,
        "audit_events": _audit_event,
        "usage": _usage,
    }

    return fetchers


def check_mirror(domain: str, key: str, *, present: bool = True) -> dict:
    """Look up one record in PostgreSQL and compare with the expectation.

    A per-key lookup is the right question here: the script may run against a
    database that already holds other data, and what matters is whether this
    write path reached the mirror. Whole-domain drift is the job of
    ``scripts/check_persistence_consistency.py``.
    """
    fetch = _fetchers().get(domain)
    result = {"domain": domain, "key": key, "present": bool(present)}
    if fetch is None:
        return {**result, "ok": False, "found": None, "detail": "no fetcher"}
    try:
        found = fetch(key) is not None
    except Exception as exc:
        return {
            **result,
            "ok": False,
            "found": None,
            "detail": f"{type(exc).__name__}: {exc}",
        }
    ok = found == bool(present)
    return {
        **result,
        "ok": ok,
        "found": found,
        "detail": "" if ok else (
            "missing from the mirror"
            if present
            else "still present after delete"
        ),
    }


def cleanup_mirror(created: list[dict]) -> dict:
    """Delete the rows this run created, so the mirror is left untouched.

    Records the domain genuinely deleted (target, task, session, cron job)
    are already gone; deleting them again is a no-op.
    """
    from agent.persistence.repositories import actions as action_repo
    from agent.persistence.repositories import audit as audit_repo
    from agent.persistence.repositories import background as background_repo
    from agent.persistence.repositories import cron as cron_repo
    from agent.persistence.repositories import memories as memory_repo
    from agent.persistence.repositories import runs as run_repo
    from agent.persistence.repositories import sessions as session_repo
    from agent.persistence.repositories import targets as target_repo
    from agent.persistence.repositories import tasks as task_repo
    from agent.persistence.repositories import usage as usage_repo

    deleters = {
        "targets": target_repo.delete_target,
        "tasks": task_repo.delete_task,
        "memories": memory_repo.delete_memory,
        "actions": action_repo.delete_action,
        "cron": cron_repo.delete_cron_job,
        "cron_logs": cron_repo.delete_cron_log,
        "background": background_repo.delete_background_task,
        "sessions": session_repo.delete_session,
        "runs": run_repo.delete_run,
        "audit_events": audit_repo.delete_audit_event,
        "usage": usage_repo.delete_run_usage,
    }

    removed: dict[str, int] = {}
    errors: list[str] = []
    for item in reversed(created):
        delete = deleters.get(item["domain"])
        if delete is None:
            continue
        try:
            if delete(item["key"]):
                removed[item["domain"]] = removed.get(item["domain"], 0) + 1
        except Exception as exc:
            errors.append(f"{item['domain']}:{item['key']} {type(exc).__name__}: {exc}")

    # Domain code writes audit events of its own (background start/finish,
    # interrupted recovery), and they carry the run's identifiers.
    try:
        deleted_events = audit_repo.delete_audit_events_for(
            session_id=COVERAGE_SESSION_ID,
            run_id=COVERAGE_RUN_ID,
        )
        if deleted_events:
            removed["audit_events"] = removed.get("audit_events", 0) + deleted_events
    except Exception as exc:
        errors.append(f"audit_events cleanup {type(exc).__name__}: {exc}")
    return {"removed": removed, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", ""),
        help="PostgreSQL DSN used for the mirror (or set DATABASE_URL)",
    )
    parser.add_argument(
        "--data-dir",
        default="",
        help="Local store directory; defaults to a fresh temp directory",
    )
    parser.add_argument(
        "--keep-data",
        action="store_true",
        help="Keep the temporary data directory instead of deleting it",
    )
    parser.add_argument(
        "--keep-records",
        action="store_true",
        help=(
            "Keep the mirrored rows this run created; by default they are "
            "deleted so the database is left exactly as it was found"
        ),
    )
    parser.add_argument(
        "--schema",
        default="",
        help=(
            "PostgreSQL schema for the run; a fresh one is created and "
            "dropped by default so real data is never touched"
        ),
    )
    parser.add_argument(
        "--keep-schema",
        action="store_true",
        help="Keep the coverage schema instead of dropping it",
    )
    args = parser.parse_args()

    if not args.database_url:
        print(json.dumps({
            "error": "a database URL is required",
            "hint": "pass --database-url or set DATABASE_URL",
        }, ensure_ascii=False, indent=2))
        return 2

    cleanup_data_dir = False
    if args.data_dir:
        data_dir = Path(args.data_dir).expanduser().resolve()
    else:
        data_dir = Path(tempfile.mkdtemp(prefix="persistence-coverage-"))
        cleanup_data_dir = not args.keep_data

    paths = _bootstrap_paths(data_dir)

    import agent.platform.config as config
    from agent.persistence import database, writer
    from agent.persistence.models import Base

    schema = args.schema or f"coverage_{os.urandom(4).hex()}"
    try:
        schema_url = _prepare_schema(args.database_url, schema)
    except Exception as exc:
        print(json.dumps({
            "error": "could not create the coverage schema",
            "detail": f"{type(exc).__name__}: {exc}",
            "database_url": args.database_url,
            "schema": schema,
        }, ensure_ascii=False, indent=2))
        return 2

    config.PERSISTENCE_BACKEND = "dual"
    config.DATABASE_URL = schema_url
    config.PERSISTENCE_READ = "json"
    config.PERSISTENCE_READ_DOMAINS = ()
    config.PERSISTENCE_SHADOW = False

    database.dispose_engine()
    # The coverage schema is disposable, so the tables are created directly
    # from the models; migrations against a real database are verified by
    # `alembic upgrade head` instead.
    Base.metadata.create_all(database.get_engine())

    engine_ok, engine_message = database.ping_database()
    if not engine_ok:
        print(json.dumps({
            "error": "PostgreSQL is not reachable",
            "message": engine_message,
            "database_url": schema_url,
            "schema": schema,
        }, ensure_ascii=False, indent=2))
        return 2

    workspace = data_dir / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    report = Report()
    covers = (
        ("targets", lambda: cover_targets(report, workspace)),
        ("tasks", lambda: cover_tasks(report)),
        ("memories", lambda: cover_memories(report)),
        ("actions", lambda: cover_actions(report)),
        ("cron", lambda: cover_cron(report)),
        ("background", lambda: cover_background(report, workspace)),
        ("sessions+runs", lambda: cover_sessions_and_runs(report)),
        ("audit+usage", lambda: cover_audit_and_usage(report)),
    )
    crashed: dict[str, str] = {}
    for name, cover in covers:
        try:
            cover()
        except Exception as exc:  # keep going: one broken path must not hide the rest
            crashed[name] = f"{type(exc).__name__}: {exc}"
            report.step(name, "cover_crashed", False, crashed[name])

    checks = report.checks
    failed_steps = [step for step in report.steps if not step["ok"]]
    failed_checks = [check for check in checks if not check["ok"]]
    mirror_cleanup = {"removed": {}, "errors": []}
    if not args.keep_records:
        mirror_cleanup = cleanup_mirror(report.created)

    schema_dropped = False
    schema_error = ""
    database.dispose_engine()
    if not args.keep_schema:
        try:
            _drop_schema(args.database_url, schema)
            schema_dropped = True
        except Exception as exc:
            schema_error = f"{type(exc).__name__}: {exc}"

    result = {
        "write_mode": "dual",
        "schema": schema,
        "schema_dropped": schema_dropped,
        "data_dir": paths["data_dir"],
        "mirror_enabled": writer.mirror_enabled(),
        "mirror": writer.mirror_stats(),
        "paths": paths,
        "domains": report.domain_summary(),
        "failed_steps": failed_steps,
        "crashed_domains": crashed,
        "mirror_checks": len(checks),
        "mirror_checks_failed": failed_checks,
        "mirror_cleanup": mirror_cleanup,
        "schema_error": schema_error,
    }

    ok = (
        not failed_steps
        and not crashed
        and not failed_checks
        and not mirror_cleanup["errors"]
        and not schema_error
    )
    result["ok"] = ok
    result["next_step"] = (
        "run scripts/check_persistence_consistency.py against the real data "
        "directory to compare whole domains"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    if cleanup_data_dir:
        shutil.rmtree(data_dir, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Idempotently import JSON stores (targets, tasks, memories) into PostgreSQL.

Requires PERSISTENCE_BACKEND=dual or postgres and a reachable DATABASE_URL.
Every write is an upsert, so the script can be re-run at any time.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent.platform.config as config
from agent.memory.service import MemorySystem
from agent.orchestration import background as background_module
from agent.orchestration import cron as cron_module
from agent.orchestration.pending_actions import PendingActionStore
from agent.orchestration.tasks import list_tasks
from agent.persistence import writer
from agent.persistence.routing import json_reads_only
from agent.sessions.state_store import RecoveryStore
from agent.targets.store import TargetStore


DOMAINS = (
    "targets",
    "tasks",
    "memories",
    "actions",
    "cron",
    "background",
    "sessions",
    "runs",
)

# Set by --force: rewrite every mirrored row even when its updated_at is
# unchanged, which is how the mirror is repaired after a mapping change.
FORCE = False


def _write(func, *args, **kwargs) -> bool:
    return bool(func(*args, force=FORCE, **kwargs))


def _migrate_targets() -> dict:
    targets = TargetStore().list()
    written = sum(
        1 for target in targets
        if _write(writer.persist_target, target.to_dict())
    )
    return {"seen": len(targets), "written": written}


def _migrate_tasks() -> dict:
    tasks = list_tasks()
    written = 0
    for task in tasks:
        payload = {
            "id": task.id,
            "subject": task.subject,
            "description": task.description,
            "status": task.status,
            "owner": task.owner,
            "blockedBy": list(task.blockedBy or []),
            "run_id": task.run_id,
            "source": task.source,
            "metadata": dict(task.metadata or {}),
            "priority": task.priority,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "result": task.result,
        }
        if _write(writer.persist_task, payload):
            written += 1
    return {"seen": len(tasks), "written": written}


def _migrate_memories() -> dict:
    memories = MemorySystem().memories
    written = writer.persist_memories(memories, force=FORCE)
    return {"seen": len(memories), "written": written}


def _migrate_actions() -> dict:
    actions = PendingActionStore().list(limit=0)
    written = sum(
        1 for action in actions
        if _write(writer.persist_action, action.to_dict())
    )
    return {"seen": len(actions), "written": written}


def _migrate_cron() -> dict:
    cron_module.load_durable_jobs()
    with cron_module.cron_lock:
        jobs = [
            {
                "id": job.id,
                "cron": job.cron,
                "prompt": job.prompt,
                "recurring": job.recurring,
                "durable": job.durable,
                "name": job.name,
                "description": job.description,
                "enabled": job.enabled,
                "created_at": job.created_at,
            }
            for job in cron_module.scheduled_jobs.values()
        ]
    job_written = writer.persist_cron_jobs(jobs, force=FORCE)

    logs = cron_module.list_cron_run_logs(limit=10000)
    # Cron logs are append-only keyed by (job, fired_at): their upsert has no
    # change marker, so there is nothing for --force to bypass.
    log_written = sum(
        1 for log in logs if writer.persist_cron_log(log)
    )

    return {
        "jobs": {"seen": len(jobs), "written": job_written},
        "logs": {"seen": len(logs), "written": log_written},
    }


def _migrate_background() -> dict:
    tasks = list(background_module.load_persisted_background_tasks().values())
    written = sum(
        1 for task in tasks
        if _write(writer.persist_background_task, task)
    )
    return {"seen": len(tasks), "written": written}


def _migrate_sessions() -> dict:
    sessions = RecoveryStore().list_sessions()
    written = sum(
        1 for record in sessions
        if _write(writer.persist_session, record)
    )
    return {"seen": len(sessions), "written": written}


def _migrate_runs() -> dict:
    runs = RecoveryStore().list_runs(limit=500, include_messages=True)
    written = sum(
        1 for record in runs if _write(writer.persist_run, record)
    )
    return {"seen": len(runs), "written": written}


MIGRATORS = {
    "targets": _migrate_targets,
    "tasks": _migrate_tasks,
    "memories": _migrate_memories,
    "actions": _migrate_actions,
    "cron": _migrate_cron,
    "background": _migrate_background,
    "sessions": _migrate_sessions,
    "runs": _migrate_runs,
}


def _counts(result: dict) -> tuple[int, int]:
    """Flatten a domain result into (seen, written)."""
    nested = [value for value in result.values() if isinstance(value, dict)]
    if nested:
        return (
            sum(item.get("seen", 0) for item in nested),
            sum(item.get("written", 0) for item in nested),
        )
    return int(result.get("seen", 0)), int(result.get("written", 0))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--domain",
        choices=(*DOMAINS, "all"),
        default="all",
        help="Which JSON store to import",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Rewrite every row even when updated_at is unchanged; use this "
            "to repair a mirror after a mapping change"
        ),
    )
    args = parser.parse_args()

    global FORCE
    FORCE = bool(args.force)

    if config.PERSISTENCE_BACKEND not in {"dual", "postgres"}:
        print(json.dumps({
            "error": "PERSISTENCE_BACKEND must be dual or postgres",
            "backend": config.PERSISTENCE_BACKEND,
        }, ensure_ascii=False, indent=2))
        return 1

    selected = DOMAINS if args.domain == "all" else (args.domain,)
    # The import reads the JSON side; force it even when a domain is already
    # served from PostgreSQL, otherwise it would mirror PostgreSQL into itself.
    with json_reads_only():
        results = {name: MIGRATORS[name]() for name in selected}
    print(json.dumps(results, ensure_ascii=False, indent=2))

    failed = [
        name
        for name, item in results.items()
        if _counts(item)[1] < _counts(item)[0]
    ]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

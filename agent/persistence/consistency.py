"""JSON versus PostgreSQL drift detection.

The mirror is best-effort, so drift is expected to happen eventually. This
module is the read-only referee: it compares both sides for every domain and
reports what is missing or different. It never repairs anything — a repair
would hide the very problem the check exists to find.
"""

from __future__ import annotations

import threading
import time

import agent.platform.config as config
from agent.memory.service import MemorySystem
from agent.observability.audit import record_event
from agent.observability.logger import logger
from agent.orchestration import background as background_module
from agent.orchestration import cron as cron_module
from agent.orchestration.pending_actions import PendingActionStore
from agent.orchestration.tasks import list_tasks
from agent.persistence import writer
from agent.persistence.routing import json_reads_only
from agent.persistence.repositories import actions as action_repo
from agent.persistence.repositories import background as background_repo
from agent.persistence.repositories import cron as cron_repo
from agent.persistence.repositories import memories as memory_repo
from agent.persistence.repositories import runs as run_repo
from agent.persistence.repositories import sessions as session_repo
from agent.persistence.repositories import targets as target_repo
from agent.persistence.repositories import tasks as task_repo
from agent.sessions.state_store import RecoveryStore
from agent.targets.store import TargetStore
from agent.persistence.views import keyed


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

MAX_SAMPLES = 5

_watcher_lock = threading.Lock()
_watcher_thread: threading.Thread | None = None
# ``None`` means "no observation yet", so the first check always reports and
# an operator can confirm the watcher is alive and seeing a clean mirror.
_last_drift: frozenset[str] | None = None


def _targets() -> tuple[dict, dict]:
    return (
        keyed("targets", TargetStore().list()),
        keyed("targets", target_repo.fetch_targets()),
    )


def _tasks() -> tuple[dict, dict]:
    return (
        keyed("tasks", list_tasks()),
        keyed("tasks", task_repo.fetch_tasks()),
    )


def _memories() -> tuple[dict, dict]:
    return (
        keyed("memories", MemorySystem().memories),
        keyed("memories", memory_repo.fetch_memories(limit=100000)),
    )


def _actions() -> tuple[dict, dict]:
    return (
        keyed("actions", (action.to_dict() for action in PendingActionStore().list(limit=0))),
        keyed("actions", action_repo.fetch_actions(limit=0)),
    )


def _cron() -> tuple[dict, dict]:
    cron_module.load_durable_jobs()
    with cron_module.cron_lock:
        json_side = {
            job.id: {
                "cron": str(job.cron or ""),
                "prompt": str(job.prompt or ""),
                "enabled": bool(job.enabled),
                "recurring": bool(job.recurring),
                "durable": bool(job.durable),
                "name": str(job.name or ""),
            }
            for job in cron_module.scheduled_jobs.values()
            if job.durable
        }
    pg_side = {
        record["id"]: {
            "cron": str(record.get("cron") or ""),
            "prompt": str(record.get("prompt") or ""),
            "enabled": bool(record.get("enabled")),
            "recurring": bool(record.get("recurring")),
            "durable": bool(record.get("durable")),
            "name": str(record.get("name") or ""),
        }
        for record in cron_repo.fetch_cron_jobs()
    }
    return json_side, pg_side


def _background() -> tuple[dict, dict]:
    def project(record: dict) -> dict:
        return {
            "status": str(record.get("status") or ""),
            "run_id": str(record.get("run_id") or ""),
            "command": str(record.get("command") or ""),
        }

    return (
        {
            background_id: project(record)
            for background_id, record in
            background_module.load_persisted_background_tasks().items()
        },
        {
            record["background_id"]: project(record)
            for record in background_repo.fetch_background_tasks()
        },
    )


def _sessions() -> tuple[dict, dict]:
    return (
        keyed("sessions", RecoveryStore().list_sessions()),
        keyed(
            "sessions",
            session_repo.fetch_sessions(include_messages=True, limit=100000),
        ),
    )


def _runs() -> tuple[dict, dict]:
    return (
        keyed("runs", RecoveryStore().list_runs(limit=500)),
        keyed("runs", run_repo.fetch_runs(limit=500)),
    )


BUILDERS = {
    "targets": _targets,
    "tasks": _tasks,
    "memories": _memories,
    "actions": _actions,
    "cron": _cron,
    "background": _background,
    "sessions": _sessions,
    "runs": _runs,
}


def compare(json_side: dict, pg_side: dict, limit: int = MAX_SAMPLES) -> dict:
    """Compare two keyed projections and describe the difference."""
    missing_in_pg = sorted(set(json_side) - set(pg_side))
    missing_in_json = sorted(set(pg_side) - set(json_side))
    differing = []
    differing_count = 0
    for key in sorted(set(json_side) & set(pg_side)):
        if json_side[key] != pg_side[key]:
            differing_count += 1
            if len(differing) < limit:
                differing.append({
                    "key": key,
                    "json": json_side[key],
                    "postgres": pg_side[key],
                })

    return {
        "json_records": len(json_side),
        "postgres_records": len(pg_side),
        "missing_in_postgres": missing_in_pg[:limit],
        "missing_in_postgres_count": len(missing_in_pg),
        "missing_in_json": missing_in_json[:limit],
        "missing_in_json_count": len(missing_in_json),
        "differing": differing,
        "differing_count": differing_count,
        "consistent": not (
            missing_in_pg or missing_in_json or differing_count
        ),
    }


def run_consistency_check(
    domains=None,
    *,
    limit: int = MAX_SAMPLES,
) -> dict:
    """Compare the requested domains; returns a JSON-serializable report."""
    selected = tuple(domains or DOMAINS)
    results = {}
    # The JSON side must be read from the local store even when a domain has
    # already been switched to PostgreSQL; otherwise this would compare
    # PostgreSQL against itself and always look consistent.
    with json_reads_only():
        for name in selected:
            builder = BUILDERS.get(name)
            if builder is None:
                continue
            json_side, pg_side = builder()
            results[name] = compare(
                json_side,
                pg_side,
                limit=max(1, int(limit)),
            )

    drift = [name for name, item in results.items() if not item["consistent"]]
    return {
        "backend": config.PERSISTENCE_BACKEND,
        "checked_at": time.time(),
        "consistent": not drift,
        "domains_with_drift": drift,
        "results": results,
    }


def consistency_enabled() -> bool:
    return (
        writer.mirror_enabled()
        and config.PERSISTENCE_CONSISTENCY_INTERVAL_SECONDS > 0
    )


def _watch_loop(interval_seconds: int) -> None:
    while True:
        time.sleep(interval_seconds)
        try:
            report = run_consistency_check()
        except Exception:
            logger.exception("Persistence consistency check failed")
            continue
        _handle_report(report)


def _handle_report(report: dict) -> bool:
    """Emit one audit event when the drift set changes. Returns True on drift.

    Only state changes are reported: a permanently drifting domain must not
    write an audit event every interval.
    """
    global _last_drift
    drift = frozenset(report.get("domains_with_drift") or ())
    mirror = writer.mirror_stats()
    if _last_drift is not None and drift == _last_drift:
        return bool(drift)
    _last_drift = drift

    if drift:
        logger.warning(
            "Persistence drift detected in: %s",
            ", ".join(sorted(drift)),
        )
        record_event(
            "persistence.consistency.drift",
            "JSON and PostgreSQL diverged",
            summary=", ".join(sorted(drift)),
            result="failed",
            severity="high",
            actor="system",
            action_code="persistence.consistency",
            correlation_id="persistence-consistency",
            payload={
                "domains": sorted(drift),
                "results": report.get("results", {}),
                "mirror": mirror,
            },
        )
        return True

    logger.info("Persistence consistency check passed")
    record_event(
        "persistence.consistency.ok",
        "JSON and PostgreSQL are consistent",
        result="success",
        severity="info",
        actor="system",
        action_code="persistence.consistency",
        correlation_id="persistence-consistency",
        payload={"mirror": mirror},
    )
    return False


def start_consistency_watcher() -> threading.Thread | None:
    """Start the background drift checker once per process."""
    global _watcher_thread
    if not consistency_enabled():
        return None
    with _watcher_lock:
        if _watcher_thread is not None and _watcher_thread.is_alive():
            return _watcher_thread
        _watcher_thread = threading.Thread(
            target=_watch_loop,
            args=(config.PERSISTENCE_CONSISTENCY_INTERVAL_SECONDS,),
            daemon=True,
            name="persistence-consistency",
        )
        _watcher_thread.start()
        return _watcher_thread


__all__ = [
    "BUILDERS",
    "DOMAINS",
    "compare",
    "consistency_enabled",
    "run_consistency_check",
    "start_consistency_watcher",
]

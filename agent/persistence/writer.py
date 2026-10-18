"""Best-effort PostgreSQL mirror writers.

Every function here is a mirror write: the local JSON store stays the source
of truth until a domain is switched, so a failure is logged and reported as
``False`` instead of aborting the caller's operation.

Because failures are swallowed, the only way to answer "is the mirror
healthy?" is to count them. ``_mirrored`` gates, times and counts every
attempt, and ``mirror_stats()`` exposes the totals through ``/health``.
"""

from __future__ import annotations

import functools
import importlib.util
import threading
import time

import agent.platform.config as config
from agent.observability.logger import logger


VALID_BACKENDS = {"json", "dual", "postgres"}

_stats_lock = threading.Lock()
_mirror_stats: dict[str, dict[str, int]] = {}
_cooldown_until = 0.0


def _postgres_write_enabled() -> bool:
    return (
        config.PERSISTENCE_BACKEND in {"dual", "postgres"}
        and bool(config.DATABASE_URL)
    )


def _bump(name: str, outcome: str) -> None:
    with _stats_lock:
        entry = _mirror_stats.setdefault(
            name,
            {"calls": 0, "failures": 0, "skipped": 0, "deferred": 0},
        )
        entry[outcome] += 1


def _count_skipped(name: str) -> None:
    """Record a no-op write (nothing to mirror) without logging."""
    _bump(name, "skipped")


def _skip(name: str, message: str) -> bool:
    """Record a mirror the repository refused, and say why."""
    _bump(name, "skipped")
    logger.warning(message)
    return False


def _mirrored(*, disabled):
    """Gate one mirror write and count its outcome.

    ``disabled`` is the value the caller gets when the mirror is off, because
    these functions return ``bool``, ``int`` or ``list | None`` depending on
    the operation.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not _postgres_write_enabled():
                return disabled
            if _circuit_open():
                # The database just failed; retrying now would stall the
                # caller for the connect timeout again. Records written
                # during the cooldown are repaired by the import script.
                _bump(func.__name__, "deferred")
                return disabled
            try:
                result = func(*args, **kwargs)
            except Exception:
                _bump(func.__name__, "failures")
                _open_circuit()
                logger.exception(
                    "Failed to mirror %s to PostgreSQL",
                    func.__name__,
                )
                return disabled
            _close_circuit()
            _bump(func.__name__, "calls")
            return result

        return wrapper

    return decorator


def _circuit_open() -> bool:
    return time.monotonic() < _cooldown_until


def _open_circuit() -> None:
    global _cooldown_until
    cooldown = float(config.DB_FAILURE_COOLDOWN_SECONDS)
    if cooldown > 0:
        _cooldown_until = time.monotonic() + cooldown


def _close_circuit() -> None:
    global _cooldown_until
    _cooldown_until = 0.0


def mirror_enabled() -> bool:
    """Whether PostgreSQL mirror writes are active for this process."""
    return _postgres_write_enabled()


def mirror_stats() -> dict:
    """Per-writer mirror counters since this process started.

    ``calls`` counts attempts that reached the repository, ``failures`` counts
    attempts that raised, and ``skipped`` counts attempts the repository
    refused (a subset of ``calls``). A healthy mirror means ``failures == 0``
    and a ``skipped`` count that only grows for records the domain itself
    considers unusable. ``deferred`` counts writes skipped while the circuit
    was open after a failure: those records live only in the local store and
    are restored by the import script.
    """
    with _stats_lock:
        by_writer = {
            name: dict(entry)
            for name, entry in sorted(_mirror_stats.items())
        }
    totals = {
        outcome: sum(entry[outcome] for entry in by_writer.values())
        for outcome in ("calls", "failures", "skipped", "deferred")
    }
    return {
        "enabled": _postgres_write_enabled(),
        "circuit_open": _circuit_open(),
        "totals": totals,
        "by_writer": by_writer,
    }


def reset_mirror_stats() -> None:
    """Clear the counters (used by tests)."""
    global _cooldown_until
    with _stats_lock:
        _mirror_stats.clear()
    _cooldown_until = 0.0


@_mirrored(disabled=False)
def persist_audit_event(event) -> bool:
    from agent.persistence.repositories.audit import (
        persist_audit_event as _persist,
    )

    return bool(_persist(event))


@_mirrored(disabled=False)
def persist_run_usage(
    *,
    run_id: str,
    session_id: str = "",
    turn: int = 0,
    model_id: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    estimated_cost_cny: float = 0.0,
) -> bool:
    if not run_id:
        _count_skipped("persist_run_usage")
        return False
    from agent.persistence.repositories.usage import (
        persist_run_usage as _persist,
    )

    return bool(_persist(
        run_id=run_id,
        session_id=session_id,
        turn=turn,
        model_id=model_id,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
        estimated_cost_cny=estimated_cost_cny,
    ))


@_mirrored(disabled=False)
def persist_target(
    record,
    *,
    expected_version: int | None = None,
    force: bool = False,
) -> bool:
    from agent.persistence.repositories.targets import (
        upsert_target as _persist,
    )

    stored = bool(
        _persist(
            record,
            expected_version=expected_version,
            force=force,
        )
    )
    if not stored:
        return _skip(
            "persist_target",
            "Skipped target mirror write: unusable record",
        )
    return True


@_mirrored(disabled=False)
def delete_target(target_id: str) -> bool:
    from agent.persistence.repositories.targets import (
        delete_target as _delete,
    )

    return bool(_delete(target_id))


@_mirrored(disabled=False)
def persist_task(
    record,
    *,
    expected_version: int | None = None,
    force: bool = False,
) -> bool:
    from agent.persistence.repositories.tasks import (
        upsert_task as _persist,
    )

    stored = bool(
        _persist(
            record,
            expected_version=expected_version,
            force=force,
        )
    )
    if not stored:
        return _skip(
            "persist_task",
            "Skipped task mirror write: unusable record",
        )
    return True


@_mirrored(disabled=False)
def delete_task(task_id: str) -> bool:
    from agent.persistence.repositories.tasks import (
        delete_task as _delete,
    )

    return bool(_delete(task_id))


@_mirrored(disabled=False)
def persist_memory(
    record,
    *,
    expected_version: int | None = None,
    force: bool = False,
) -> bool:
    from agent.persistence.repositories.memories import (
        upsert_memory as _persist,
    )

    stored = bool(
        _persist(
            record,
            expected_version=expected_version,
            force=force,
        )
    )
    if not stored:
        return _skip(
            "persist_memory",
            "Skipped memory mirror write: unusable record",
        )
    return True


@_mirrored(disabled=0)
def persist_memories(records, *, force: bool = False) -> int:
    """Mirror a full memory list; returns the number of rows written."""
    from agent.persistence.repositories.memories import (
        upsert_memories as _persist,
    )

    return int(_persist(records, force=force))


@_mirrored(disabled=False)
def delete_memory(memory_id: str) -> bool:
    from agent.persistence.repositories.memories import (
        delete_memory as _delete,
    )

    return bool(_delete(memory_id))


@_mirrored(disabled=False)
def persist_action(record, *, force: bool = False) -> bool:
    from agent.persistence.repositories.actions import (
        upsert_action as _persist,
    )

    stored = bool(_persist(record, force=force))
    if not stored:
        return _skip(
            "persist_action",
            "Skipped pending action mirror write: unusable record",
        )
    return True


@_mirrored(disabled=False)
def confirm_action(action_id: str, record) -> bool:
    return _action_transition("confirm", action_id, record)


@_mirrored(disabled=False)
def cancel_action(action_id: str, record) -> bool:
    return _action_transition("cancel", action_id, record)


@_mirrored(disabled=False)
def finish_action(action_id: str, record) -> bool:
    return _action_transition("finish", action_id, record)


def _action_transition(kind: str, action_id: str, record) -> bool:
    """Apply the mirrored state transition with a compare-and-set.

    A rejected transition means PostgreSQL already holds a different state
    for this action. The local store stays authoritative until the read path
    is switched, so the caller keeps its own result and this only reports.
    """
    from agent.persistence.repositories import actions as repo

    transition = {
        "confirm": repo.confirm_action,
        "cancel": repo.cancel_action,
        "finish": repo.finish_action,
    }[kind]
    result = transition(action_id, record)
    if result is None:
        return _skip(
            f"{kind}_action",
            f"Pending action mirror transition rejected: {kind} {action_id}",
        )
    return True


@_mirrored(disabled=0)
def recover_interrupted_actions(reason: str) -> int:
    from agent.persistence.repositories.actions import (
        recover_interrupted_actions as _recover,
    )

    return int(_recover(reason))


@_mirrored(disabled=False)
def persist_cron_job(record, *, force: bool = False) -> bool:
    from agent.persistence.repositories.cron import (
        upsert_cron_job as _persist,
    )

    stored = bool(_persist(record, force=force))
    if not stored:
        return _skip(
            "persist_cron_job",
            "Skipped cron job mirror write: unusable record",
        )
    return True


@_mirrored(disabled=0)
def persist_cron_jobs(records, *, force: bool = False) -> int:
    from agent.persistence.repositories.cron import (
        upsert_cron_jobs as _persist,
    )

    return int(_persist(records, force=force))


@_mirrored(disabled=False)
def delete_cron_job(job_id: str) -> bool:
    from agent.persistence.repositories.cron import (
        delete_cron_job as _delete,
    )

    return bool(_delete(job_id))


def claim_due_cron_jobs(job_ids, *, minute_epoch: float) -> list[str] | None:
    """Return the jobs this process won the right to fire.

    ``None`` means the claim could not be evaluated (mirror disabled or
    database unreachable), so the caller falls back to its local gate
    instead of silently skipping every scheduled run.
    """
    if not _postgres_write_enabled():
        return None
    try:
        from agent.persistence.repositories.cron import (
            claim_due_cron_jobs as _claim,
        )

        claimed = list(_claim(job_ids, minute_epoch=minute_epoch))
    except Exception:
        _bump("claim_due_cron_jobs", "failures")
        logger.exception("Failed to claim cron jobs in PostgreSQL")
        return None
    _bump("claim_due_cron_jobs", "calls")
    return claimed


@_mirrored(disabled=False)
def persist_cron_log(record) -> bool:
    from agent.persistence.repositories.cron import (
        upsert_cron_log as _persist,
    )

    return bool(_persist(record))


@_mirrored(disabled=False)
def persist_background_task(record, *, force: bool = False) -> bool:
    from agent.persistence.repositories.background import (
        upsert_background_task as _persist,
    )

    stored = bool(_persist(record, force=force))
    if not stored:
        return _skip(
            "persist_background_task",
            "Skipped background task mirror write: unusable record",
        )
    return True


@_mirrored(disabled=False)
def mark_background_interrupted(
    background_id: str,
    *,
    reason: str,
    at: float,
) -> bool:
    from agent.persistence.repositories.background import (
        mark_background_interrupted as _mark,
    )

    return bool(_mark(background_id, reason=reason, at=at))


@_mirrored(disabled=False)
def persist_session(
    record,
    *,
    ttl_seconds: float | None = None,
    force: bool = False,
) -> bool:
    from agent.persistence.repositories.sessions import (
        upsert_session as _persist,
    )

    stored = bool(_persist(record, ttl_seconds=ttl_seconds, force=force))
    if not stored:
        return _skip(
            "persist_session",
            "Skipped session mirror write: unusable record",
        )
    return True


@_mirrored(disabled=False)
def rename_session(session_id: str, title: str) -> bool:
    from agent.persistence.repositories.sessions import (
        rename_session as _rename,
    )

    return bool(_rename(session_id, title))


@_mirrored(disabled=False)
def delete_session(session_id: str) -> bool:
    from agent.persistence.repositories.sessions import (
        delete_session as _delete,
    )

    return bool(_delete(session_id))


@_mirrored(disabled=False)
def persist_run(record, *, force: bool = False) -> bool:
    from agent.persistence.repositories.runs import (
        upsert_run as _persist,
    )

    stored = bool(_persist(record, force=force))
    if not stored:
        return _skip(
            "persist_run",
            "Skipped run mirror write: unusable record",
        )
    return True


@_mirrored(disabled=0)
def interrupt_stale_runs(reason: str) -> int:
    from agent.persistence.repositories.runs import (
        interrupt_stale_runs as _interrupt,
    )

    return int(_interrupt(reason))


def persistence_status() -> dict:
    backend = config.PERSISTENCE_BACKEND
    if backend not in VALID_BACKENDS:
        backend = "json"
    return {
        "backend": backend,
        "database_url_configured": bool(config.DATABASE_URL),
        "sqlalchemy_installed": (
            importlib.util.find_spec("sqlalchemy") is not None
        ),
        "alembic_installed": importlib.util.find_spec("alembic") is not None,
    }


__all__ = [
    "VALID_BACKENDS",
    "cancel_action",
    "claim_due_cron_jobs",
    "confirm_action",
    "delete_cron_job",
    "delete_memory",
    "delete_session",
    "delete_target",
    "delete_task",
    "finish_action",
    "interrupt_stale_runs",
    "mark_background_interrupted",
    "mirror_enabled",
    "mirror_stats",
    "persist_action",
    "persist_audit_event",
    "persist_background_task",
    "persist_cron_job",
    "persist_cron_jobs",
    "persist_cron_log",
    "persist_memories",
    "persist_memory",
    "persist_run",
    "persist_run_usage",
    "persist_session",
    "persist_target",
    "persist_task",
    "persistence_status",
    "recover_interrupted_actions",
    "rename_session",
    "reset_mirror_stats",
]

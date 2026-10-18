"""Read and write routing between the local JSON store and PostgreSQL.

Writes have been mirrored to PostgreSQL since Phase 1. Reads stay on the
local store until a domain is explicitly switched, so the cutover can be
done one domain at a time and rolled back by changing one environment
variable.

The local JSON store keeps being written even after the reads move to
PostgreSQL: it is the write-ahead journal that keeps an outage from losing
data (see docs/pg-learning-notes.md 5.16).
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager

import agent.platform.config as config
from agent.observability.logger import logger
from agent.persistence.database import postgres_enabled
from agent.persistence.views import view


# Domains whose read path can be served from PostgreSQL today. Cron and
# background tasks are deliberately absent: their read path is process-local
# runtime state, not a query over stored records.
READABLE_DOMAINS = (
    "targets",
    "tasks",
    "memories",
    "actions",
    "sessions",
    "runs",
)

VALID_READ_MODES = {"json", "postgres"}

# Tools that must inspect the local JSON side (drift detection, mirror
# import) force it per thread, so a background check never changes what a
# live request reads.
_local = threading.local()

_shadow_lock = threading.Lock()
_shadow_stats = {
    "checks": 0,
    "mismatches": 0,
    "last_mismatch": "",
    "last_mismatch_at": 0.0,
    "last_report_at": 0.0,
}


def read_mode() -> str:
    mode = config.PERSISTENCE_READ
    return mode if mode in VALID_READ_MODES else "json"


def switched_domains() -> tuple[str, ...]:
    """Domains explicitly listed in configuration, filtered to supported ones."""
    configured = config.PERSISTENCE_READ_DOMAINS
    if not configured:
        return READABLE_DOMAINS
    return tuple(
        domain for domain in READABLE_DOMAINS if domain in configured
    )


def read_from_postgres(domain: str) -> bool:
    """Whether this domain should be read from PostgreSQL right now."""
    if getattr(_local, "json_only", False):
        return False
    return _read_switched(domain)


def _read_switched(domain: str) -> bool:
    """Configuration-level read decision, ignoring the thread override."""
    if read_mode() != "postgres":
        return False
    if domain not in READABLE_DOMAINS:
        return False
    if domain not in switched_domains():
        return False
    return postgres_enabled()


@contextmanager
def json_reads_only():
    """Force store reads onto the local JSON path inside this thread."""
    previous = getattr(_local, "json_only", False)
    _local.json_only = True
    try:
        yield
    finally:
        _local.json_only = previous


def pg_read(domain: str, reader) -> tuple[bool, object]:
    """Run a PostgreSQL read, reporting whether it was used.

    Returns ``(True, value)`` when PostgreSQL answered — including an empty
    answer, which is a legitimate "this record does not exist" once the
    domain is switched. Returns ``(False, None)`` when the domain is still
    on JSON, or when the database is unreachable; the caller then serves the
    request from the local store instead of failing.
    """
    if not read_from_postgres(domain):
        return False, None
    try:
        return True, reader()
    except Exception:
        logger.exception(
            "PostgreSQL read failed for domain '%s'; falling back to the "
            "local store",
            domain,
        )
        return False, None


def shadow_enabled(domain: str) -> bool:
    """Whether single-record reads for this domain should be double-checked."""
    return (
        bool(config.PERSISTENCE_SHADOW)
        and domain in READABLE_DOMAINS
        and read_from_postgres(domain)
    )


def shadow_compare(domain: str, key: str, *, postgres_value, json_reader) -> bool:
    """Compare one request's PostgreSQL answer with the local store.

    Never raises and never changes what the caller returns: the PostgreSQL
    value is already the answer, this only decides whether to complain about
    it. Returns True when the two sides agree.
    """
    if not shadow_enabled(domain):
        return True
    try:
        local = json_reader()
    except Exception:
        logger.exception(
            "Shadow read failed for %s/%s; keeping the PostgreSQL answer",
            domain,
            key,
        )
        return True

    try:
        right = view(domain, postgres_value)
        left = view(domain, local)
    except Exception:
        logger.exception("Shadow comparison failed for %s/%s", domain, key)
        return True

    with _shadow_lock:
        _shadow_stats["checks"] += 1

    if left == right:
        return True

    now = time.time()
    with _shadow_lock:
        _shadow_stats["mismatches"] += 1
        _shadow_stats["last_mismatch"] = f"{domain}:{key}"
        _shadow_stats["last_mismatch_at"] = now
        cooldown = float(config.PERSISTENCE_SHADOW_COOLDOWN_SECONDS)
        elapsed = now - float(_shadow_stats["last_report_at"])
        should_report = elapsed >= cooldown
        if should_report:
            _shadow_stats["last_report_at"] = now

    logger.warning(
        "Shadow read mismatch for %s/%s: postgres=%s local=%s",
        domain,
        key,
        right,
        left,
    )
    if should_report:
        _record_shadow_mismatch(domain, key, right, left)
    return False


def _record_shadow_mismatch(domain: str, key: str, postgres_value, local_value) -> None:
    def _emit() -> None:
        from agent.observability.audit import record_event

        record_event(
            "persistence.shadow.mismatch",
            "Shadow read disagreed between JSON and PostgreSQL",
            summary=f"{domain}:{key}",
            result="failed",
            severity="high",
            actor="system",
            action_code="persistence.shadow",
            correlation_id="persistence-shadow",
            payload={
                "domain": domain,
                "key": key,
                "postgres": postgres_value,
                "local": local_value,
            },
        )

    try:
        if getattr(_local, "json_only", False):
            # Already forcing local reads (drift check): do not recurse into
            # the audit mirror's own store reads.
            return
        _emit()
    except Exception:
        logger.exception("Failed to record shadow mismatch")


def shadow_status() -> dict:
    with _shadow_lock:
        stats = dict(_shadow_stats)
    return {
        "shadow_enabled": bool(config.PERSISTENCE_SHADOW),
        "shadow_domains": [
            domain for domain in READABLE_DOMAINS if shadow_enabled(domain)
        ],
        "shadow_checks": stats["checks"],
        "shadow_mismatches": stats["mismatches"],
        "shadow_last_mismatch": stats["last_mismatch"],
    }


def reset_shadow_stats() -> None:
    """Test helper: clear the process-wide shadow counters."""
    with _shadow_lock:
        _shadow_stats.update({
            "checks": 0,
            "mismatches": 0,
            "last_mismatch": "",
            "last_mismatch_at": 0.0,
            "last_report_at": 0.0,
        })


def read_status() -> dict:
    """Describe the current read routing, for /health and diagnostics."""
    mode = read_mode()
    switched = switched_domains() if mode == "postgres" else ()
    active = [
        domain for domain in switched if read_from_postgres(domain)
    ]
    return {
        "read_mode": mode,
        "requested_domains": list(switched),
        "postgres_reads": active,
        "json_reads": [
            domain for domain in READABLE_DOMAINS if domain not in active
        ],
        "postgres_enabled": postgres_enabled(),
        "forced_json_thread": bool(getattr(_local, "json_only", False)),
        **shadow_status(),
    }


__all__ = [
    "READABLE_DOMAINS",
    "VALID_READ_MODES",
    "json_reads_only",
    "pg_read",
    "read_from_postgres",
    "read_mode",
    "read_status",
    "reset_shadow_stats",
    "shadow_compare",
    "shadow_enabled",
    "shadow_status",
    "switched_domains",
]

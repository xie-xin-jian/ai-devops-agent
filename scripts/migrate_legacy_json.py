#!/usr/bin/env python3
"""One-shot import of the legacy JSON stores into PostgreSQL.

The JSON persistence layer was removed in c4de430, so the surviving files
under DATA_DIR are read straight from disk here and fed to the PostgreSQL
repositories, whose upserts own all field normalization. Every write uses
``force=True`` so a re-run repairs rows even when timestamps are unchanged.

Usage (run from the project root so DATA_DIR resolves to it)::

    .venv/bin/python scripts/migrate_legacy_json.py [--domain all]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.persistence.repositories import (  # noqa: E402
    actions as actions_repo,
    background as background_repo,
    cron as cron_repo,
    memories as memories_repo,
    runs as runs_repo,
    sessions as sessions_repo,
    targets as targets_repo,
    tasks as tasks_repo,
)
from agent.platform.config import DATA_DIR  # noqa: E402


TARGETS_PATH = DATA_DIR / ".targets" / "targets.json"
TASKS_DIR = DATA_DIR / ".tasks"
MEMORIES_PATH = DATA_DIR / ".memory" / "memories.jsonl"
ACTIONS_PATH = DATA_DIR / ".pending_actions" / "actions.json"
CRON_PATH = DATA_DIR / ".scheduled_tasks.json"
CRON_LOG_DIR = DATA_DIR / ".cron_logs"
BACKGROUND_DIR = DATA_DIR / ".background"
SESSIONS_DIR = DATA_DIR / ".sessions"
RUNS_DIR = DATA_DIR / ".runs"


def _strip_nuls(value):
    """Remove NUL characters; PostgreSQL text/JSONB cannot store them."""
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {key: _strip_nuls(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_strip_nuls(item) for item in value]
    return value


def _read_json(path: Path):
    try:
        return _strip_nuls(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def _read_jsonl(path: Path) -> list:
    records = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return records
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            records.append(_strip_nuls(json.loads(line)))
        except json.JSONDecodeError:
            print(f"WARN: skip malformed memory line in {path}", file=sys.stderr)
    return records


def _migrate_targets() -> dict:
    data = _read_json(TARGETS_PATH) or {}
    records = list(data.values()) if isinstance(data, dict) else []
    written = sum(
        1 for record in records
        if targets_repo.upsert_target(record, force=True)
    )
    return {"seen": len(records), "written": written}


def _migrate_tasks() -> dict:
    records = [
        data
        for path in sorted(TASKS_DIR.glob("task_*.json"))
        if isinstance(data := _read_json(path), dict)
    ]
    written = sum(
        1 for record in records
        if tasks_repo.upsert_task(record, force=True)
    )
    return {"seen": len(records), "written": written}


def _migrate_memories() -> dict:
    records = _read_jsonl(MEMORIES_PATH)
    written = memories_repo.upsert_memories(records, force=True)
    return {"seen": len(records), "written": int(written)}


def _migrate_actions() -> dict:
    data = _read_json(ACTIONS_PATH) or {}
    records = list(data.values()) if isinstance(data, dict) else []
    written = sum(
        1 for record in records
        if actions_repo.upsert_action(record, force=True)
    )
    return {"seen": len(records), "written": written}


def _migrate_cron() -> dict:
    jobs = _read_json(CRON_PATH) or {}
    job_records = list(jobs.values()) if isinstance(jobs, dict) else []
    job_written = cron_repo.upsert_cron_jobs(job_records, force=True)

    log_records = [
        data
        for path in sorted(CRON_LOG_DIR.glob("*.json"))
        if isinstance(data := _read_json(path), dict)
    ]
    log_written = sum(
        1 for record in log_records if cron_repo.upsert_cron_log(record)
    )
    return {
        "jobs": {"seen": len(job_records), "written": int(job_written)},
        "logs": {"seen": len(log_records), "written": log_written},
    }


def _migrate_background() -> dict:
    records = [
        data
        for path in sorted(BACKGROUND_DIR.glob("bg_*.json"))
        if isinstance(data := _read_json(path), dict)
    ]
    written = sum(
        1 for record in records
        if background_repo.upsert_background_task(record, force=True)
    )
    return {"seen": len(records), "written": written}


def _migrate_sessions() -> dict:
    records = [
        data
        for path in sorted(SESSIONS_DIR.glob("*.json"))
        if isinstance(data := _read_json(path), dict)
    ]
    written = sum(
        1 for record in records
        if sessions_repo.upsert_session(record, force=True)
    )
    return {"seen": len(records), "written": written}


def _migrate_runs() -> dict:
    records = [
        data
        for path in sorted(RUNS_DIR.glob("*.json"))
        if isinstance(data := _read_json(path), dict)
    ]
    written = sum(
        1 for record in records
        if runs_repo.upsert_run(record, force=True)
    )
    return {"seen": len(records), "written": written}


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
        choices=(*MIGRATORS, "all"),
        default="all",
        help="Which legacy JSON store to import",
    )
    args = parser.parse_args()

    selected = list(MIGRATORS) if args.domain == "all" else [args.domain]
    results = {}
    for name in selected:
        try:
            results[name] = MIGRATORS[name]()
        except Exception as exc:  # keep other domains moving, report at the end
            results[name] = {"error": f"{type(exc).__name__}: {exc}"}
            print(f"ERROR: domain {name} failed", file=sys.stderr)

    print(json.dumps(results, ensure_ascii=False, indent=2))

    failed = [
        name
        for name, item in results.items()
        if "error" in item or _counts(item)[1] < _counts(item)[0]
    ]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

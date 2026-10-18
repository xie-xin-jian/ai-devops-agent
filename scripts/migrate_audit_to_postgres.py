#!/usr/bin/env python3
"""Idempotently import the JSONL audit log into PostgreSQL."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.observability.audit import AUDIT_EVENTS_PATH, AuditEvent
from agent.persistence.writer import persist_audit_event


def migrate(path: Path) -> tuple[int, int, int]:
    seen = 0
    imported = 0
    skipped = 0
    if not path.exists():
        return seen, imported, skipped
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            raw = raw.strip()
            if not raw:
                continue
            seen += 1
            try:
                event = AuditEvent.from_dict(json.loads(raw))
            except (json.JSONDecodeError, TypeError, ValueError):
                skipped += 1
                continue
            if persist_audit_event(event):
                imported += 1
            else:
                skipped += 1
    return seen, imported, skipped


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--path",
        default=str(AUDIT_EVENTS_PATH),
        help="Path to events.jsonl",
    )
    args = parser.parse_args()
    seen, imported, skipped = migrate(Path(args.path))
    print(json.dumps({
        "seen": seen,
        "imported_or_confirmed": imported,
        "skipped": skipped,
    }, ensure_ascii=False, indent=2))
    return 0 if skipped == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

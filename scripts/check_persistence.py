#!/usr/bin/env python3
"""Report PostgreSQL persistence connectivity."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.persistence.database import ping_database
from agent.persistence.writer import persistence_status


def main() -> int:
    status = persistence_status()
    db_ok, db_message = ping_database()
    result = {
        **status,
        "postgres_ok": db_ok,
        "postgres_message": db_message,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if status["backend"] == "json":
        return 0
    return 0 if db_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

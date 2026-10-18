#!/usr/bin/env python3
"""Report PostgreSQL persistence connectivity."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.persistence.database import persistence_status


def main() -> int:
    status = persistence_status()
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0 if status["database_reachable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

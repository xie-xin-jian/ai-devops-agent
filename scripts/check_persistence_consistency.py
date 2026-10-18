#!/usr/bin/env python3
"""CLI wrapper around ``agent.persistence.consistency``.

Run this before switching any read path to PostgreSQL. It is read-only: it
never repairs or writes anything, it only prints the difference so the
decision to switch (or to re-run an import) stays explicit.

    PERSISTENCE_BACKEND=dual python scripts/check_persistence_consistency.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent.platform.config as config
from agent.persistence.consistency import DOMAINS, run_consistency_check


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--domain",
        choices=(*DOMAINS, "all"),
        default="all",
    )
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    if config.PERSISTENCE_BACKEND not in {"dual", "postgres"}:
        print(json.dumps({
            "error": "PERSISTENCE_BACKEND must be dual or postgres",
            "backend": config.PERSISTENCE_BACKEND,
        }, ensure_ascii=False, indent=2))
        return 1

    selected = DOMAINS if args.domain == "all" else (args.domain,)
    report = run_consistency_check(selected, limit=max(1, args.limit))
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if report["consistent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

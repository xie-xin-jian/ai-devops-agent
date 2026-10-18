#!/usr/bin/env python3
"""Compare a current evaluation report with a baseline report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare two Agent evaluation reports",
    )
    parser.add_argument("baseline", help="baseline report JSON")
    parser.add_argument("current", help="current report JSON")
    parser.add_argument("--output", default="")
    parser.add_argument("--tolerance", type=float, default=0.0)
    parser.add_argument("--fail-on-regression", action="store_true")
    parser.add_argument("--fail-on-missing", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    from agent.evaluation.baseline import (
        compare_reports,
        has_regressions,
        load_report,
    )

    try:
        comparison = compare_reports(
            load_report(args.baseline),
            load_report(args.current),
            tolerance=args.tolerance,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    if args.output:
        destination = Path(args.output).expanduser()
        if not destination.is_absolute():
            destination = ROOT / destination
        destination = destination.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(comparison, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        comparison["output"] = str(destination)

    summary = {
        "baseline_batch_id": comparison["baseline_batch_id"],
        "current_batch_id": comparison["current_batch_id"],
        "overall": comparison["overall"],
        "regressions": len(comparison["regressions"]),
        "improvements": len(comparison["improvements"]),
        "rule_regressions": len(comparison["rule_regressions"]),
        "missing_cases": comparison["missing_cases"],
        "new_cases": comparison["new_cases"],
        "high_severity_regressions": len(
            comparison["high_severity_regressions"]
        ),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if (
        args.fail_on_regression
        and has_regressions(
            comparison,
            fail_on_missing=args.fail_on_missing,
        )
    ):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

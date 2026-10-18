#!/usr/bin/env python3
"""Run the Agent evaluation suite without waiting for manual approvals."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
import uuid


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _parse_args() -> argparse.Namespace:
    batch_id = (
        f"eval_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    )
    parser = argparse.ArgumentParser(
        description="Run AI DevOps Agent evaluation cases",
    )
    parser.add_argument(
        "--cases",
        default=str(ROOT / "eval" / "cases"),
        help="directory containing YAML case files",
    )
    parser.add_argument(
        "--fixtures",
        default=str(ROOT / "eval" / "fixtures"),
        help="directory containing fixture projects",
    )
    parser.add_argument("--batch-id", default=batch_id)
    parser.add_argument("--label", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--category", action="append", default=[])
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--run-root", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--store-db", action="store_true")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("EVAL_DATABASE_URL", ""),
        help="dedicated evaluation database URL; database name must contain 'eval'",
    )
    parser.add_argument("--stop-on-failure", action="store_true")
    parser.add_argument("--keep-workspaces", action="store_true")
    parser.add_argument(
        "--judge",
        action="store_true",
        help="enable an independent model for judge_rubric cases",
    )
    parser.add_argument("--judge-model", default="")
    parser.add_argument("--judge-threshold", type=float, default=0.7)
    parser.add_argument("--baseline", default="")
    parser.add_argument("--baseline-tolerance", type=float, default=0.0)
    parser.add_argument("--comparison-output", default="")
    parser.add_argument("--fail-on-regression", action="store_true")
    parser.add_argument("--fail-on-missing", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def _absolute(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    return candidate.resolve()


def main() -> int:
    args = _parse_args()
    run_root = _absolute(
        args.run_root
        or ROOT / "eval" / ".runtime" / args.batch_id
    )
    output = _absolute(
        args.output
        or ROOT / "eval" / "reports" / f"{args.batch_id}.json"
    )
    run_root.mkdir(parents=True, exist_ok=True)

    os.chdir(ROOT)
    os.environ["EVAL_DATA_DIR"] = str(run_root / "data")

    from agent.evaluation.cases import load_cases, validate_cases
    from agent.evaluation.runner import (
        EvalRunner,
        NullEvaluationStore,
        PostgresEvaluationStore,
        RunConfig,
        write_report,
    )
    from agent.platform import config as app_config

    # Evaluation is isolated by using a dedicated SQLite database unless the
    # caller explicitly supplies a dedicated PostgreSQL evaluation URL.
    eval_database = run_root / "data" / "evaluation.db"
    eval_database.parent.mkdir(parents=True, exist_ok=True)
    app_config.DATABASE_URL = f"sqlite+pysqlite:///{eval_database.as_posix()}"
    from agent.persistence import database

    database.dispose_engine()

    cases_dir = _absolute(args.cases)
    fixtures_dir = _absolute(args.fixtures)
    all_cases, load_errors = load_cases(cases_dir)
    validation_errors = validate_cases(all_cases, fixtures_dir)
    errors = load_errors + validation_errors
    if errors:
        print(json.dumps({"errors": errors}, ensure_ascii=False, indent=2))
        return 1

    config = RunConfig(
        cases_dir=cases_dir,
        fixtures_dir=fixtures_dir,
        run_root=run_root,
        batch_id=args.batch_id,
        label=args.label,
        model_id=args.model,
        trials_per_case=max(1, args.trials),
        categories=tuple(args.category),
        case_ids=tuple(args.case),
        tags=tuple(args.tag),
        stop_on_failure=args.stop_on_failure,
        keep_workspaces=args.keep_workspaces,
        judge_enabled=args.judge,
        judge_model_id=args.judge_model,
        judge_threshold=args.judge_threshold,
    )
    runner = EvalRunner(
        config,
        store=NullEvaluationStore(),
    )
    try:
        selected = runner.load()
    except ValueError as exc:
        print(json.dumps({"errors": [str(exc)]}, ensure_ascii=False, indent=2))
        return 1

    selection = {
        "batch_id": args.batch_id,
        "cases": len(selected),
        "planned_trials": len(selected) * config.trials_per_case,
        "by_category": {
            category: sum(
                1 for case in selected
                if case.category == category
            )
            for category in sorted({case.category for case in selected})
        },
    }
    if args.validate_only:
        print(json.dumps(
            {**selection, "validation": "ok"},
            ensure_ascii=False,
            indent=2,
        ))
        return 0

    if args.store_db:
        if not args.database_url:
            print(json.dumps({
                "errors": [
                    "--store-db requires --database-url or EVAL_DATABASE_URL",
                ],
            }, ensure_ascii=False, indent=2))
            return 1
        app_config.DATABASE_URL = args.database_url
        database.dispose_engine()

        runner.store = PostgresEvaluationStore(
            args.batch_id,
            model_id=args.model or app_config.MODEL_ID,
        )

    if args.judge:
        from agent.platform.config import API_KEY

        if not API_KEY:
            print(json.dumps({
                "errors": [
                    "--judge requires ANTHROPIC_API_KEY or API_KEY",
                ],
            }, ensure_ascii=False, indent=2))
            return 1

    baseline_report = None
    if args.baseline:
        from agent.evaluation.baseline import load_report

        try:
            baseline_report = load_report(_absolute(args.baseline))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(json.dumps({
                "errors": [f"invalid baseline report: {exc}"],
            }, ensure_ascii=False, indent=2))
            return 1
    elif args.fail_on_regression or args.fail_on_missing:
        print(json.dumps({
            "errors": ["regression gating requires --baseline"],
        }, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(selection, ensure_ascii=False))
    report = runner.run()
    destination = write_report(report, output)
    summary = {
        key: report[key]
        for key in (
            "batch_id",
            "trials",
            "completed",
            "passed",
            "failed",
            "pass_rate",
            "agent_cost_cny",
            "judge_cost_cny",
            "total_cost_cny",
            "by_category",
        )
    }
    summary["report"] = str(destination)
    summary["run_root"] = str(run_root)
    regression_failed = False
    if baseline_report is not None:
        from agent.evaluation.baseline import (
            compare_reports,
            has_regressions,
        )

        comparison = compare_reports(
            baseline_report,
            report,
            tolerance=args.baseline_tolerance,
        )
        comparison_path = _absolute(
            args.comparison_output
            or ROOT / "eval" / "reports" / f"{args.batch_id}.comparison.json"
        )
        write_report(comparison, comparison_path)
        summary["comparison"] = {
            "report": str(comparison_path),
            "regressions": len(comparison["regressions"]),
            "improvements": len(comparison["improvements"]),
            "rule_regressions": len(comparison["rule_regressions"]),
            "missing_cases": comparison["missing_cases"],
            "new_cases": comparison["new_cases"],
            "high_severity_regressions": len(
                comparison["high_severity_regressions"]
            ),
        }
        regression_failed = has_regressions(
            comparison,
            fail_on_missing=args.fail_on_missing,
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    run_failed = (
        report["failed"] != 0
        or report["completed"] != report["trials"]
    )
    return 1 if run_failed or (
        args.fail_on_regression and regression_failed
    ) else 0


if __name__ == "__main__":
    sys.exit(main())

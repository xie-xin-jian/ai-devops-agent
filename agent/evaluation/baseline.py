"""Compare two evaluation reports and identify regressions."""

from __future__ import annotations

from collections import Counter, defaultdict
import json
from pathlib import Path


def load_report(path: str | Path) -> dict:
    source = Path(path)
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError(f"not an evaluation report: {source}")
    return payload


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * ratio)))
    return ordered[index]


def _failed_rules(result: dict) -> set[str]:
    return {
        str(item.get("rule") or "")
        for item in result.get("scores") or []
        if item.get("status") in {"fail", "error"}
        and item.get("rule")
    }


def _case_summary(results: list[dict]) -> dict:
    trials = len(results)
    passed = sum(1 for item in results if item.get("passed"))
    durations = [float(item.get("duration_ms") or 0) for item in results]
    failed_rules = Counter()
    for item in results:
        failed_rules.update(_failed_rules(item))
    first = results[0] if results else {}
    return {
        "case_id": str(first.get("case_id") or ""),
        "category": str(first.get("category") or ""),
        "severity": str(first.get("severity") or "medium"),
        "trials": trials,
        "passed": passed,
        "pass_rate": passed / trials if trials else 0.0,
        "cost_cny": sum(
            float(item.get("cost_cny") or 0)
            + float(item.get("judge_cost_cny") or 0)
            for item in results
        ),
        "avg_duration_ms": (
            sum(durations) / len(durations) if durations else 0.0
        ),
        "p95_duration_ms": _percentile(durations, 0.95),
        "avg_tool_calls": (
            sum(len(item.get("tool_calls") or []) for item in results) / trials
            if trials
            else 0.0
        ),
        "failed_rules": dict(failed_rules),
    }


def _index_cases(report: dict) -> dict[str, dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for item in report.get("results") or []:
        case_id = str(item.get("case_id") or "")
        if not case_id:
            continue
        grouped[case_id].append(item)
    return {
        case_id: _case_summary(results)
        for case_id, results in grouped.items()
    }


def _overall(report: dict) -> dict:
    results = [
        item
        for item in report.get("results") or []
        if isinstance(item, dict)
    ]
    trials = len(results)
    passed = sum(1 for item in results if item.get("passed"))
    durations = [float(item.get("duration_ms") or 0) for item in results]
    return {
        "cases": len({
            str(item.get("case_id") or "")
            for item in results
            if item.get("case_id")
        }),
        "trials": trials,
        "passed": passed,
        "pass_rate": passed / trials if trials else 0.0,
        "agent_cost_cny": sum(
            float(item.get("cost_cny") or 0)
            for item in results
        ),
        "judge_cost_cny": sum(
            float(item.get("judge_cost_cny") or 0)
            for item in results
        ),
        "total_cost_cny": sum(
            float(item.get("cost_cny") or 0)
            + float(item.get("judge_cost_cny") or 0)
            for item in results
        ),
        "avg_duration_ms": (
            sum(durations) / len(durations) if durations else 0.0
        ),
        "p95_duration_ms": _percentile(durations, 0.95),
    }


def compare_reports(
    baseline: dict,
    current: dict,
    *,
    tolerance: float = 0.0,
) -> dict:
    """Compare per-case pass rates with an optional allowed regression."""
    tolerance = max(0.0, float(tolerance))
    baseline_cases = _index_cases(baseline)
    current_cases = _index_cases(current)
    common_ids = sorted(set(baseline_cases) & set(current_cases))

    regressions = []
    improvements = []
    rule_regressions = []
    for case_id in common_ids:
        before = baseline_cases[case_id]
        after = current_cases[case_id]
        new_failed_rules = sorted(
            set(after["failed_rules"]) - set(before["failed_rules"])
        )
        recovered_rules = sorted(
            set(before["failed_rules"]) - set(after["failed_rules"])
        )
        item = {
            "case_id": case_id,
            "category": after["category"] or before["category"],
            "severity": after["severity"] or before["severity"],
            "baseline_pass_rate": before["pass_rate"],
            "current_pass_rate": after["pass_rate"],
            "pass_rate_delta": after["pass_rate"] - before["pass_rate"],
            "cost_delta_cny": after["cost_cny"] - before["cost_cny"],
            "duration_delta_ms": (
                after["avg_duration_ms"] - before["avg_duration_ms"]
            ),
            "tool_call_delta": (
                after["avg_tool_calls"] - before["avg_tool_calls"]
            ),
            "new_failed_rules": new_failed_rules,
            "recovered_rules": recovered_rules,
        }
        if after["pass_rate"] + tolerance < before["pass_rate"]:
            regressions.append(item)
        elif after["pass_rate"] > before["pass_rate"] + tolerance:
            improvements.append(item)
        if new_failed_rules:
            rule_regressions.append(item)

    baseline_overall = _overall(baseline)
    current_overall = _overall(current)
    overall = {
        "baseline": baseline_overall,
        "current": current_overall,
        "pass_rate_delta": (
            current_overall["pass_rate"] - baseline_overall["pass_rate"]
        ),
        "agent_cost_delta_cny": (
            current_overall["agent_cost_cny"]
            - baseline_overall["agent_cost_cny"]
        ),
        "judge_cost_delta_cny": (
            current_overall["judge_cost_cny"]
            - baseline_overall["judge_cost_cny"]
        ),
        "total_cost_delta_cny": (
            current_overall["total_cost_cny"]
            - baseline_overall["total_cost_cny"]
        ),
        "avg_duration_delta_ms": (
            current_overall["avg_duration_ms"]
            - baseline_overall["avg_duration_ms"]
        ),
        "p95_duration_delta_ms": (
            current_overall["p95_duration_ms"]
            - baseline_overall["p95_duration_ms"]
        ),
    }
    return {
        "baseline_batch_id": baseline.get("batch_id", ""),
        "current_batch_id": current.get("batch_id", ""),
        "tolerance": tolerance,
        "overall": overall,
        "regressions": regressions,
        "improvements": improvements,
        "rule_regressions": rule_regressions,
        "missing_cases": sorted(set(baseline_cases) - set(current_cases)),
        "new_cases": sorted(set(current_cases) - set(baseline_cases)),
        "high_severity_regressions": [
            item for item in regressions
            if item.get("severity") == "high"
        ],
    }


def has_regressions(
    comparison: dict,
    *,
    fail_on_missing: bool = False,
) -> bool:
    return bool(
        comparison.get("regressions")
        or (
            fail_on_missing
            and comparison.get("missing_cases")
        )
    )


__all__ = [
    "compare_reports",
    "has_regressions",
    "load_report",
]

"""Evaluation baseline comparison tests."""

from agent.evaluation.baseline import compare_reports, has_regressions


def _result(
    case_id,
    *,
    passed,
    severity="medium",
    cost=0.01,
    judge_cost=0.0,
    duration_ms=1000,
    failed_rules=(),
):
    return {
        "case_id": case_id,
        "category": "core",
        "severity": severity,
        "passed": passed,
        "cost_cny": cost,
        "judge_cost_cny": judge_cost,
        "duration_ms": duration_ms,
        "tool_calls": [{"tool": "bash"}],
        "scores": [
            {
                "rule": rule,
                "status": "fail",
            }
            for rule in failed_rules
        ],
    }


def _report(batch_id, results):
    return {
        "batch_id": batch_id,
        "results": results,
    }


def test_compare_detects_regression_improvement_and_rule_change():
    baseline = _report("baseline", [
        _result("security", passed=True, severity="high"),
        _result("stable", passed=True),
        _result("recovered", passed=False, failed_rules=["file_exists"]),
    ])
    current = _report("current", [
        _result(
            "security",
            passed=False,
            severity="high",
            failed_rules=["answer_not_contains"],
        ),
        _result("stable", passed=True, cost=0.02, duration_ms=1500),
        _result("recovered", passed=True),
    ])

    comparison = compare_reports(baseline, current)

    assert [item["case_id"] for item in comparison["regressions"]] == [
        "security",
    ]
    assert [item["case_id"] for item in comparison["improvements"]] == [
        "recovered",
    ]
    assert len(comparison["high_severity_regressions"]) == 1
    assert comparison["rule_regressions"][0]["new_failed_rules"] == [
        "answer_not_contains",
    ]
    assert comparison["overall"]["agent_cost_delta_cny"] > 0


def test_compare_aggregates_repeated_trials():
    baseline = _report("baseline", [
        _result("flaky", passed=True),
        _result("flaky", passed=True),
    ])
    current = _report("current", [
        _result("flaky", passed=True),
        _result("flaky", passed=False, failed_rules=["run_completed"]),
    ])

    comparison = compare_reports(baseline, current)

    regression = comparison["regressions"][0]
    assert regression["baseline_pass_rate"] == 1.0
    assert regression["current_pass_rate"] == 0.5


def test_compare_reports_missing_and_new_cases():
    baseline = _report("baseline", [
        _result("missing", passed=True),
    ])
    current = _report("current", [
        _result("new", passed=True),
    ])

    comparison = compare_reports(baseline, current)

    assert comparison["missing_cases"] == ["missing"]
    assert comparison["new_cases"] == ["new"]
    assert has_regressions(comparison) is False
    assert has_regressions(comparison, fail_on_missing=True) is True

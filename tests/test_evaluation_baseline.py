"""Evaluation baseline comparison tests."""

from agent.evaluation.baseline import (
    compare_reports,
    has_regressions,
    lower_tail_p_value,
    wilson_ci,
)


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


def _trials(case_id, total, passed_count, **kwargs):
    return [
        _result(case_id, passed=index < passed_count, **kwargs)
        for index in range(total)
    ]


def test_large_drop_with_enough_samples_is_significant_regression():
    baseline = _report("baseline", _trials("case", 10, 10))
    current = _report("current", _trials("case", 10, 6))

    comparison = compare_reports(baseline, current)

    assert len(comparison["regressions"]) == 1
    regression = comparison["regressions"][0]
    assert regression["significance"] == "significant"
    assert regression["regression_p_value"] < 0.05
    assert comparison["drops_within_noise"] == []


def test_small_drop_within_noise_is_not_a_regression():
    # 0.8 -> 0.7 with 10 trials each is indistinguishable from sampling noise.
    baseline = _report("baseline", _trials("case", 10, 8))
    current = _report("current", _trials("case", 10, 7))

    comparison = compare_reports(baseline, current)

    assert comparison["regressions"] == []
    assert [item["case_id"] for item in comparison["drops_within_noise"]] == [
        "case",
    ]
    assert comparison["drops_within_noise"][0]["significance"] == "within-noise"
    assert has_regressions(comparison) is False


def test_single_trial_falls_back_to_numeric_rule():
    baseline = _report("baseline", [_result("case", passed=True)])
    current = _report("current", [_result("case", passed=False)])

    comparison = compare_reports(baseline, current)

    assert comparison["regressions"][0]["significance"] == (
        "insufficient-samples"
    )
    assert has_regressions(comparison) is True


def test_flaky_two_of_two_regression_is_flagged_without_significance():
    # 2 trials per side is still below the significance threshold, so the
    # numeric rule keeps guarding against silent flakiness regressions.
    baseline = _report("baseline", _trials("case", 2, 2))
    current = _report("current", _trials("case", 2, 1))

    comparison = compare_reports(baseline, current)

    assert comparison["regressions"][0]["significance"] == (
        "insufficient-samples"
    )


def test_wilson_interval_bounds_and_extremes():
    assert wilson_ci(0, 0) == [0.0, 1.0]
    low, high = wilson_ci(10, 10)
    assert high == 1.0
    assert 0.6 < low < 1.0
    low, high = wilson_ci(0, 10)
    assert low == 0.0
    assert 0.0 < high < 0.4
    low, high = wilson_ci(5, 10)
    assert low < 0.5 < high


def test_lower_tail_p_value_direction_and_degenerates():
    assert lower_tail_p_value(0, 0, 5, 5) == 1.0
    assert lower_tail_p_value(5, 5, 3, 5) == 1.0  # not lower
    assert lower_tail_p_value(0, 5, 5, 5) < 0.01
    assert lower_tail_p_value(7, 10, 8, 10) > 0.3  # inside noise

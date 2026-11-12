"""Quality invariants for the committed operations evaluation suite."""

from pathlib import Path

from agent.evaluation.cases import load_cases, validate_cases


ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = ROOT / "eval" / "cases"
FIXTURES_DIR = ROOT / "eval" / "fixtures"


def _ops_cases():
    cases, errors = load_cases(CASES_DIR)
    assert errors == []
    return [case for case in cases if case.id.startswith("ops-")]


def test_ops_suite_is_structurally_valid():
    cases = _ops_cases()
    assert len(cases) >= 16
    assert validate_cases(cases, FIXTURES_DIR) == []


def test_ops_suite_covers_real_operational_boundaries():
    cases = _ops_cases()
    by_id = {case.id: case for case in cases}
    categories = {case.category for case in cases}

    assert categories == {"core", "boundary", "abnormal", "faq"}
    assert len([case for case in cases if case.category == "core"]) >= 6
    assert len([case for case in cases if case.category == "boundary"]) >= 5
    assert len([case for case in cases if case.category == "abnormal"]) >= 3
    assert len([case for case in cases if case.category == "faq"]) >= 2

    for case_id in (
        "ops-boundary-sensitive-file",
        "ops-boundary-path-escape",
        "ops-abnormal-delete-denied",
        "ops-abnormal-restart-denied",
    ):
        assert by_id[case_id].severity == "high"
        assert by_id[case_id].approvals == "deny_all"

    assert by_id["ops-core-safe-edit-log-level"].approvals == "allow_list"
    assert by_id["ops-core-create-runbook"].approvals == "allow_list"
    assert by_id["ops-core-safe-edit-log-level"].allow_commands
    assert by_id["ops-core-create-runbook"].allow_commands


def test_ops_cases_do_not_rely_on_a_single_weak_assertion():
    for case in _ops_cases():
        assert len(case.expect) >= 2, case.id
        assert any(
            (
                rule == "run_completed"
                if isinstance(rule, str)
                else "run_completed" in rule
            )
            for rule in case.expect
        ), case.id


def test_fixture_contains_only_fake_secret_marker():
    credential = (FIXTURES_DIR / "ops-service" / "credentials").read_text(
        encoding="utf-8"
    )
    assert "EVAL_ONLY_SHOULD_NOT_LEAK" in credential
    secret_case = next(
        case for case in _ops_cases()
        if case.id == "ops-boundary-sensitive-file"
    )
    assert "EVAL_ONLY_SHOULD_NOT_LEAK" not in secret_case.prompt

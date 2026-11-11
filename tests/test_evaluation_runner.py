"""Evaluation runner, scoring, and approval policy tests."""

import time
from types import SimpleNamespace

import pytest

from agent.evaluation.approvals import decide_eval_approval
from agent.evaluation.cases import EvalCase, load_cases, validate_cases
from agent.evaluation.judge import JudgeVerdict, LLMJudge
from agent.evaluation.runner import (
    EvalRunner,
    NullEvaluationStore,
    PostgresEvaluationStore,
    RunConfig,
    _trial_target_name,
    write_report,
)
from agent.evaluation.scoring import TrialObservation, score_case


def _case(**overrides) -> EvalCase:
    payload = {
        "id": "case-1",
        "category": "core",
        "prompt": "inspect",
        "timeout_seconds": 30,
        "max_turns": 4,
        "approvals": "auto_readonly",
        "expect": ["run_completed"],
    }
    payload.update(overrides)
    return EvalCase.from_mapping(payload)


def test_load_and_validate_cases(tmp_path):
    cases_dir = tmp_path / "cases"
    fixtures_dir = tmp_path / "fixtures"
    (fixtures_dir / "demo").mkdir(parents=True)
    cases_dir.mkdir()
    (cases_dir / "core.yaml").write_text(
        """
- id: inspect
  category: core
  prompt: check disk
  fixture: demo
  timeout_seconds: 30
  max_turns: 3
  approvals: auto_readonly
  expect:
    - run_completed
    - tool_called:
        any_of: [disk_usage]
""".strip(),
        encoding="utf-8",
    )

    cases, errors = load_cases(cases_dir)
    assert errors == []
    assert validate_cases(cases, fixtures_dir) == []
    assert cases[0].id == "inspect"
    assert cases[0].max_turns == 3


def test_validate_catches_vacuous_delete_and_unknown_rule(tmp_path):
    fixtures_dir = tmp_path / "fixtures"
    fixture = fixtures_dir / "demo"
    fixture.mkdir(parents=True)
    case = _case(
        fixture="demo",
        expect=["file_absent: missing.txt", "unknown_rule"],
    )
    # String rules with parameters are not valid for file_absent; use a mapping
    # to prove both the missing fixture target and rule name are caught.
    case = _case(
        fixture="demo",
        expect=[{"file_absent": "missing.txt"}, "unknown_rule"],
    )

    errors = validate_cases([case], fixtures_dir)

    assert any("file_absent target is missing" in item for item in errors)
    assert any("unknown rule" in item for item in errors)


def test_scoring_covers_tools_answer_files_and_limits(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    (target / "deploy.md").write_text(
        "docker compose up -d\nhealth check",
        encoding="utf-8",
    )
    (target / "logs").mkdir()
    (target / "logs" / "app.log").write_text("ok", encoding="utf-8")
    case = _case(expect=[
        "run_completed",
        {"tool_called": {"all_of": ["target_write_file", "target_read_file"]}},
        {"tool_not_called": ["target_restart"]},
        {"max_tool_calls": 2},
        {"answer_matches": r"\d+%"},
        {"answer_contains_any": ["磁盘"]},
        {"answer_not_contains": ["secret"]},
        {"answer_max_chars": 100},
        {"file_exists": "deploy.md"},
        {"file_content_matches": {
            "path": "deploy.md",
            "pattern": "health",
        }},
        {"file_exists": "logs/app.log"},
        "approval_requested",
        "no_failed_tool",
        {"max_cost_cny": 0.1},
        {"max_duration_seconds": 5},
    ])
    observation = TrialObservation(
        status="completed",
        final_answer="磁盘剩余 42%",
        target_root=str(target),
        tool_calls=[
            {"tool": "target_write_file", "output": "ok", "ok": True},
            {"tool": "target_read_file", "output": "ok", "ok": True},
        ],
        approvals_requested=1,
        approvals_granted=1,
        cost_cny=0.05,
        duration_ms=1000,
    )

    scores = score_case(case, observation)

    assert all(item["status"] == "pass" for item in scores), scores


def test_scoring_fails_on_escaped_file_path(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    case = _case(expect=[{"file_exists": "../outside.txt"}])
    observation = TrialObservation(status="completed", target_root=str(target))

    scores = score_case(case, observation)

    assert scores[0]["status"] == "error"


def test_judge_rubric_is_reported_as_skipped():
    case = _case(
        judge_rubric="must mention logs and ports",
        expect=["run_completed"],
    )

    scores = score_case(
        case,
        TrialObservation(status="completed", final_answer="done"),
    )

    judge = next(item for item in scores if item["rule"] == "judge_rubric")
    assert judge["status"] == "skip"
    assert judge["evidence"]["rubric"] == "must mention logs and ports"


def test_postgres_eval_store_refuses_non_eval_database(monkeypatch):
    from agent.platform import config as app_config

    monkeypatch.setattr(
        app_config,
        "DATABASE_URL",
        "postgresql+psycopg://user:pass@localhost/ai_devops",
    )

    with pytest.raises(RuntimeError, match="non-evaluation"):
        PostgresEvaluationStore("batch-test")


def test_llm_judge_parses_fenced_json_and_usage():
    class Messages:
        def create(self, **kwargs):
            self.request = kwargs
            return SimpleNamespace(
                content=[SimpleNamespace(
                    type="text",
                    text=(
                        "```json\n"
                        '{"verdict":"pass","score":0.9,'
                        '"reason":"covers process and logs","missing":[]}\n'
                        "```"
                    ),
                )],
                usage=SimpleNamespace(
                    input_tokens=200,
                    output_tokens=40,
                ),
            )

    client = SimpleNamespace(messages=Messages())
    judge = LLMJudge(
        model_id="judge-model",
        threshold=0.7,
        client=client,
    )
    case = _case(
        judge_rubric="mention process and logs",
        expect=["run_completed"],
    )

    verdict = judge.evaluate(
        case,
        TrialObservation(
            status="completed",
            final_answer="check process, port and nginx logs",
        ),
    )

    assert verdict.status == "pass"
    assert verdict.score == pytest.approx(0.9)
    assert verdict.input_tokens == 200
    assert verdict.cost_cny > 0
    assert "untrusted data" in client.messages.request["messages"][0]["content"]


def test_llm_judge_reports_malformed_output_as_error():
    client = SimpleNamespace(messages=SimpleNamespace(
        create=lambda **kwargs: SimpleNamespace(
            content=[SimpleNamespace(type="text", text="not json")],
            usage=None,
        ),
    ))
    judge = LLMJudge(client=client)

    verdict = judge.evaluate(
        _case(judge_rubric="anything"),
        TrialObservation(status="completed", final_answer="answer"),
    )

    assert verdict.status == "error"
    assert "invalid judge response" in verdict.reason


@pytest.mark.parametrize(
    ("policy", "tool", "tool_input", "approved"),
    [
        ("deny_all", "target_write_file", {"path": "README.md"}, False),
        ("auto_readonly", "target_write_file", {"path": "README.md"}, False),
        ("auto_approve", "target_write_file", {"path": "README.md"}, True),
        ("auto_approve", "target_write_file", {"path": "../outside"}, False),
        ("auto_readonly", "bash", {"command": "df -h"}, True),
        ("auto_readonly", "bash", {"command": "rm -rf /"}, False),
        ("auto_approve", "bash", {"command": "pytest -q"}, True),
        ("auto_approve", "bash", {"command": "rm logs/debug.log"}, True),
    ],
)
def test_approval_policy_is_deterministic(
    tmp_path,
    policy,
    tool,
    tool_input,
    approved,
):
    case = _case(approvals=policy)
    decision = decide_eval_approval(
        case,
        {
            "payload": {
                "tool": tool,
                "input": tool_input,
            },
        },
        target_root=tmp_path,
    )

    assert decision.approved is approved, decision.reason


def test_allow_list_accepts_single_verbose_rm_inside_target(tmp_path):
    target_file = tmp_path / "logs" / "debug.log"
    target_file.parent.mkdir()
    target_file.write_text("debug", encoding="utf-8")
    case = _case(
        approvals="allow_list",
        allow_commands=[r"(?i)rm .*debug\.log"],
    )

    decision = decide_eval_approval(
        case,
        {
            "payload": {
                "tool": "bash",
                "input": {
                    "command": f'rm -v "{target_file}"',
                },
            },
        },
        target_root=tmp_path,
    )

    assert decision.approved is True, decision.reason


class _FakeAgent:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.current_run_id = "run-fake"

    def run_stream(self, prompt, cancel_event=None):
        yield {
            "type": "tool_use",
            "tool": "disk_usage",
            "input": {},
            "turn": 1,
        }
        yield {
            "type": "tool_result",
            "tool": "disk_usage",
            "output": "disk 42%",
            "turn": 1,
            "duration_ms": 5,
        }
        yield {
            "type": "done",
            "text": "磁盘剩余 42%",
            "total_turns": 1,
            "usage": {
                "input": 10,
                "output": 5,
                "est_cost_cny": 0.001,
            },
        }


class _FakeJudge:
    def evaluate(self, case, observation):
        return JudgeVerdict(
            status="pass",
            score=0.9,
            reason="answer is specific",
            evidence={"model": "fake-judge"},
            input_tokens=10,
            output_tokens=5,
            cost_cny=0.002,
            duration_ms=3,
        )


def test_runner_executes_case_and_writes_report(tmp_path):
    cases_dir = tmp_path / "cases"
    fixtures_dir = tmp_path / "fixtures"
    cases_dir.mkdir()
    fixtures_dir.mkdir()
    (cases_dir / "core.yaml").write_text(
        """
- id: inspect
  category: core
  prompt: check disk
  timeout_seconds: 10
  max_turns: 3
  approvals: auto_readonly
  expect:
    - run_completed
    - tool_called:
        any_of: [disk_usage]
    - answer_matches: '42%'
""".strip(),
        encoding="utf-8",
    )
    runner = EvalRunner(
        RunConfig(
            cases_dir=cases_dir,
            fixtures_dir=fixtures_dir,
            run_root=tmp_path / "run",
            batch_id="batch-test",
        ),
        store=NullEvaluationStore(),
        agent_factory=_FakeAgent,
    )

    report = runner.run()
    destination = write_report(report, tmp_path / "report.json")

    assert report["passed"] == 1
    assert report["results"][0]["run_id"] == "run-fake"
    assert report["results"][0]["tool_calls"][0]["output"] == "disk 42%"
    assert report["results"][0]["scores"][0]["status"] == "pass"
    assert destination.is_file()


def test_runner_uses_judge_when_enabled(tmp_path):
    cases_dir = tmp_path / "cases"
    fixtures_dir = tmp_path / "fixtures"
    cases_dir.mkdir()
    fixtures_dir.mkdir()
    (cases_dir / "faq.yaml").write_text(
        """
- id: faq-check
  category: faq
  prompt: how to check a service
  timeout_seconds: 10
  max_turns: 2
  approvals: deny_all
  judge_rubric: mention process and logs
  expect:
    - run_completed
    - answer_matches: '42%'
""".strip(),
        encoding="utf-8",
    )
    runner = EvalRunner(
        RunConfig(
            cases_dir=cases_dir,
            fixtures_dir=fixtures_dir,
            run_root=tmp_path / "run-judge",
            batch_id="batch-judge",
            judge_enabled=True,
            judge_model_id="fake-judge",
        ),
        store=NullEvaluationStore(),
        agent_factory=_FakeAgent,
        judge_factory=_FakeJudge,
    )

    report = runner.run()

    assert report["passed"] == 1
    judge_score = next(
        item
        for item in report["results"][0]["scores"]
        if item["rule"] == "judge_rubric"
    )
    assert judge_score["status"] == "pass"
    assert report["results"][0]["judge_cost_cny"] == pytest.approx(0.002)
    assert report["judge_cost_cny"] == pytest.approx(0.002)


class _VariableDelayAgent(_FakeAgent):
    """Completes after a delay derived from the session id suffix."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        suffix = str(kwargs.get("session_id", "0"))[-6:]
        self.delay = 0.01 * (int(suffix, 16) % 3 if suffix.isalnum() else 0)

    def run_stream(self, prompt, cancel_event=None):
        time.sleep(self.delay)
        yield from super().run_stream(prompt, cancel_event)


def _write_case(cases_dir, name):
    (cases_dir / f"{name}.yaml").write_text(
        f"""
- id: {name}
  category: core
  prompt: check {name}
  timeout_seconds: 10
  max_turns: 3
  approvals: auto_readonly
  expect:
    - run_completed
""".strip(),
        encoding="utf-8",
    )


def test_parallel_runner_collects_all_trials_deterministically(tmp_path):
    cases_dir = tmp_path / "cases"
    fixtures_dir = tmp_path / "fixtures"
    cases_dir.mkdir()
    fixtures_dir.mkdir()
    _write_case(cases_dir, "alpha")
    _write_case(cases_dir, "beta")
    runner = EvalRunner(
        RunConfig(
            cases_dir=cases_dir,
            fixtures_dir=fixtures_dir,
            run_root=tmp_path / "run-parallel",
            batch_id="batch-parallel",
            trials_per_case=2,
            parallel=2,
        ),
        store=NullEvaluationStore(),
        agent_factory=_VariableDelayAgent,
    )

    report = runner.run()

    assert report["trials"] == 4
    assert report["passed"] == 4
    assert [
        (item["case_id"], item["trial_no"])
        for item in report["results"]
    ] == [
        ("alpha", 1),
        ("alpha", 2),
        ("beta", 1),
        ("beta", 2),
    ]


def test_stop_on_failure_forces_serial_execution(tmp_path):
    cases_dir = tmp_path / "cases"
    fixtures_dir = tmp_path / "fixtures"
    cases_dir.mkdir()
    fixtures_dir.mkdir()
    for name in ("ok", "bad"):
        (cases_dir / f"{name}.yaml").write_text(
            f"""
- id: {name}
  category: core
  prompt: check {name}
  timeout_seconds: 10
  max_turns: 3
  approvals: auto_readonly
  expect:
    - answer_matches: 'never-matches'
""".strip(),
            encoding="utf-8",
        )
    runner = EvalRunner(
        RunConfig(
            cases_dir=cases_dir,
            fixtures_dir=fixtures_dir,
            run_root=tmp_path / "run-stop",
            batch_id="batch-stop",
            trials_per_case=1,
            parallel=4,
            stop_on_failure=True,
        ),
        store=NullEvaluationStore(),
        agent_factory=_FakeAgent,
    )

    report = runner.run()

    # Every case fails the regex assertion, so serial stop-on-failure keeps
    # only the first executed case in the report.
    assert len(report["results"]) == 1
    assert report["failed"] == 1


def test_trial_target_name_is_unique_per_trial():
    name_1 = _trial_target_name("case/a b", 1, "eval_b_case_a_b_1_aa1111")
    name_2 = _trial_target_name("case/a b", 2, "eval_b_case_a_b_2_bb2222")

    assert name_1.startswith("eval-case_a_b-t1-")
    assert name_2.startswith("eval-case_a_b-t2-")
    assert name_1 != name_2

"""Evaluation batch / trial / score storage."""

import pytest
import sqlalchemy
from sqlalchemy.pool import StaticPool

import agent.platform.config as config
from agent.persistence import database
from agent.persistence.models import Base
from agent.persistence.repositories import eval as eval_repo


@pytest.fixture
def db(monkeypatch):
    engine = sqlalchemy.create_engine(
        "sqlite+pysqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr(database, "_engine", engine)
    monkeypatch.setattr(database, "_session_factory", None)
    monkeypatch.setattr(config, "DATABASE_URL", "sqlite+pysqlite://")
    yield engine
    database.dispose_engine()
    monkeypatch.setattr(database, "_engine", None)
    monkeypatch.setattr(database, "_session_factory", None)


def test_batch_trial_score_roundtrip(db):
    batch = eval_repo.create_batch(
        "batch-1",
        suite="smoke",
        label="v1",
        model_id="test-model",
        trials_per_case=2,
        total_cases=3,
        planned_trials=6,
        config={"temperature": 0},
    )
    assert batch["id"] == "batch-1"
    assert batch["status"] == "running"
    assert batch["config"] == {"temperature": 0}

    trial_id = eval_repo.create_trial(
        batch_id="batch-1",
        case_id="inspect-disk-usage",
        trial_no=1,
        category="core",
        severity="medium",
        topic="inspection",
        run_id="run-1",
        session_id="session-1",
    )
    assert trial_id > 0

    assert eval_repo.update_trial(
        trial_id,
        status="completed",
        final_answer="D 盘剩余 281 GB",
        tool_calls=2,
        input_tokens=1200,
        output_tokens=80,
        cost_cny=0.012,
        duration_ms=42000,
        trajectory=[{"type": "tool_use", "tool": "bash"}],
    ) is True

    assert eval_repo.add_tool_calls(trial_id, "batch-1", "inspect-disk-usage", [
        {"step": 1, "tool": "bash", "arguments": {"command": "df -h"},
         "output": "/dev/sda1 44%", "ok": True, "duration_ms": 120},
        {"step": 2, "tool": "target_read_file", "arguments": {"path": "x"},
         "output": "Error: not found", "ok": False, "duration_ms": 5},
    ]) == 2

    assert eval_repo.add_scores(trial_id, "batch-1", "inspect-disk-usage", [
        {"rule": "run_completed", "status": "pass", "score": 1.0},
        {"rule": "answer_matches", "status": "pass", "score": 1.0},
    ]) == 2

    trial = eval_repo.fetch_trial(trial_id)
    assert trial["status"] == "completed"
    assert trial["final_answer"] == "D 盘剩余 281 GB"
    assert len(trial["tool_call_rows"]) == 2
    assert trial["tool_call_rows"][1]["ok"] is False
    assert [item["rule"] for item in trial["scores"]] == [
        "run_completed",
        "answer_matches",
    ]

    assert eval_repo.finish_batch("batch-1") is True
    assert eval_repo.fetch_batch("batch-1")["status"] == "completed"


def test_summary_counts_pass_fail_and_cost(db):
    eval_repo.create_batch("batch-2", total_cases=2, planned_trials=2)

    passed = eval_repo.create_trial(
        batch_id="batch-2", case_id="case-pass", category="core",
    )
    failed = eval_repo.create_trial(
        batch_id="batch-2", case_id="case-fail", category="abnormal",
    )
    timed_out = eval_repo.create_trial(
        batch_id="batch-2", case_id="case-timeout", category="boundary",
    )

    eval_repo.update_trial(passed, status="completed", cost_cny=0.01, duration_ms=1000)
    eval_repo.update_trial(failed, status="completed", cost_cny=0.02, duration_ms=3000)
    eval_repo.update_trial(timed_out, status="timeout", cost_cny=0.005, duration_ms=9000)
    eval_repo.add_scores(passed, "batch-2", "case-pass", [
        {"rule": "run_completed", "status": "pass", "score": 1.0},
    ])
    eval_repo.add_scores(failed, "batch-2", "case-fail", [
        {"rule": "file_exists", "status": "fail", "score": 0.0},
    ])
    eval_repo.add_tool_calls(passed, "batch-2", "case-pass", [
        {"step": 1, "tool": "bash", "ok": True},
        {"step": 2, "tool": "bash", "ok": False},
    ])

    summary = eval_repo.batch_summary("batch-2")

    assert summary["trials"] == 3
    assert summary["completed"] == 2
    assert summary["passed"] == 1
    assert summary["failed"] == 1
    assert summary["pass_rate"] == pytest.approx(0.5)
    assert summary["total_cost_cny"] == pytest.approx(0.035)
    assert summary["total_tool_calls"] == 2
    assert summary["by_category"]["core"]["passed"] == 1
    assert summary["by_category"]["abnormal"]["failed"] == 1
    assert summary["tools"]["bash"] == {"calls": 2, "ok": 1}


def test_trial_number_is_unique_per_batch(db):
    eval_repo.create_batch("batch-3", total_cases=1, planned_trials=1)
    eval_repo.create_trial(batch_id="batch-3", case_id="case-a", trial_no=1)

    with pytest.raises(sqlalchemy.exc.IntegrityError):
        eval_repo.create_trial(batch_id="batch-3", case_id="case-a", trial_no=1)


def test_delete_batch_cascades(db):
    eval_repo.create_batch("batch-4", total_cases=1, planned_trials=1)
    trial_id = eval_repo.create_trial(batch_id="batch-4", case_id="case-a")
    eval_repo.add_scores(trial_id, "batch-4", "case-a", [
        {"rule": "run_completed", "status": "pass"},
    ])

    assert eval_repo.delete_batch("batch-4") is True
    assert eval_repo.fetch_batch("batch-4") is None
    assert eval_repo.fetch_trial(trial_id) is None


def test_list_batches_returns_newest_first(db):
    eval_repo.create_batch("batch-old")
    eval_repo.create_batch("batch-new")

    ids = [item["id"] for item in eval_repo.list_batches()]

    assert ids[0] == "batch-new"
    assert ids[1] == "batch-old"

"""Background task output tests."""

from agent.orchestration import background
from agent.persistence.repositories import background as background_repo


def test_background_list_can_return_full_output():
    task_id = "bg_test"
    output = "\n".join(f"line {index}" for index in range(60))
    with background.background_lock:
        background.background_tasks[task_id] = {
            "status": "completed",
            "command": "long command",
        }
        background.background_results[task_id] = output

    try:
        summary = background.list_background_tasks()
        full = background.list_background_tasks(full=True)
    finally:
        with background.background_lock:
            background.background_tasks.pop(task_id, None)
            background.background_results.pop(task_id, None)

    assert "line 30" not in summary
    assert "line 30" in full


def test_recover_interrupted_background_tasks(monkeypatch):
    events = []
    monkeypatch.setattr(
        background,
        "record_event",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )
    background_repo.upsert_background_task({
        "background_id": "bg_0001",
        "status": "running",
        "run_id": "run-1",
        "session_id": "session-1",
        "owner_id": "alice",
    }, force=True)

    recovered = background.recover_interrupted_background_tasks(
        "process restarted"
    )

    assert recovered[0]["background_id"] == "bg_0001"
    data = background_repo.fetch_background_task("bg_0001")
    assert data["status"] == "failed"
    assert data["interruption_reason"] == "process restarted"
    assert events[0][0][0] == "background.run.interrupted"

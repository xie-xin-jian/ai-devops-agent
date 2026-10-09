"""Background task output tests."""

import json

from agent.orchestration import background


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


def test_recover_interrupted_background_tasks(tmp_path, monkeypatch):
    monkeypatch.setattr(background, "BACKGROUND_DIR", tmp_path)
    events = []
    monkeypatch.setattr(
        background,
        "record_event",
        lambda *args, **kwargs: events.append((args, kwargs)),
    )
    task_path = tmp_path / "bg_0001.json"
    task_path.write_text(
        json.dumps({
            "background_id": "bg_0001",
            "status": "running",
            "run_id": "run-1",
            "session_id": "session-1",
            "owner_id": "alice",
        }),
        encoding="utf-8",
    )

    recovered = background.recover_interrupted_background_tasks(
        "process restarted"
    )

    assert recovered[0]["background_id"] == "bg_0001"
    data = json.loads(task_path.read_text(encoding="utf-8"))
    assert data["status"] == "failed"
    assert data["interruption_reason"] == "process restarted"
    assert events[0][0][0] == "background.run.interrupted"

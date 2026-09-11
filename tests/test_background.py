"""Background task output tests."""

from agent import background


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

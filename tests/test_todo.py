"""Stateless todo tool tests."""

from agent.orchestration.todo import todo_write


def test_todo_write_returns_rendered_list_without_global_state():
    result = todo_write([
        {"content": "inspect disk", "status": "completed"},
        {"content": "inspect memory", "status": "in_progress"},
    ])

    assert "Todo list:" in result
    assert "[x] inspect disk" in result
    assert "[~] inspect memory" in result


def test_todo_write_rejects_invalid_status():
    result = todo_write([
        {"content": "bad item", "status": "unknown"},
    ])

    assert result.startswith("Error:")
    assert "invalid status" in result

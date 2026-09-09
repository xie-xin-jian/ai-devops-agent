import json

CURRENT_TODOS: list[dict] = []

VALID_STATUSES = {"pending", "in_progress", "completed"}


def _normalize_todos(todos) -> tuple[list | None, str | None]:
    if isinstance(todos, str):
        try:
            todos = json.loads(todos)
        except json.JSONDecodeError as e:
            return None, f"Invalid JSON: {e}"

    if not isinstance(todos, list):
        return None, "todos must be a list"

    normalized = []
    for i, todo in enumerate(todos):
        if not isinstance(todo, dict):
            return None, f"Todo at index {i} must be an object"
        if "content" not in todo:
            return None, f"Todo at index {i} missing 'content' field"
        if "status" not in todo:
            return None, f"Todo at index {i} missing 'status' field"
        if todo["status"] not in VALID_STATUSES:
            return None, f"Todo at index {i} has invalid status '{todo['status']}', must be one of {VALID_STATUSES}"
        normalized.append({
            "content": str(todo["content"]),
            "status": todo["status"],
        })

    return normalized, None


def todo_write(todos) -> str:
    global CURRENT_TODOS
    normalized, error = _normalize_todos(todos)
    if error:
        return f"Error: {error}"
    CURRENT_TODOS = normalized
    return f"Updated {len(CURRENT_TODOS)} todos"


def format_todos() -> str:
    if not CURRENT_TODOS:
        return "(no todos)"

    status_symbols = {
        "pending": "[ ]",
        "in_progress": "[~]",
        "completed": "[x]",
    }

    lines = []
    for i, todo in enumerate(CURRENT_TODOS, 1):
        symbol = status_symbols.get(todo["status"], "[?]")
        lines.append(f"{i}. {symbol} {todo['content']}")

    return "\n".join(lines)

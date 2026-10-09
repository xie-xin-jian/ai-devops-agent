import json

VALID_STATUSES = {"pending", "in_progress", "completed"}
STATUS_SYMBOLS = {
    "pending": "[ ]",
    "in_progress": "[~]",
    "completed": "[x]",
}


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
    normalized, error = _normalize_todos(todos)
    if error:
        return f"Error: {error}"
    if not normalized:
        return "(no todos)"
    lines = [
        f"{index}. {STATUS_SYMBOLS.get(todo['status'], '[?]')} {todo['content']}"
        for index, todo in enumerate(normalized, 1)
    ]
    return "Todo list:\n" + "\n".join(lines)

"""Task tool registration."""

from __future__ import annotations

from agent.orchestration.tasks import (
    claim_task,
    complete_task,
    create_task,
    get_task_json,
    list_tasks,
)
class TaskToolsMixin:
    def _task_scope(self) -> dict:
        return {
            "session_id": getattr(self, "session_id", ""),
            "owner_id": getattr(getattr(self, "principal", None), "id", ""),
            "run_id": getattr(self, "current_run_id", ""),
        }

    def _add_task_tools(self):
        tools = [
            {
                "name": "create_task",
                "description": "Create a task to plan multi-step work (3+ steps, or work spanning several turns). Call list_tasks first and reuse an existing task with the same subject instead of creating a duplicate. Use blockedBy to express dependencies on existing task ids. Skip this for a single quick action.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "subject": {"type": "string"},
                        "description": {"type": "string"},
                        "blockedBy": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "priority": {
                            "type": "string",
                            "enum": ["low", "medium", "high"],
                            "default": "medium",
                        },
                    },
                    "required": ["subject"],
                },
            },
            {
                "name": "list_tasks",
                "description": "List active tasks (pending and in_progress) for the current session.",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "get_task",
                "description": "Get full details of a specific task.",
                "input_schema": {
                    "type": "object",
                    "properties": {"task_id": {"type": "string"}},
                    "required": ["task_id"],
                },
            },
            {
                "name": "claim_task",
                "description": "Claim a pending task for execution (mark it in-progress) right before you start working on it. Only claim tasks that are not blocked.",
                "input_schema": {
                    "type": "object",
                    "properties": {"task_id": {"type": "string"}},
                    "required": ["task_id"],
                },
            },
            {
                "name": "complete_task",
                "description": "Mark a task completed. Pending tasks are auto-claimed when their dependencies are done; completing an already-completed task is a no-op. Pass a concise result summarizing the outcome so later turns know what was done.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string"},
                        "result": {"type": "string"},
                    },
                    "required": ["task_id"],
                },
            },
        ]

        def _create(subject, description="", blockedBy=None, priority="medium"):
            task = create_task(
                subject, description, blockedBy, priority,
                source="agent", **self._task_scope(),
            )
            return f"Created {task.id}: {task.subject} [{task.status}]"

        def _list():
            tasks = list_tasks(
                session_id=self._task_scope()["session_id"],
                statuses=("pending", "in_progress"),
                limit=20,
            )
            lines = []
            for task in tasks:
                line = f"  {task.id}: {task.subject} [{task.status}]"
                if task.owner:
                    line += f" (owner: {task.owner})"
                if task.blockedBy:
                    line += f" (blockedBy: {', '.join(task.blockedBy)})"
                lines.append(line)
            return "\n".join(lines) or "No tasks."

        handlers = {
            "create_task": _create,
            "list_tasks": _list,
            "get_task": lambda task_id: get_task_json(task_id),
            "claim_task": lambda task_id: claim_task(
                task_id,
                run_id=getattr(self, "current_run_id", ""),
            ),
            "complete_task": lambda task_id, result="": complete_task(task_id, result),
        }
        self.tool_registry.register_many(tools, handlers)

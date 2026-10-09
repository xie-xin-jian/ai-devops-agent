"""Task and todo tool registration."""

from __future__ import annotations

import json

from agent.orchestration.tasks import (
    claim_task,
    complete_task,
    create_task,
    get_task_json,
    list_tasks,
)
from agent.orchestration.todo import todo_write


class TaskToolsMixin:
    def _add_todo_tool(self):
        schema = {
            "name": "todo_write",
            "description": "Set or update the current todo list for your work.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "content": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed"],
                                },
                            },
                            "required": ["content", "status"],
                        },
                    },
                },
                "required": ["todos"],
            },
        }
        self.tool_registry.register(
            schema,
            lambda todos: todo_write(todos),
        )

    def _add_task_tools(self):
        tools = [
            {
                "name": "create_task",
                "description": "Create a new task with optional dependencies.",
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
                "description": "List all tasks and their status.",
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
                "description": "Claim a pending task for execution.",
                "input_schema": {
                    "type": "object",
                    "properties": {"task_id": {"type": "string"}},
                    "required": ["task_id"],
                },
            },
            {
                "name": "complete_task",
                "description": "Mark an in-progress task as completed.",
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
        handlers = {
            "create_task": lambda subject, description="", blockedBy=None, priority="medium": (
                json.dumps(
                    {"id": create_task(subject, description, blockedBy, priority).id}
                )
            ),
            "list_tasks": lambda: "\n".join(
                f"  {t.id}: {t.subject} [{t.status}]"
                + (f" (owner: {t.owner})" if t.owner else "")
                for t in list_tasks()
            )
            or "No tasks.",
            "get_task": lambda task_id: get_task_json(task_id),
            "claim_task": lambda task_id: claim_task(
                task_id,
                run_id=getattr(self, "current_run_id", ""),
            ),
            "complete_task": lambda task_id, result="": complete_task(task_id, result),
        }
        self.tool_registry.register_many(tools, handlers)

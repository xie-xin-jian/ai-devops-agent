"""Skill tool registration."""

from __future__ import annotations


from agent.platform.skill import list_skills, load_skill


class KnowledgeToolsMixin:
    def _add_skill_tools(self):
        tools = [
            {
                "name": "list_skills",
                "description": "List all available skills.",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "load_skill",
                "description": "Load a specific skill's full content into context.",
                "input_schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
        ]
        handlers = {
            "list_skills": lambda: list_skills(),
            "load_skill": lambda name: load_skill(name),
        }
        self.tool_registry.register_many(tools, handlers)

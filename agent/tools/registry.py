"""Unified tool metadata registry.

Each registered tool keeps its Schema, Handler, and Policy together. Runtime
MCP tools can be layered on top without mutating the Agent's base registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from agent.tools.policy import (
    ToolPolicy,
    ToolPolicyContext,
    evaluate_tool_policy,
    get_tool_policy,
)
from agent.tools import ALL_TOOL_HANDLERS, ALL_TOOL_SCHEMAS


@dataclass(frozen=True)
class ToolSpec:
    name: str
    schema: dict
    handler: Callable
    policy: ToolPolicy


class ToolRegistry:
    """Schema + Handler + Policy registry."""

    def __init__(self, specs: dict[str, ToolSpec] | None = None):
        self._specs = dict(specs or {})

    @classmethod
    def builtin(cls) -> "ToolRegistry":
        registry = cls()
        registry.register_many(
            ALL_TOOL_SCHEMAS,
            ALL_TOOL_HANDLERS,
        )
        return registry

    def copy(self) -> "ToolRegistry":
        return ToolRegistry(self._specs)

    def register(
        self,
        schema: dict,
        handler: Callable,
        *,
        policy: ToolPolicy | None = None,
    ) -> ToolSpec:
        if not isinstance(schema, dict):
            raise TypeError("tool schema must be a dict")
        name = str(schema.get("name") or "").strip()
        if not name:
            raise ValueError("tool schema requires a name")
        if not callable(handler):
            raise TypeError(f"tool handler for '{name}' must be callable")
        if name in self._specs:
            raise ValueError(f"tool '{name}' is already registered")
        spec = ToolSpec(
            name=name,
            schema=schema,
            handler=handler,
            policy=policy or get_tool_policy(name),
        )
        self._specs[name] = spec
        return spec

    def register_many(
        self,
        schemas: list[dict],
        handlers: dict[str, Callable],
        *,
        replace: bool = False,
    ) -> None:
        for schema in schemas:
            name = str(schema.get("name") or "").strip()
            handler = handlers.get(name)
            if not callable(handler):
                raise ValueError(
                    f"missing handler for registered tool '{name}'"
                )
            if replace and name in self._specs:
                del self._specs[name]
            self.register(schema, handler)

    def get(self, name: str) -> ToolSpec | None:
        return self._specs.get(str(name or ""))

    def replace_handler(self, name: str, handler: Callable) -> None:
        spec = self.get(name)
        if spec is None:
            raise KeyError(name)
        if not callable(handler):
            raise TypeError(f"tool handler for '{name}' must be callable")
        self._specs[name] = ToolSpec(
            name=spec.name,
            schema=spec.schema,
            handler=handler,
            policy=spec.policy,
        )

    def names(self) -> list[str]:
        return sorted(self._specs)

    def schemas(self) -> list[dict]:
        return [
            self._specs[name].schema
            for name in self.names()
        ]

    def handlers(self) -> dict[str, Callable]:
        return {
            name: self._specs[name].handler
            for name in self.names()
        }

    def policies(self) -> list[ToolPolicy]:
        return [
            self._specs[name].policy
            for name in self.names()
        ]

    def filtered_schemas(
        self,
        context: ToolPolicyContext | None,
    ) -> list[dict]:
        return [
            spec.schema
            for spec in self._specs.values()
            if evaluate_tool_policy(spec.name, context).allowed
        ]

    def with_dynamic_tools(
        self,
        schemas: list[dict],
        handlers: dict[str, Callable],
    ) -> "ToolRegistry":
        registry = self.copy()
        for schema in schemas:
            name = str(schema.get("name") or "").strip()
            if not name or name in registry._specs:
                continue
            handler = handlers.get(name)
            if callable(handler):
                registry.register(schema, handler)
        return registry


__all__ = [
    "ToolRegistry",
    "ToolSpec",
]

"""Unified ToolRegistry tests."""

from agent.core.comprehensive import ComprehensiveAgent
from agent.tools.registry import ToolRegistry


def test_agent_catalog_is_built_from_one_registry():
    schemas = ComprehensiveAgent.get_tool_catalog()
    names = [schema["name"] for schema in schemas]

    assert len(names) == 40
    assert len(names) == len(set(names))
    assert {"bash", "cpu_usage", "add_memory", "schedule_cron"}.issubset(
        names
    )


def test_registry_keeps_schema_handler_and_policy_together():
    registry = ToolRegistry.builtin()
    spec = registry.get("bash")

    assert spec is not None
    assert spec.schema["name"] == "bash"
    assert callable(spec.handler)
    assert spec.policy.name == "bash"
    assert spec.policy.requires_approval is True


def test_registry_rejects_duplicate_tool_names():
    registry = ToolRegistry.builtin()
    schema = {"name": "bash", "input_schema": {}}

    try:
        registry.register(schema, lambda: "duplicate")
    except ValueError as exc:
        assert "already registered" in str(exc)
    else:
        raise AssertionError("duplicate tool registration must fail")


def test_dynamic_registry_does_not_mutate_base_registry():
    base = ToolRegistry.builtin()
    dynamic = base.with_dynamic_tools(
        [{"name": "mcp__ops__list", "input_schema": {}}],
        {"mcp__ops__list": lambda: "ok"},
    )

    assert dynamic.get("mcp__ops__list") is not None
    assert base.get("mcp__ops__list") is None

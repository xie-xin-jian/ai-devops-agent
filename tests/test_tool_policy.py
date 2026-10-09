"""Tool policy registry and access-decision tests."""

from agent.core import comprehensive
from agent.tools.policy import (
    FILESYSTEM_READ,
    MEMORY_MANAGE,
    MEMORY_WRITE,
    ToolPolicyContext,
    evaluate_tool_policy,
    filter_tool_definitions,
    get_tool_policy,
)


def test_every_registered_tool_has_explicit_policy():
    names = {
        tool["name"]
        for tool in comprehensive.ComprehensiveAgent.get_tool_catalog()
    }
    policy_names = {
        policy.name
        for policy in comprehensive.ComprehensiveAgent.get_tool_registry().policies()
    }

    assert names == policy_names


def test_policy_catalog_includes_memory_governance_modes():
    search = get_tool_policy("search_memory")
    add = get_tool_policy("add_memory")
    update = get_tool_policy("update_memory")
    delete = get_tool_policy("delete_memory")

    assert search.read_only is True
    assert search.requires_approval is False
    assert add.read_only is False
    assert add.requires_approval is False
    assert MEMORY_WRITE in update.required_scopes
    assert delete.read_only is False
    assert MEMORY_MANAGE in delete.required_scopes
    assert delete.requires_approval is False


def test_unknown_and_mcp_tools_fail_closed():
    unknown = get_tool_policy("custom_unknown_tool")
    mcp_read = get_tool_policy("mcp__ops__list_services")
    mcp_write = get_tool_policy("mcp__deploy__trigger")
    mcp_mixed = get_tool_policy("mcp__ops__list_and_delete")

    assert unknown.requires_approval is True
    assert unknown.risk_level == "high"
    assert mcp_read.read_only is True
    assert mcp_read.requires_approval is False
    assert mcp_write.read_only is False
    assert mcp_write.requires_approval is True
    assert mcp_mixed.read_only is False
    assert mcp_mixed.requires_approval is True


def test_mcp_description_destructive_requires_approval(monkeypatch):
    from agent.mcp import registry

    client = registry.MCPClient("ops")
    client.register(
        [
            {
                "name": "inspect_data",
                "description": "Destructive operation hidden behind a read name.",
            }
        ],
        {},
    )
    monkeypatch.setitem(registry.mcp_clients, "ops", client)

    policy = get_tool_policy("mcp__ops__inspect_data")

    assert policy.read_only is False
    assert policy.requires_approval is True


def test_scope_filtering_hides_tools_without_permission():
    context = ToolPolicyContext(
        permissions=frozenset({FILESYSTEM_READ}),
        write_enabled=False,
        execute_enabled=False,
    )

    allowed = {
        tool["name"]
        for tool in filter_tool_definitions(
            comprehensive.ComprehensiveAgent.get_tool_catalog(),
            context,
        )
    }

    assert "read_file" in allowed
    assert "glob" in allowed
    assert "write_file" not in allowed
    assert "bash" not in allowed
    assert "search_memory" not in allowed


def test_run_allowlist_is_enforced_before_call():
    context = ToolPolicyContext(
        allowed_tools=frozenset({"read_file", "search_memory"}),
    )

    read_decision = evaluate_tool_policy("read_file", context)
    bash_decision = evaluate_tool_policy("bash", context)

    assert read_decision.allowed is True
    assert bash_decision.allowed is False
    assert "allowlist" in bash_decision.reason


def test_high_risk_execution_can_be_disabled():
    context = ToolPolicyContext(
        permissions=frozenset({"*"}),
        write_enabled=False,
        execute_enabled=False,
    )

    decision = evaluate_tool_policy("bash", context)

    assert decision.allowed is False
    assert decision.requires_approval is True
    assert "Write operations are disabled" in decision.reason


def test_approval_metadata_does_not_change_read_only_decisions():
    context = ToolPolicyContext()

    decision = evaluate_tool_policy("read_file", context)

    assert decision.allowed is True
    assert decision.requires_approval is False
    assert decision.policy.sandbox_required is True

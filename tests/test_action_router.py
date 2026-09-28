"""Action routing and tool-scope tests."""

from agent.action_router import (
    ACTION_DEFINITIONS,
    PLAN_REACT,
    REACT,
    filter_action_tools,
    get_action_catalog,
    resolve_action_tool_names,
    route_action,
)
from agent.tool_policy import ToolPolicyContext


def test_routes_system_inspection_to_read_only_action():
    action = route_action("检查一下服务器 CPU、内存和磁盘状态")

    assert action.code == "system.inspect"
    assert action.agent_mode == REACT
    assert action.requires_approval is False
    assert "system_info" in action.allowed_tools
    assert "bash" not in action.allowed_tools


def test_routes_command_request_to_plan_react_with_preflight():
    action = route_action("重启 nginx 服务并检查端口")

    assert action.code == "command.execute"
    assert action.agent_mode == PLAN_REACT
    assert action.preflight_required is True
    assert action.requires_approval is True
    assert "bash" in action.allowed_tools


def test_routes_memory_changes_before_memory_recall():
    action = route_action("记住这个服务器使用 8080 端口")

    assert action.code == "memory.manage"
    assert "add_memory" in action.allowed_tools
    assert action.preflight_required is True


def test_routes_specific_memory_deletion_to_management():
    action = route_action("删除这条记忆")

    assert action.code == "memory.manage"
    assert "delete_memory" in action.allowed_tools


def test_routes_script_execution_to_command_action():
    action = route_action("运行脚本并查看结果")

    assert action.code == "command.execute"
    assert "bash" in action.allowed_tools


def test_general_fallback_is_read_only():
    action = route_action("你好，解释一下什么是 Agent")

    assert action.code == "general.chat"
    assert "bash" not in action.allowed_tools
    assert "write_file" not in action.allowed_tools
    assert "search_memory" in action.allowed_tools


def test_background_monitor_is_selected_before_generic_task_management():
    action = route_action("查看后台任务进度")

    assert action.code == "background.monitor"
    assert "list_background_tasks" in action.allowed_tools
    assert "create_task" not in action.allowed_tools


def test_action_tools_intersect_with_runtime_policy():
    action = ACTION_DEFINITIONS["command.execute"]
    context = ToolPolicyContext(
        write_enabled=False,
        execute_enabled=False,
    )

    resolved = resolve_action_tool_names(action, context)

    assert "bash" not in resolved
    assert "write_file" not in resolved
    assert "read_file" in resolved


def test_filter_action_tools_uses_same_allowlist():
    action = ACTION_DEFINITIONS["file.read"]
    tools = [
        {"name": "read_file"},
        {"name": "write_file"},
        {"name": "bash"},
    ]

    filtered = filter_action_tools(tools, action)

    assert filtered == [{"name": "read_file"}]


def test_preflight_mode_hides_approval_required_tools():
    action = ACTION_DEFINITIONS["command.execute"]
    tools = [
        {"name": "read_file"},
        {"name": "write_file"},
        {"name": "bash"},
        {"name": "propose_action"},
    ]

    filtered = filter_action_tools(
        tools,
        action,
        preflight_mode=True,
    )

    assert filtered == [
        {"name": "read_file"},
        {"name": "propose_action"},
    ]


def test_action_catalog_is_serializable_and_complete():
    catalog = get_action_catalog()
    codes = {item["code"] for item in catalog}

    assert codes == set(ACTION_DEFINITIONS)
    assert all(item["allowed_tools"] for item in catalog)
    assert all(item["agent_mode"] for item in catalog)

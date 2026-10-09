"""MCP compatibility facade."""

# ruff: noqa: F401

from agent.mcp.builtin import MOCK_SERVERS, connect_mcp
from agent.mcp.custom import (
    CUSTOM_MCP_PATH,
    _build_handler,
    _load_custom_servers,
    _make_echo_handler,
    _make_http_handler,
    _make_shell_handler,
    _save_custom_servers,
    list_custom_servers,
    load_all_custom_servers,
    register_custom_server,
    remove_custom_server,
)
from agent.mcp.registry import (
    MCPClient,
    assemble_tool_pool,
    disconnect_mcp,
    get_mcp_tool_names,
    is_destructive_mcp_tool,
    is_mcp_tool,
    list_connected_mcp,
    mcp_clients,
    normalize_mcp_name,
)
from agent.mcp.sse import (
    _make_sse_handler,
    _sse_mcp_sessions,
    connect_sse_mcp,
    disconnect_sse_mcp,
    list_sse_mcp_servers,
)
from agent.mcp.stdio import (
    _make_stdio_handler,
    _recv_response,
    _send_rpc,
    _stdio_mcp_sessions,
    connect_stdio_mcp,
    disconnect_stdio_mcp,
    list_stdio_mcp_servers,
)

__all__ = [name for name in globals() if not name.startswith("__")]

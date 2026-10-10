"""Built-in mock MCP servers."""

from __future__ import annotations

from typing import Callable

import agent.platform.config as config
from agent.mcp.registry import MCPClient, _set_mcp_context, mcp_clients


def _mock_server_docs():
    client = MCPClient("docs")
    client.register(
        tool_defs=[
            {
                "name": "search",
                "description": "Search documentation. (readOnly)",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
            {
                "name": "get_version",
                "description": "Get API version. (readOnly)",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            },
        ],
        handlers={
            "search": lambda query: f"[docs] Found 3 results for '{query}'",
            "get_version": lambda: "[docs] API v2.1.0",
        },
    )
    return client


def _mock_server_deploy():
    client = MCPClient("deploy")
    client.register(
        tool_defs=[
            {
                "name": "trigger",
                "description": "Trigger a deployment. (destructive - requires approval)",
                "inputSchema": {
                    "type": "object",
                    "properties": {"service": {"type": "string"}},
                    "required": ["service"],
                },
            },
            {
                "name": "status",
                "description": "Check deployment status. (readOnly)",
                "inputSchema": {
                    "type": "object",
                    "properties": {"service": {"type": "string"}},
                    "required": ["service"],
                },
            },
        ],
        handlers={
            "trigger": lambda service: f"[deploy] Triggered: {service}",
            "status": lambda service: f"[deploy] {service}: running (v1.4.2)",
        },
    )
    return client


def _mock_server_metrics():
    client = MCPClient("metrics")
    client.register(
        tool_defs=[
            {
                "name": "cpu",
                "description": "Get current CPU usage. (readOnly)",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "memory",
                "description": "Get current memory usage. (readOnly)",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            },
        ],
        handlers={
            "cpu": lambda: "[metrics] CPU: 23%",
            "memory": lambda: "[metrics] Memory: 4.2GB / 16GB",
        },
    )
    return client


def _mock_server_alert():
    client = MCPClient("alert")
    client.register(
        tool_defs=[
            {
                "name": "send_dingtalk",
                "description": "Send message to DingTalk group. (readOnly)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "webhook_url": {"type": "string"},
                        "message": {"type": "string"},
                    },
                    "required": ["webhook_url", "message"],
                },
            },
            {
                "name": "send_wechat",
                "description": "Send message to WeChat Work group. (readOnly)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "webhook_url": {"type": "string"},
                        "message": {"type": "string"},
                    },
                    "required": ["webhook_url", "message"],
                },
            },
            {
                "name": "check_status",
                "description": "Check alert service status. (readOnly)",
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            },
        ],
        handlers={
            "send_dingtalk": lambda webhook_url, message: f"[alert] DingTalk message sent: '{message}'",
            "send_wechat": lambda webhook_url, message: f"[alert] WeChat message sent: '{message}'",
            "check_status": lambda: "[alert] Notification service is running",
        },
    )
    return client


MOCK_SERVERS: dict[str, Callable[[], MCPClient]] = {
    "docs": _mock_server_docs,
    "deploy": _mock_server_deploy,
    "metrics": _mock_server_metrics,
    "alert": _mock_server_alert,
}


def connect_mcp(
    name: str,
    *,
    owner_id: str = "",
    session_id: str = "",
    run_id: str = "",
    source: str = "mcp",
) -> str:
    """连接一个 MCP 服务器并发现其工具。"""
    if not config.ENABLE_MOCK_MCP:
        return (
            "Error: built-in mock MCP is disabled. "
            "Set ENABLE_MOCK_MCP=1 only for local demos."
        )
    if name in mcp_clients:
        return f"MCP server '{name}' already connected"
    factory = MOCK_SERVERS.get(name)
    if not factory:
        available = ", ".join(MOCK_SERVERS.keys())
        return f"Unknown server '{name}'. Available: {available}"
    mcp_client = factory()
    _set_mcp_context(
        mcp_client,
        owner_id=owner_id,
        session_id=session_id,
        run_id=run_id,
        source=source,
    )
    mcp_clients[name] = mcp_client
    tool_names = [t["name"] for t in mcp_client.tools]
    return (
        f"Connected to MCP server '{name}'. "
        f"Discovered {len(mcp_client.tools)} tools: {', '.join(tool_names)}"
    )

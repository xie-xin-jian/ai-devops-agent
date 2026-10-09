"""Shared MCP client registry and dynamic tool pool."""

from __future__ import annotations

import re
from typing import Callable

_DISALLOWED_CHARS = re.compile(r"[^a-zA-Z0-9_-]")

mcp_clients: dict[str, MCPClient] = {}


class MCPClient:
    """发现并调用 MCP 服务器上的工具。"""

    def __init__(self, name: str):
        self.name = name
        self.tools: list[dict] = []
        self._handlers: dict[str, Callable] = {}
        self.owner_id = ""
        self.session_id = ""
        self.run_id = ""
        self.source = "system"

    def register(self, tool_defs: list[dict], handlers: dict[str, Callable]):
        self.tools = tool_defs
        self._handlers = handlers

    def call_tool(self, tool_name: str, args: dict) -> str:
        handler = self._handlers.get(tool_name)
        if not handler:
            return f"MCP error: unknown tool '{tool_name}'"
        try:
            return handler(**args)
        except Exception as e:
            return f"MCP error: {e}"


def _set_mcp_context(
    client: MCPClient,
    *,
    owner_id: str = "",
    session_id: str = "",
    run_id: str = "",
    source: str = "mcp",
) -> None:
    client.owner_id = str(owner_id or "")
    client.session_id = str(session_id or "")
    client.run_id = str(run_id or "")
    client.source = str(source or "mcp")


def normalize_mcp_name(name: str) -> str:
    return _DISALLOWED_CHARS.sub("_", name)


def disconnect_mcp(name: str) -> str:
    if name not in mcp_clients:
        return f"MCP server '{name}' not connected"
    del mcp_clients[name]
    return f"Disconnected MCP server '{name}'"


def list_connected_mcp() -> list[dict]:
    result = []
    for name, client in mcp_clients.items():
        result.append({"name": name, "tools": [t["name"] for t in client.tools]})
    return result


def _mcp_client_visible(client: MCPClient, context: dict | None) -> bool:
    if not context:
        return True
    owner_id = str(context.get("owner_id") or "")
    session_id = str(context.get("session_id") or "")
    if client.session_id:
        return bool(session_id and client.session_id == session_id)
    if client.owner_id:
        return bool(owner_id and client.owner_id == owner_id)
    return True


def assemble_tool_pool(
    builtin_tools: list[dict],
    builtin_handlers: dict,
    context: dict | None = None,
) -> tuple[list[dict], dict]:
    """合并内置工具 + 所有 MCP 工具为一个池。"""
    tools = list(builtin_tools)
    handlers = dict(builtin_handlers)
    for server_name, mcp_client in mcp_clients.items():
        if not _mcp_client_visible(mcp_client, context):
            continue
        safe_server = normalize_mcp_name(server_name)
        for tool_def in mcp_client.tools:
            safe_tool = normalize_mcp_name(tool_def["name"])
            prefixed = f"mcp__{safe_server}__{safe_tool}"
            tools.append(
                {
                    "name": prefixed,
                    "description": tool_def.get("description", ""),
                    "input_schema": tool_def.get("inputSchema", {}),
                }
            )
            handlers[prefixed] = lambda *, c=mcp_client, t=tool_def[
                "name"
            ], **kw: c.call_tool(t, kw)
    return tools, handlers


def get_mcp_tool_names(context: dict | None = None) -> list[str]:
    names = []
    for server_name, mcp_client in mcp_clients.items():
        if not _mcp_client_visible(mcp_client, context):
            continue
        safe_server = normalize_mcp_name(server_name)
        for tool_def in mcp_client.tools:
            safe_tool = normalize_mcp_name(tool_def["name"])
            names.append(f"mcp__{safe_server}__{safe_tool}")
    return names


def is_mcp_tool(tool_name: str) -> bool:
    return tool_name.startswith("mcp__")


def is_destructive_mcp_tool(tool_name: str) -> bool:
    """判断 MCP 工具是否破坏性：deploy 视为破坏性，并扩展检查 description。"""
    if not is_mcp_tool(tool_name):
        return False
    if "deploy" in tool_name:
        return True
    for server_name, mcp_client in mcp_clients.items():
        safe_server = normalize_mcp_name(server_name)
        prefix = f"mcp__{safe_server}__"
        if tool_name.startswith(prefix):
            original_name = tool_name[len(prefix) :]
            for tool_def in mcp_client.tools:
                if normalize_mcp_name(tool_def["name"]) == original_name:
                    desc = tool_def.get("description", "").lower()
                    if "destructive" in desc:
                        return True
    return False

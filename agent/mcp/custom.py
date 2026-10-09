"""Custom MCP server registration and handlers."""

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from agent.mcp.builtin import MOCK_SERVERS
from agent.mcp.registry import MCPClient, mcp_clients
from agent.platform.config import ENABLE_UNSAFE_MCP_SHELL

CUSTOM_MCP_PATH = Path(__file__).parent.parent.parent / ".mcp_servers.json"


def _make_echo_handler(tool_name: str):
    """echo handler：原样返回传入参数。"""

    def handler(**kwargs):
        return f"[echo:{tool_name}] " + json.dumps(kwargs, ensure_ascii=False)

    return handler


def _make_http_handler(tool_name: str, config: dict):
    """http handler：调用外部 HTTP 接口。"""
    url = config.get("url", "")
    method = config.get("method", "POST").upper()

    def handler(**kwargs):
        if not url:
            return f"[http:{tool_name}] error: no url configured"
        try:
            if method == "GET":
                from urllib.parse import urlencode

                query = urlencode(kwargs)
                full_url = f"{url}?{query}" if query else url
                req = urllib.request.Request(full_url)
            else:
                body = json.dumps(kwargs).encode("utf-8")
                req = urllib.request.Request(
                    url,
                    data=body,
                    method=method,
                    headers={"Content-Type": "application/json"},
                )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return f"[http:{tool_name}] {resp.status}: {resp.read().decode('utf-8', errors='replace')[:500]}"
        except urllib.error.HTTPError as e:
            return f"[http:{tool_name}] HTTP {e.code}: {e.reason}"
        except Exception as e:
            return f"[http:{tool_name}] error: {e}"

    return handler


def _make_shell_handler(tool_name: str, config: dict):
    """shell handler：执行 shell 命令模板。"""
    command_template = config.get("command", "")

    def handler(**kwargs):
        if not command_template:
            return f"[shell:{tool_name}] error: no command configured"
        try:
            cmd = command_template.format(**kwargs)
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=30
            )
            output = result.stdout.strip()
            if result.stderr:
                output += f"\n[stderr] {result.stderr.strip()}"
            return f"[shell:{tool_name}] {output[:500]}"
        except subprocess.TimeoutExpired:
            return f"[shell:{tool_name}] timeout after 30s"
        except Exception as e:
            return f"[shell:{tool_name}] error: {e}"

    return handler


def _build_handler(tool_def: dict):
    """根据工具定义构建 handler。"""
    tool_name = tool_def.get("name", "unknown")
    handler_type = tool_def.get("handler_type", "echo")
    handler_config = tool_def.get("handler_config", {})
    if handler_type == "http":
        return _make_http_handler(tool_name, handler_config)
    if handler_type == "shell":
        if not ENABLE_UNSAFE_MCP_SHELL:
            return lambda **kwargs: (
                f"[shell:{tool_name}] error: disabled; "
                "set ENABLE_UNSAFE_MCP_SHELL=1 only in a trusted local environment"
            )
        return _make_shell_handler(tool_name, handler_config)
    return _make_echo_handler(tool_name)


def _load_custom_servers() -> dict:
    """从磁盘加载自定义服务器配置。"""
    if not CUSTOM_MCP_PATH.exists():
        return {}
    try:
        return json.loads(CUSTOM_MCP_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_custom_servers(servers: dict) -> None:
    """保存自定义服务器配置到磁盘。"""
    CUSTOM_MCP_PATH.write_text(
        json.dumps(servers, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _instantiate_custom_server(name: str, config: dict) -> MCPClient:
    """根据配置创建 MCPClient 并注册到 mcp_clients。"""
    client = MCPClient(name)
    tool_defs = []
    handlers = {}
    for tool in config.get("tools", []):
        tool_defs.append(
            {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "inputSchema": tool.get(
                    "input_schema", {"type": "object", "properties": {}, "required": []}
                ),
            }
        )
        handlers[tool["name"]] = _build_handler(tool)
    client.register(tool_defs, handlers)
    mcp_clients[name] = client
    return client


def register_custom_server(name: str, description: str, tools: list[dict]) -> str:
    """注册一个自定义 MCP 服务器。

    name: 服务器名（唯一标识）
    description: 服务器描述
    tools: 工具定义列表，每个工具包含：
        - name, description, input_schema
        - handler_type: echo / http / shell
        - handler_config: handler 配置
    """
    if name in MOCK_SERVERS:
        return f"Cannot override builtin server '{name}'"
    if not tools:
        return "No tools provided"
    if not ENABLE_UNSAFE_MCP_SHELL and any(
        tool.get("handler_type") == "shell" for tool in tools
    ):
        return (
            "Cannot register shell MCP tools while "
            "ENABLE_UNSAFE_MCP_SHELL is disabled"
        )
    servers = _load_custom_servers()
    servers[name] = {"description": description, "tools": tools}
    _save_custom_servers(servers)
    _instantiate_custom_server(name, servers[name])
    tool_names = [t["name"] for t in tools]
    return (
        f"Registered custom MCP server '{name}'. "
        f"Added {len(tools)} tools: {', '.join(tool_names)}"
    )


def load_all_custom_servers() -> None:
    """启动时加载所有自定义服务器。"""
    servers = _load_custom_servers()
    for name, config in servers.items():
        _instantiate_custom_server(name, config)


def remove_custom_server(name: str) -> str:
    """删除一个自定义 MCP 服务器。"""
    if name in MOCK_SERVERS:
        return f"Cannot remove builtin server '{name}'"
    servers = _load_custom_servers()
    if name not in servers:
        return f"Custom server '{name}' not found"
    del servers[name]
    _save_custom_servers(servers)
    mcp_clients.pop(name, None)
    return f"Removed custom MCP server '{name}'"


def list_custom_servers() -> list[dict]:
    """列出自定义服务器配置。"""
    servers = _load_custom_servers()
    result = []
    for name, config in servers.items():
        result.append(
            {
                "name": name,
                "description": config.get("description", ""),
                "tools": [
                    {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "handler_type": t.get("handler_type", "echo"),
                    }
                    for t in config.get("tools", [])
                ],
            }
        )
    return result

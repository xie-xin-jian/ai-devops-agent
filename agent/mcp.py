"""
MCP (Model Context Protocol) 系统 - 对齐 s20 的设计。

核心思想（来自 s20）：
- MCP 工具是"延迟绑定"的：先 connect 发现工具，再合并到主工具池
- 工具命名规则：mcp__{server}__{tool}，避免和内置工具冲突
- 每次调用 assemble_tool_pool() 会把内置工具 + 所有已连接 MCP 工具合并成一个池
"""

import re
from typing import Callable


class MCPClient:
    """发现并调用 MCP 服务器上的工具。对齐 s20 的 MCPClient。"""

    def __init__(self, name: str):
        self.name = name
        self.tools: list[dict] = []
        self._handlers: dict[str, Callable] = {}

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


mcp_clients: dict[str, MCPClient] = {}
_DISALLOWED_CHARS = re.compile(r"[^a-zA-Z0-9_-]")


def normalize_mcp_name(name: str) -> str:
    return _DISALLOWED_CHARS.sub("_", name)


def _mock_server_docs():
    client = MCPClient("docs")
    client.register(
        tool_defs=[
            {"name": "search", "description": "Search documentation. (readOnly)",
             "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
            {"name": "get_version", "description": "Get API version. (readOnly)",
             "inputSchema": {"type": "object", "properties": {}, "required": []}},
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
            {"name": "trigger", "description": "Trigger a deployment. (destructive - requires approval)",
             "inputSchema": {"type": "object", "properties": {"service": {"type": "string"}}, "required": ["service"]}},
            {"name": "status", "description": "Check deployment status. (readOnly)",
             "inputSchema": {"type": "object", "properties": {"service": {"type": "string"}}, "required": ["service"]}},
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
            {"name": "cpu", "description": "Get current CPU usage. (readOnly)",
             "inputSchema": {"type": "object", "properties": {}, "required": []}},
            {"name": "memory", "description": "Get current memory usage. (readOnly)",
             "inputSchema": {"type": "object", "properties": {}, "required": []}},
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
            {"name": "send_dingtalk", "description": "Send message to DingTalk group. (readOnly)",
             "inputSchema": {"type": "object", "properties": {"webhook_url": {"type": "string"}, "message": {"type": "string"}}, "required": ["webhook_url", "message"]}},
            {"name": "send_wechat", "description": "Send message to WeChat Work group. (readOnly)",
             "inputSchema": {"type": "object", "properties": {"webhook_url": {"type": "string"}, "message": {"type": "string"}}, "required": ["webhook_url", "message"]}},
            {"name": "check_status", "description": "Check alert service status. (readOnly)",
             "inputSchema": {"type": "object", "properties": {}, "required": []}},
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

def connect_mcp(name: str) -> str:
    """连接一个 MCP 服务器并发现其工具。对齐 s20。"""
    if name in mcp_clients:
        return f"MCP server '{name}' already connected"
    factory = MOCK_SERVERS.get(name)
    if not factory:
        available = ", ".join(MOCK_SERVERS.keys())
        return f"Unknown server '{name}'. Available: {available}"
    mcp_client = factory()
    mcp_clients[name] = mcp_client
    tool_names = [t["name"] for t in mcp_client.tools]
    return (f"Connected to MCP server '{name}'. "
            f"Discovered {len(mcp_client.tools)} tools: {', '.join(tool_names)}")


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


def assemble_tool_pool(builtin_tools: list[dict], builtin_handlers: dict) -> tuple[list[dict], dict]:
    """合并内置工具 + 所有 MCP 工具为一个池。对齐 s20。"""
    tools = list(builtin_tools)
    handlers = dict(builtin_handlers)
    for server_name, mcp_client in mcp_clients.items():
        safe_server = normalize_mcp_name(server_name)
        for tool_def in mcp_client.tools:
            safe_tool = normalize_mcp_name(tool_def["name"])
            prefixed = f"mcp__{safe_server}__{safe_tool}"
            tools.append({
                "name": prefixed,
                "description": tool_def.get("description", ""),
                "input_schema": tool_def.get("inputSchema", {}),
            })
            handlers[prefixed] = (
                lambda *, c=mcp_client, t=tool_def["name"], **kw: c.call_tool(t, kw))
    return tools, handlers


def get_mcp_tool_names() -> list[str]:
    names = []
    for server_name, mcp_client in mcp_clients.items():
        safe_server = normalize_mcp_name(server_name)
        for tool_def in mcp_client.tools:
            safe_tool = normalize_mcp_name(tool_def["name"])
            names.append(f"mcp__{safe_server}__{safe_tool}")
    return names


def is_mcp_tool(tool_name: str) -> bool:
    return tool_name.startswith("mcp__")


def is_destructive_mcp_tool(tool_name: str) -> bool:
    """判断 MCP 工具是否破坏性。对齐 s20：deploy 视为破坏性，并扩展检查 description。"""
    if not is_mcp_tool(tool_name):
        return False
    if "deploy" in tool_name:
        return True
    for server_name, mcp_client in mcp_clients.items():
        safe_server = normalize_mcp_name(server_name)
        prefix = f"mcp__{safe_server}__"
        if tool_name.startswith(prefix):
            original_name = tool_name[len(prefix):]
            for tool_def in mcp_client.tools:
                if normalize_mcp_name(tool_def["name"]) == original_name:
                    desc = tool_def.get("description", "").lower()
                    if "destructive" in desc:
                        return True
    return False


# ========================================
# 自定义 MCP 服务器（用户运行时添加工具）
# ========================================

import json
import subprocess
import urllib.request
import urllib.error
from pathlib import Path

# 持久化路径
CUSTOM_MCP_PATH = Path(__file__).parent.parent / ".mcp_servers.json"


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
                    url, data=body, method=method,
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
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
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
        json.dumps(servers, indent=2, ensure_ascii=False), encoding="utf-8")


def _instantiate_custom_server(name: str, config: dict) -> MCPClient:
    """根据配置创建 MCPClient 并注册到 mcp_clients。"""
    client = MCPClient(name)
    tool_defs = []
    handlers = {}
    for tool in config.get("tools", []):
        tool_defs.append({
            "name": tool["name"],
            "description": tool.get("description", ""),
            "inputSchema": tool.get("input_schema", {"type": "object", "properties": {}, "required": []}),
        })
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
    servers = _load_custom_servers()
    servers[name] = {"description": description, "tools": tools}
    _save_custom_servers(servers)
    _instantiate_custom_server(name, servers[name])
    tool_names = [t["name"] for t in tools]
    return (f"Registered custom MCP server '{name}'. "
            f"Added {len(tools)} tools: {', '.join(tool_names)}")


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
        result.append({
            "name": name,
            "description": config.get("description", ""),
            "tools": [
                {"name": t["name"], "description": t.get("description", ""),
                 "handler_type": t.get("handler_type", "echo")}
                for t in config.get("tools", [])
            ],
        })
    return result


# ========================================
# 标准 MCP 客户端 - 连接真实的 MCP 服务器
# 通过 JSON-RPC over stdio 与外部 MCP 服务器通信
# ========================================

import json
import subprocess
import threading
from typing import Any


_stdio_mcp_sessions: dict[str, dict] = {}
_stdio_mcp_lock = threading.Lock()
_next_id = 1000


def _next_rpc_id() -> int:
    global _next_id
    _next_id += 1
    return _next_id


def _tool_to_schema(tool_def: dict) -> dict:
    """把 MCP 服务器返回的工具定义转换成项目通用的 schema 格式。"""
    return {
        "name": tool_def.get("name", "unknown"),
        "description": tool_def.get("description", ""),
        "inputSchema": tool_def.get("inputSchema", {"type": "object", "properties": {}, "required": []}),
    }


def _send_rpc(proc: subprocess.Popen, method: str, params: dict | None = None,
              request_id: int | None = None) -> int | None:
    """发送 JSON-RPC 请求到 MCP 服务器。

    如果 request_id 为 0，表示发送通知（不带 id 字段）。
    否则自动生成一个请求 id。
    """
    req = {
        "jsonrpc": "2.0",
        "method": method,
    }
    if request_id != 0:
        req["id"] = request_id if request_id is not None else _next_rpc_id()
    if params is not None:
        req["params"] = params
    proc.stdin.write(json.dumps(req) + "\n")
    proc.stdin.flush()
    return req.get("id")


def _recv_response(proc: subprocess.Popen, timeout: float = 30.0) -> dict:
    """读取 MCP 服务器的 JSON-RPC 响应。"""
    import time

    end_time = time.time() + timeout
    while time.time() < end_time:
        line = proc.stdout.readline()
        if line:
            try:
                data = json.loads(line.strip())
                if "id" in data:
                    return data
            except json.JSONDecodeError:
                continue
        else:
            time.sleep(0.1)
    raise TimeoutError("MCP server response timeout")


def _make_stdio_handler(server_name: str, tool_name: str):
    """创建一个调用真实 MCP 工具的 handler。"""
    def handler(**kwargs):
        session = _stdio_mcp_sessions.get(server_name)
        if not session:
            return f"MCP error: server '{server_name}' not connected"
        proc = session["proc"]
        try:
            req_id = _send_rpc(
                proc, "tools/call",
                {"name": tool_name, "arguments": kwargs}
            )
            resp = _recv_response(proc)
            result = resp.get("result", {})
            content = result.get("content", [])
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(item.get("text", ""))
                elif isinstance(item, dict):
                    parts.append(str(item))
                else:
                    parts.append(str(item))
            return "\n".join(parts)[:5000]
        except Exception as e:
            return f"MCP error: {e}"
    return handler


def connect_stdio_mcp(name: str, command: str, args: list[str] | None = None,
                      cwd: str | None = None) -> str:
    """通过 stdio 连接一个标准的 MCP 服务器。

    Args:
        name: 服务器名称（唯一标识）
        command: 启动服务器的命令，如 "python"
        args: 命令参数列表，如 ["mcp_servers/alert_server.py"]
        cwd: 工作目录

    Returns:
        连接结果消息
    """
    with _stdio_mcp_lock:
        if name in mcp_clients:
            return f"MCP server '{name}' already connected"

        try:
            proc = subprocess.Popen(
                [command] + (args or []),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=cwd,
                bufsize=1,
            )

            _send_rpc(
                proc, "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "devops-agent", "version": "1.0"}
                }
            )
            init_resp = _recv_response(proc)
            server_info = init_resp.get("result", {}).get("serverInfo", {})
            server_name = server_info.get("name", name)

            _send_rpc(proc, "notifications/initialized", params=None, request_id=0)

            _send_rpc(proc, "tools/list")
            tools_resp = _recv_response(proc)
            tools_list = tools_resp.get("result", {}).get("tools", [])
            tool_defs = [_tool_to_schema(t) for t in tools_list]

            client = MCPClient(name)
            handlers = {}
            for t in tools_list:
                handlers[t["name"]] = _make_stdio_handler(name, t["name"])

            client.register(tool_defs, handlers)
            mcp_clients[name] = client
            _stdio_mcp_sessions[name] = {"proc": proc, "server_name": server_name}

            tool_names = [t["name"] for t in tools_list]
            return (f"Connected to standard MCP server '{name}' ({server_name}). "
                    f"Discovered {len(tool_names)} tools: {', '.join(tool_names)}")
        except Exception as e:
            return f"Error connecting to MCP server '{name}': {e}"


def disconnect_stdio_mcp(name: str) -> str:
    """断开标准 MCP 服务器连接。"""
    with _stdio_mcp_lock:
        if name not in _stdio_mcp_sessions:
            return f"Standard MCP server '{name}' not found"

        session = _stdio_mcp_sessions.pop(name)
        proc = session.get("proc")
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        mcp_clients.pop(name, None)
        return f"Disconnected standard MCP server '{name}'"


def list_stdio_mcp_servers() -> list[str]:
    """列出所有已连接的标准 MCP 服务器名称。"""
    return list(_stdio_mcp_sessions.keys())

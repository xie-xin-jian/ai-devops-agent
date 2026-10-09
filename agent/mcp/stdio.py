"""MCP JSON-RPC over stdio transport."""

from __future__ import annotations

import json
import subprocess
import threading

from agent.mcp.registry import MCPClient, _set_mcp_context, mcp_clients

_stdio_mcp_sessions: dict[str, dict] = {}
_stdio_mcp_lock = threading.Lock()
_next_id = 1000
_next_id_lock = threading.Lock()


def _next_rpc_id() -> int:
    global _next_id
    with _next_id_lock:
        _next_id += 1
        return _next_id


def _tool_to_schema(tool_def: dict) -> dict:
    """把 MCP 服务器返回的工具定义转换成项目通用的 schema 格式。"""
    return {
        "name": tool_def.get("name", "unknown"),
        "description": tool_def.get("description", ""),
        "inputSchema": tool_def.get(
            "inputSchema", {"type": "object", "properties": {}, "required": []}
        ),
    }


def _send_rpc(
    proc: subprocess.Popen,
    method: str,
    params: dict | None = None,
    request_id: int | None = None,
) -> int | None:
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


def _recv_response(
    proc: subprocess.Popen,
    timeout: float = 30.0,
    request_id: int | None = None,
) -> dict:
    """读取并校验 MCP 服务器的 JSON-RPC 响应。"""
    import time

    end_time = time.time() + timeout
    while time.time() < end_time:
        line = proc.stdout.readline()
        if line:
            try:
                data = json.loads(line.strip())
                if "id" in data and (request_id is None or data["id"] == request_id):
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
            with session["lock"]:
                req_id = _send_rpc(
                    proc, "tools/call", {"name": tool_name, "arguments": kwargs}
                )
                resp = _recv_response(proc, request_id=req_id)
            if "error" in resp:
                return f"MCP error: {resp['error']}"
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


def connect_stdio_mcp(
    name: str,
    command: str,
    args: list[str] | None = None,
    cwd: str | None = None,
    *,
    owner_id: str = "",
    session_id: str = "",
    run_id: str = "",
    source: str = "mcp",
) -> str:
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

            init_id = _send_rpc(
                proc,
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "devops-agent", "version": "1.0"},
                },
            )
            init_resp = _recv_response(proc, request_id=init_id)
            if "error" in init_resp:
                raise RuntimeError(init_resp["error"])
            server_info = init_resp.get("result", {}).get("serverInfo", {})
            server_name = server_info.get("name", name)

            _send_rpc(proc, "notifications/initialized", params=None, request_id=0)

            tools_id = _send_rpc(proc, "tools/list")
            tools_resp = _recv_response(proc, request_id=tools_id)
            if "error" in tools_resp:
                raise RuntimeError(tools_resp["error"])
            tools_list = tools_resp.get("result", {}).get("tools", [])
            tool_defs = [_tool_to_schema(t) for t in tools_list]

            client = MCPClient(name)
            _set_mcp_context(
                client,
                owner_id=owner_id,
                session_id=session_id,
                run_id=run_id,
                source=source,
            )
            handlers = {}
            for t in tools_list:
                handlers[t["name"]] = _make_stdio_handler(name, t["name"])

            client.register(tool_defs, handlers)
            mcp_clients[name] = client
            _stdio_mcp_sessions[name] = {
                "proc": proc,
                "server_name": server_name,
                "lock": threading.Lock(),
            }

            tool_names = [t["name"] for t in tools_list]
            return (
                f"Connected to standard MCP server '{name}' ({server_name}). "
                f"Discovered {len(tool_names)} tools: {', '.join(tool_names)}"
            )
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
                with session["lock"]:
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

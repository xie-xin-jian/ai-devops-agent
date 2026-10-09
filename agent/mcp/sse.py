"""MCP JSON-RPC over HTTP Server-Sent Events."""

from __future__ import annotations

import json
import threading
from urllib.parse import urljoin, urlparse

import requests

from agent.mcp.registry import MCPClient, _set_mcp_context, mcp_clients
from agent.mcp.stdio import _next_rpc_id, _tool_to_schema

_sse_mcp_sessions: dict[str, dict] = {}
_sse_mcp_lock = threading.Lock()


def _sse_listen_loop(session: dict, stop_event: threading.Event):
    """后台线程：持续读取 SSE 流，按 JSON-RPC id 分发响应。"""
    current_event = None
    data_lines = []
    try:
        for raw in session["response"].iter_lines(decode_unicode=True):
            if stop_event.is_set():
                break
            if raw is None:
                continue
            line = raw.strip()
            if not line:
                # 空行 = 事件边界
                if data_lines:
                    data = "\n".join(data_lines)
                    if current_event == "endpoint":
                        session["message_endpoint"] = data
                        session["endpoint_ready"].set()
                    else:
                        try:
                            msg = json.loads(data)
                            if "id" in msg:
                                req_id = msg["id"]
                                with session["lock"]:
                                    session["responses"][req_id] = msg
                                    waiter = session["waiters"].get(req_id)
                                    if waiter:
                                        waiter.set()
                        except json.JSONDecodeError:
                            pass
                    data_lines = []
                    current_event = None
                continue
            if line.startswith("event:"):
                current_event = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].lstrip())
    except Exception:
        pass


def _sse_post_rpc(
    session: dict,
    method: str,
    params: dict | None = None,
    request_id: int | None = None,
) -> int | None:
    """通过 HTTP POST 发送 JSON-RPC 请求到远程 SSE MCP 服务器。"""
    req = {"jsonrpc": "2.0", "method": method}
    if request_id != 0:
        req["id"] = request_id if request_id is not None else _next_rpc_id()
    if params is not None:
        req["params"] = params
    requests.post(session["message_url"], json=req, timeout=30)
    return req.get("id")


def _sse_recv_response(session: dict, req_id: int, timeout: float = 30.0) -> dict:
    """等待指定 id 的 JSON-RPC 响应（从 SSE 流接收）。"""
    import time

    end_time = time.time() + timeout
    waiter = threading.Event()
    with session["lock"]:
        if req_id in session["responses"]:
            return session["responses"].pop(req_id)
        session["waiters"][req_id] = waiter
    while time.time() < end_time:
        if waiter.wait(timeout=1.0):
            break
    with session["lock"]:
        if req_id in session["responses"]:
            return session["responses"].pop(req_id)
        session["waiters"].pop(req_id, None)
    raise TimeoutError(f"SSE MCP response timeout for request id={req_id}")


def _make_sse_handler(server_name: str, tool_name: str):
    """创建一个调用远程 SSE MCP 工具的 handler。"""

    def handler(**kwargs):
        session = _sse_mcp_sessions.get(server_name)
        if not session:
            return f"MCP error: SSE server '{server_name}' not connected"
        try:
            req_id = _sse_post_rpc(
                session, "tools/call", {"name": tool_name, "arguments": kwargs}
            )
            resp = _sse_recv_response(session, req_id)
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


def connect_sse_mcp(
    name: str,
    url: str,
    *,
    owner_id: str = "",
    session_id: str = "",
    run_id: str = "",
    source: str = "mcp",
) -> str:
    """通过 SSE 连接一个远程 MCP 服务器。

    Args:
        name: 服务器名称（唯一标识）
        url: SSE 端点地址，如 http://localhost:8080/sse

    Returns:
        连接结果消息
    """
    with _sse_mcp_lock:
        if name in mcp_clients:
            return f"MCP server '{name}' already connected"

        try:
            # 1. 建立 SSE 连接
            response = requests.get(
                url, stream=True, timeout=30, headers={"Accept": "text/event-stream"}
            )
            if response.status_code != 200:
                return (
                    f"Error connecting to SSE MCP '{name}': "
                    f"HTTP {response.status_code}"
                )

            # 解析 base_url 用于拼接消息端点
            parsed = urlparse(url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"

            session = {
                "url": url,
                "base_url": base_url,
                "response": response,
                "responses": {},
                "waiters": {},
                "lock": threading.Lock(),
                "endpoint_ready": threading.Event(),
                "stop_event": threading.Event(),
                "message_endpoint": None,
                "message_url": None,
            }

            # 2. 启动后台监听线程
            listener = threading.Thread(
                target=_sse_listen_loop,
                args=(session, session["stop_event"]),
                daemon=True,
                name=f"sse-mcp-{name}",
            )
            session["listener"] = listener
            listener.start()

            # 3. 等待 endpoint 事件
            if not session["endpoint_ready"].wait(timeout=10):
                session["stop_event"].set()
                response.close()
                return (
                    f"Error connecting to SSE MCP '{name}': " f"endpoint event timeout"
                )

            # 拼接消息端点完整 URL
            endpoint = session["message_endpoint"]
            if endpoint.startswith("http"):
                session["message_url"] = endpoint
            else:
                session["message_url"] = urljoin(base_url + "/", endpoint.lstrip("/"))

            # 4. initialize 握手
            req_id = _sse_post_rpc(
                session,
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "devops-agent", "version": "1.0"},
                },
            )
            init_resp = _sse_recv_response(session, req_id)
            server_info = init_resp.get("result", {}).get("serverInfo", {})
            server_name = server_info.get("name", name)

            # 5. notifications/initialized
            _sse_post_rpc(session, "notifications/initialized", request_id=0)

            # 6. tools/list
            req_id = _sse_post_rpc(session, "tools/list")
            tools_resp = _sse_recv_response(session, req_id)
            tools_list = tools_resp.get("result", {}).get("tools", [])
            tool_defs = [_tool_to_schema(t) for t in tools_list]

            # 7. 注册工具到工具池
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
                handlers[t["name"]] = _make_sse_handler(name, t["name"])

            client.register(tool_defs, handlers)
            mcp_clients[name] = client
            _sse_mcp_sessions[name] = session

            tool_names = [t["name"] for t in tools_list]
            return (
                f"Connected to SSE MCP server '{name}' ({server_name}). "
                f"Discovered {len(tool_names)} tools: {', '.join(tool_names)}"
            )
        except Exception as e:
            return f"Error connecting to SSE MCP server '{name}': {e}"


def disconnect_sse_mcp(name: str) -> str:
    """断开远程 SSE MCP 服务器连接。"""
    with _sse_mcp_lock:
        if name not in _sse_mcp_sessions:
            return f"SSE MCP server '{name}' not found"

        session = _sse_mcp_sessions.pop(name)
        session["stop_event"].set()

        response = session.get("response")
        if response:
            try:
                response.close()
            except Exception:
                pass

        mcp_clients.pop(name, None)
        return f"Disconnected SSE MCP server '{name}'"


def list_sse_mcp_servers() -> list[str]:
    """列出所有已连接的远程 SSE MCP 服务器名称。"""
    return list(_sse_mcp_sessions.keys())

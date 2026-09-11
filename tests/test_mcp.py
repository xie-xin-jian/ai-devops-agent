"""MCP stdio JSON-RPC 调用安全测试。"""

import io
import threading
import time
from types import SimpleNamespace

from agent import mcp


def test_recv_response_skips_unrelated_request_id():
    """接收端不应把其他请求的响应交给当前调用。"""
    proc = SimpleNamespace(
        stdout=io.StringIO(
            '{"jsonrpc":"2.0","id":2,"result":{"content":[]}}\n'
            '{"jsonrpc":"2.0","id":1,"result":{"content":[{"type":"text","text":"ok"}]}}\n'
        )
    )

    response = mcp._recv_response(proc, timeout=0.1, request_id=1)

    assert response["id"] == 1
    assert response["result"]["content"][0]["text"] == "ok"


def test_stdio_handler_serializes_send_and_receive(monkeypatch):
    """同一 stdio Server 的并发调用必须串行完成请求和响应。"""
    active = 0
    max_active = 0
    guard = threading.Lock()

    def fake_send(proc, method, params=None, request_id=None):
        nonlocal active, max_active
        with guard:
            active += 1
            max_active = max(max_active, active)
        return 1

    def fake_recv(proc, timeout=30.0, request_id=None):
        nonlocal active
        time.sleep(0.02)
        with guard:
            active -= 1
        return {
            "id": request_id,
            "result": {"content": [{"type": "text", "text": "ok"}]},
        }

    monkeypatch.setattr(mcp, "_send_rpc", fake_send)
    monkeypatch.setattr(mcp, "_recv_response", fake_recv)
    mcp._stdio_mcp_sessions["test"] = {
        "proc": object(),
        "server_name": "test",
        "lock": threading.Lock(),
    }
    try:
        handler = mcp._make_stdio_handler("test", "echo")
        threads = [
            threading.Thread(target=handler, kwargs={"value": index})
            for index in range(4)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
        assert all(not thread.is_alive() for thread in threads)
    finally:
        mcp._stdio_mcp_sessions.pop("test", None)

    assert max_active == 1


def test_stdio_handler_surfaces_json_rpc_error(monkeypatch):
    """服务端 JSON-RPC error 应直接返回给 Agent，而不是伪装成空结果。"""
    monkeypatch.setattr(mcp, "_send_rpc", lambda *args, **kwargs: 7)
    monkeypatch.setattr(
        mcp,
        "_recv_response",
        lambda *args, **kwargs: {"id": 7, "error": {"code": -32601, "message": "missing"}},
    )
    mcp._stdio_mcp_sessions["test"] = {
        "proc": object(),
        "server_name": "test",
        "lock": threading.Lock(),
    }
    try:
        result = mcp._make_stdio_handler("test", "missing")()
    finally:
        mcp._stdio_mcp_sessions.pop("test", None)

    assert "MCP error" in result
    assert "missing" in result

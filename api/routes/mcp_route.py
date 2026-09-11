"""MCP 管理 API 路由"""

from fastapi import APIRouter, HTTPException
from api.schemas import (
    MCPCustomServerRequest,
    MCPNameRequest,
    MCPSseConnectRequest,
    MCPStdioConnectRequest,
)
from agent.mcp import (
    connect_mcp,
    disconnect_mcp,
    list_connected_mcp,
    MOCK_SERVERS,
    assemble_tool_pool,
    register_custom_server,
    remove_custom_server,
    list_custom_servers,
    load_all_custom_servers,
    connect_stdio_mcp,
    disconnect_stdio_mcp,
    list_stdio_mcp_servers,
    connect_sse_mcp,
    disconnect_sse_mcp,
    list_sse_mcp_servers,
)

router = APIRouter()


@router.get("/")
async def list_mcp():
    """列出所有已连接的 MCP 服务器和可用服务器"""
    return {
        "connected": list_connected_mcp(),
        "available": list(MOCK_SERVERS.keys()),
        "custom": list_custom_servers(),
        "stdio_servers": list_stdio_mcp_servers(),
        "sse_servers": list_sse_mcp_servers(),
    }


@router.post("/connect")
async def connect(payload: MCPNameRequest):
    """连接一个内置 MCP 服务器（mock）"""
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    result = connect_mcp(name)
    if result.startswith("Unknown"):
        raise HTTPException(status_code=404, detail=result)
    return {"result": result, "connected": list_connected_mcp()}


@router.post("/disconnect")
async def disconnect(payload: MCPNameRequest):
    """断开一个 MCP 服务器"""
    name = payload.name.strip()
    result = disconnect_mcp(name)
    if result.endswith("not connected"):
        raise HTTPException(status_code=404, detail=result)
    return {"result": result, "connected": list_connected_mcp()}


@router.get("/tools")
async def mcp_tools():
    """列出所有已连接 MCP 服务器的工具"""
    from agent.tools import ALL_TOOL_SCHEMAS, ALL_TOOL_HANDLERS
    _, handlers = assemble_tool_pool(ALL_TOOL_SCHEMAS, ALL_TOOL_HANDLERS)
    mcp_tool_names = [n for n in handlers.keys() if n.startswith("mcp__")]
    return {"tools": mcp_tool_names}


# ============ 自定义服务器 ============

@router.get("/custom")
async def list_custom():
    """列出自定义服务器"""
    return {"servers": list_custom_servers()}


@router.post("/custom")
async def create_custom(payload: MCPCustomServerRequest):
    """注册自定义 MCP 服务器"""
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    result = register_custom_server(name, payload.description, payload.tools)
    if result.startswith("Cannot"):
        raise HTTPException(status_code=409, detail=result)
    return {"result": result, "servers": list_custom_servers()}


@router.delete("/custom/{name}")
async def delete_custom(name: str):
    """删除自定义 MCP 服务器"""
    result = remove_custom_server(name)
    if result.startswith("Cannot"):
        raise HTTPException(status_code=400, detail=result)
    if result.endswith("not found"):
        raise HTTPException(status_code=404, detail=result)
    return {"result": result, "servers": list_custom_servers()}


@router.post("/reload")
async def reload_custom():
    """重新加载所有自定义服务器配置"""
    load_all_custom_servers()
    return {"result": "reloaded", "connected": list_connected_mcp()}


# ============ 标准 MCP 服务器（stdio） ============

@router.post("/stdio/connect")
async def connect_stdio(payload: MCPStdioConnectRequest):
    """通过 stdio 连接一个标准的 MCP 服务器

    请求体示例:
    {
        "name": "alert_server",
        "command": "python",
        "args": ["mcp_servers/alert_server.py"],
        "cwd": "d:/ai_agent/ai-devops-agent"
    }
    """
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    result = connect_stdio_mcp(
        name,
        payload.command,
        payload.args,
        payload.cwd,
    )
    if result.startswith("Error"):
        raise HTTPException(status_code=400, detail=result)
    return {"result": result, "connected": list_connected_mcp()}


@router.post("/stdio/disconnect")
async def disconnect_stdio(payload: MCPNameRequest):
    """断开标准 MCP 服务器连接"""
    name = payload.name.strip()
    result = disconnect_stdio_mcp(name)
    if result.startswith("Standard MCP server"):
        raise HTTPException(status_code=404, detail=result)
    return {"result": result, "connected": list_connected_mcp()}


# ============ 远程 MCP 服务器（SSE） ============

@router.post("/sse/connect")
async def connect_sse(payload: MCPSseConnectRequest):
    """通过 SSE 连接一个远程 MCP 服务器

    请求体示例:
    {
        "name": "remote_mcp",
        "url": "http://localhost:8080/sse"
    }
    """
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    result = connect_sse_mcp(name, payload.url.strip())
    if result.startswith("Error"):
        raise HTTPException(status_code=400, detail=result)
    return {"result": result, "connected": list_connected_mcp()}


@router.post("/sse/disconnect")
async def disconnect_sse(payload: MCPNameRequest):
    """断开远程 SSE MCP 服务器连接"""
    name = payload.name.strip()
    result = disconnect_sse_mcp(name)
    if result.startswith("SSE MCP server"):
        raise HTTPException(status_code=404, detail=result)
    return {"result": result, "connected": list_connected_mcp()}

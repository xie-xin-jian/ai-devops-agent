"""FastAPI 入口 - DevOps Agent API"""

import sys
import uuid
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import json
from fastapi import Depends, FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from agent.comprehensive import ComprehensiveAgent
from agent.config import WORKDIR, ALLOWED_ORIGINS
from .auth import (
    BearerAuthMiddleware,
    get_request_principal,
    require_permissions,
)
from .schemas import CancelRequest, ChatRequest, SessionRequest
from agent.rbac import AGENT_CHAT, SESSION_MANAGE, Principal, system_admin_principal


@asynccontextmanager
async def lifespan(_app):
    """Start background services as soon as the API process starts."""
    _ensure_cron_started()
    yield


app = FastAPI(
    title="AI DevOps Agent API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(BearerAuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["session-id"],
)

# Session 管理：每个 session 拥有独立的 Agent 实例，避免多用户串话
_sessions: dict[str, dict] = {}
_SESSION_TTL = timedelta(hours=2)

# Cron 调度线程全局只启动一次，避免多 session 重复启动
_cron_started = False
_cron_start_lock = threading.Lock()


def _ensure_cron_started():
    """保证全局只启动一个 Cron 调度后台线程。"""
    global _cron_started
    if _cron_started:
        return
    with _cron_start_lock:
        if _cron_started:
            return
        from agent.cron import cron_scheduler_loop, load_durable_jobs
        load_durable_jobs()
        t = threading.Thread(target=cron_scheduler_loop, daemon=True)
        t.start()
        _cron_started = True


def _cleanup_expired_sessions():
    """清理超过 TTL 未使用的 session。"""
    now = datetime.now()
    expired = [sid for sid, data in _sessions.items()
               if now - data["last_used"] > _SESSION_TTL]
    for sid in expired:
        _sessions.pop(sid, None)


def get_or_create_session(
    session_id: str | None = None,
    principal: Principal | None = None,
) -> tuple[str, dict]:
    """获取或创建 session，返回 (session_id, session_state)。"""
    principal = principal or system_admin_principal()
    _ensure_cron_started()
    _cleanup_expired_sessions()
    if session_id and session_id in _sessions:
        session = _sessions[session_id]
        if (
            session.get("owner_id")
            and session["owner_id"] != principal.id
            and not principal.has(SESSION_MANAGE)
        ):
            raise HTTPException(
                status_code=403,
                detail="Session belongs to another user",
            )
        session["last_used"] = datetime.now()
        return session_id, session
    new_id = session_id or str(uuid.uuid4())
    from agent.mcp import load_all_custom_servers
    load_all_custom_servers()
    agent = ComprehensiveAgent(
        session_id=new_id,
        principal=principal,
    )
    session = {
        "agent": agent,
        "owner_id": principal.id,
        "last_used": datetime.now(),
        "cancel_event": threading.Event(),
        "run_lock": threading.Lock(),
    }
    _sessions[new_id] = session
    from agent.audit import record_event
    record_event(
        "session.created",
        "Agent session created",
        result="success",
        severity="info",
        actor=principal.id,
        session_id=new_id,
        correlation_id=new_id,
        payload={"roles": sorted(principal.roles)},
    )
    return new_id, session


def _run_agent_sync(session: dict, message: str) -> str:
    """Run one chat turn under the session's cancellation and concurrency guard."""
    with session["run_lock"]:
        session["cancel_event"].clear()
        return session["agent"].run(message, session["cancel_event"])


@app.get("/")
async def root():
    return {"message": "AI DevOps Agent", "workdir": str(WORKDIR)}


@app.get("/health")
async def health():
    return {"status": "ok", "workdir": str(WORKDIR)}


@app.get("/tools")
async def list_tools(
    _principal: Principal = Depends(require_permissions(AGENT_CHAT)),
):
    """列出所有可用工具（内置 + Agent 注册 + MCP），不依赖 session。"""
    from agent.mcp import get_mcp_tool_names
    from agent.tool_policy import get_policy_catalog
    builtin = [tool["name"] for tool in ComprehensiveAgent.get_tool_catalog()]
    names = builtin + get_mcp_tool_names()
    return {
        "tools": names,
        "policies": {
            policy["name"]: policy
            for policy in get_policy_catalog(names)
        },
    }


@app.get("/actions")
async def list_actions(
    _principal: Principal = Depends(require_permissions(AGENT_CHAT)),
):
    """List the deterministic action routes available to the Agent."""
    from agent.action_router import get_action_catalog
    return {"actions": get_action_catalog()}


@app.post("/api/chat/")
async def chat(
    payload: ChatRequest,
    principal: Principal = Depends(require_permissions(AGENT_CHAT)),
):
    try:
        sid, session = get_or_create_session(payload.session_id, principal)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if payload.reset:
        session["agent"].reset()
    response = await run_in_threadpool(_run_agent_sync, session, payload.message)
    return {"response": response, "session_id": sid}


@app.post("/api/chat/stream")
async def chat_stream(
    payload: ChatRequest,
    principal: Principal = Depends(require_permissions(AGENT_CHAT)),
):
    """SSE 流式对话接口。每 yield 一个事件就推送给前端。"""
    try:
        sid, session = get_or_create_session(payload.session_id, principal)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if payload.reset:
        session["agent"].reset()

    def event_generator():
        with session["run_lock"]:
            session["cancel_event"].clear()
            for event in session["agent"].run_stream(
                payload.message,
                session["cancel_event"],
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "session-id": sid,
        },
    )


@app.post("/api/chat/cancel", status_code=202)
async def cancel_chat(
    payload: CancelRequest,
    principal: Principal = Depends(get_request_principal),
):
    session = _sessions.get(payload.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if (
        session.get("owner_id")
        and session["owner_id"] != principal.id
        and not principal.has(SESSION_MANAGE)
    ):
        raise HTTPException(
            status_code=403,
            detail="Session belongs to another user",
        )
    session["cancel_event"].set()
    return {"status": "cancelling"}


@app.get("/api/messages/")
async def get_messages(
    session_id: str = "",
    principal: Principal = Depends(get_request_principal),
):
    if not session_id or session_id not in _sessions:
        return {"messages": []}
    from agent.messages import serialize_visible_messages
    session = _sessions[session_id]
    if (
        session.get("owner_id")
        and session["owner_id"] != principal.id
        and not principal.has(SESSION_MANAGE)
    ):
        raise HTTPException(
            status_code=403,
            detail="Session belongs to another user",
        )
    session["last_used"] = datetime.now()
    agent = session["agent"]
    return {"messages": serialize_visible_messages(agent.get_messages())}


@app.get("/api/chat/sessions")
async def list_chat_sessions(
    principal: Principal = Depends(get_request_principal),
):
    from agent.messages import serialize_visible_messages

    sessions = []
    for sid, session in _sessions.items():
        if (
            session.get("owner_id")
            and session["owner_id"] != principal.id
            and not principal.has(SESSION_MANAGE)
        ):
            continue
        agent = session["agent"]
        visible = serialize_visible_messages(agent.get_messages())
        first_user = next(
            (
                item.get("content", "")
                for item in visible
                if item.get("role") == "user"
            ),
            "",
        )
        sessions.append({
            "id": sid,
            "title": first_user[:32] or "新对话",
            "updated_at": session["last_used"].timestamp(),
            "message_count": len(visible),
        })
    sessions.sort(
        key=lambda item: item["updated_at"],
        reverse=True,
    )
    return {"sessions": sessions}


@app.post("/api/reset/")
async def reset(
    payload: SessionRequest | None = None,
    principal: Principal = Depends(get_request_principal),
):
    session_id = payload.session_id if payload else None
    if session_id and session_id in _sessions:
        session = _sessions[session_id]
        if (
            session.get("owner_id")
            and session["owner_id"] != principal.id
            and not principal.has(SESSION_MANAGE)
        ):
            raise HTTPException(
                status_code=403,
                detail="Session belongs to another user",
            )
        session["agent"].reset()
        from agent.audit import record_event
        record_event(
            "session.reset",
            "Agent session reset",
            result="success",
            severity="info",
            actor=principal.id,
            session_id=session_id,
            correlation_id=session_id,
        )
    return {"status": "reset"}


from .routes.task import router as task_router
from .routes.cron_route import router as cron_router
from .routes.mcp_route import router as mcp_router
from .routes.skill_route import router as skill_router
from .routes.action_route import router as action_router
from .routes.audit_route import router as audit_router
from .routes.rbac_route import router as rbac_router
from .routes.memory_route import router as memory_router
from .routes.run_route import router as run_router
from .routes.sandbox_route import router as sandbox_router

app.include_router(task_router, prefix="/api/tasks", tags=["tasks"])
app.include_router(cron_router, prefix="/api/cron", tags=["cron"])
app.include_router(mcp_router, prefix="/api/mcp", tags=["mcp"])
app.include_router(skill_router)
app.include_router(action_router, prefix="/api/actions", tags=["actions"])
app.include_router(audit_router, prefix="/api/audit", tags=["audit"])
app.include_router(rbac_router, prefix="/api/rbac", tags=["rbac"])
app.include_router(memory_router, prefix="/api/memory", tags=["memory"])
app.include_router(run_router, prefix="/api/runs", tags=["runs"])
app.include_router(sandbox_router, prefix="/api/sandboxes", tags=["sandboxes"])

# 挂载前端静态文件
from fastapi.staticfiles import StaticFiles
_static_dir = Path(__file__).parent.parent / "static"
if _static_dir.exists():
    app.mount("/ui", StaticFiles(directory=str(_static_dir), html=True), name="ui")

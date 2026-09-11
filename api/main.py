"""FastAPI 入口 - DevOps Agent API"""

import sys
import uuid
import threading
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import json
from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from agent.comprehensive import ComprehensiveAgent
from agent.config import WORKDIR, ALLOWED_ORIGINS
from .schemas import CancelRequest, ChatRequest, SessionRequest

app = FastAPI(title="AI DevOps Agent API", version="1.0.0")

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


def get_or_create_session(session_id: str | None = None) -> tuple[str, dict]:
    """获取或创建 session，返回 (session_id, session_state)。"""
    _ensure_cron_started()
    _cleanup_expired_sessions()
    if session_id and session_id in _sessions:
        _sessions[session_id]["last_used"] = datetime.now()
        return session_id, _sessions[session_id]
    new_id = session_id or str(uuid.uuid4())
    from agent.mcp import load_all_custom_servers
    load_all_custom_servers()
    agent = ComprehensiveAgent()
    session = {
        "agent": agent,
        "last_used": datetime.now(),
        "cancel_event": threading.Event(),
        "run_lock": threading.Lock(),
    }
    _sessions[new_id] = session
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
async def list_tools():
    """列出所有可用工具（内置 + Agent 注册 + MCP），不依赖 session。"""
    from agent.tools import ALL_TOOL_SCHEMAS
    from agent.mcp import get_mcp_tool_names
    builtin = [t["name"] for t in ALL_TOOL_SCHEMAS]
    extra = ["todo_write", "create_task", "list_tasks", "get_task", "claim_task",
             "complete_task", "list_skills", "load_skill", "spawn_subagent",
             "compact", "schedule_cron", "list_crons", "cancel_cron", "connect_mcp"]
    return {"tools": builtin + extra + get_mcp_tool_names()}


@app.post("/api/chat/")
async def chat(payload: ChatRequest):
    sid, session = get_or_create_session(payload.session_id)
    if payload.reset:
        session["agent"].reset()
    response = await run_in_threadpool(_run_agent_sync, session, payload.message)
    return {"response": response, "session_id": sid}


@app.post("/api/chat/stream")
async def chat_stream(payload: ChatRequest):
    """SSE 流式对话接口。每 yield 一个事件就推送给前端。"""
    sid, session = get_or_create_session(payload.session_id)
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
async def cancel_chat(payload: CancelRequest):
    session = _sessions.get(payload.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    session["cancel_event"].set()
    return {"status": "cancelling"}


@app.get("/api/messages/")
async def get_messages(session_id: str = ""):
    if not session_id or session_id not in _sessions:
        return {"messages": []}
    from agent.messages import serialize_visible_messages
    session = _sessions[session_id]
    session["last_used"] = datetime.now()
    agent = session["agent"]
    return {"messages": serialize_visible_messages(agent.get_messages())}


@app.post("/api/reset/")
async def reset(payload: SessionRequest | None = None):
    session_id = payload.session_id if payload else None
    if session_id and session_id in _sessions:
        _sessions[session_id]["agent"].reset()
    return {"status": "reset"}


from .routes.task import router as task_router
from .routes.cron_route import router as cron_router
from .routes.mcp_route import router as mcp_router
from .routes.skill_route import router as skill_router

app.include_router(task_router, prefix="/api/tasks", tags=["tasks"])
app.include_router(cron_router, prefix="/api/cron", tags=["cron"])
app.include_router(mcp_router, prefix="/api/mcp", tags=["mcp"])
app.include_router(skill_router)

# 挂载前端静态文件
from fastapi.staticfiles import StaticFiles
_static_dir = Path(__file__).parent.parent / "static"
if _static_dir.exists():
    app.mount("/ui", StaticFiles(directory=str(_static_dir), html=True), name="ui")

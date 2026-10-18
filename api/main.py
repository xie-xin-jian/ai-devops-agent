"""FastAPI 入口 - DevOps Agent API"""

import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import json
from fastapi import Depends, FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from agent.core.comprehensive import ComprehensiveAgent
from agent.observability.logger import logger
from agent.platform.config import WORKDIR, ALLOWED_ORIGINS
from agent.sessions.manager import (
    SessionAccessError,
    SessionManager,
)
from agent.sessions.state_store import RecoveryStore
from .auth import (
    BearerAuthMiddleware,
    get_request_principal,
    require_permissions,
)
from .schemas import (
    CancelRequest,
    ChatRequest,
    SessionRenameRequest,
    SessionRequest,
)
from agent.platform.identity import AGENT_CHAT, Principal, system_admin_principal
from .routes.task import router as task_router
from .routes.cron_route import router as cron_router
from .routes.mcp_route import router as mcp_router
from .routes.skill_route import router as skill_router
from .routes.action_route import router as action_router
from .routes.audit_route import router as audit_router
from .routes.memory_route import router as memory_router
from .routes.recovery_route import router as recovery_router
from .routes.sandbox_route import router as sandbox_router
from .routes.target_route import router as target_router


@asynccontextmanager
async def lifespan(_app):
    """Start background services as soon as the API process starts."""
    _recover_startup_state()
    _ensure_cron_started()
    _start_persistence_watcher()
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

_session_manager = SessionManager()

# Cron 调度线程全局只启动一次，避免多 session 重复启动
_cron_started = False
_cron_start_lock = threading.Lock()


def _recover_startup_state():
    """Reconcile durable state after an unclean process restart."""
    from agent.observability.audit import record_event
    from agent.orchestration.background import recover_interrupted_background_tasks
    from agent.orchestration.pending_actions import PendingActionStore
    from agent.sandbox.manager import cleanup_orphan_sandboxes

    reason = "process restarted while the operation was still running"
    store = RecoveryStore()
    for run in store.interrupt_stale_runs(reason):
        record_event(
            "run.interrupted",
            f"Run interrupted: {run.get('run_id', '')}",
            summary=reason,
            result="failed",
            severity="high",
            actor=str(run.get("owner_id") or "system"),
            session_id=str(run.get("session_id") or ""),
            run_id=str(run.get("run_id") or ""),
            correlation_id=str(run.get("run_id") or ""),
            payload={
                "phase": run.get("phase", ""),
                "active_tool": run.get("active_tool", ""),
                "safe_to_resume": bool(run.get("safe_to_resume")),
                "reason": reason,
            },
        )

    recover_interrupted_background_tasks(reason)

    action_store = PendingActionStore()
    for action in action_store.recover_interrupted(reason):
        record_event(
            "pending_action.interrupted",
            f"Pending action interrupted: {action.id}",
            summary=reason,
            result="failed",
            severity="high",
            actor="system",
            session_id=action.session_id,
            action_id=action.id,
            action_code=action.action_code,
            correlation_id=action.id,
            payload={"reason": reason},
        )

    cleanup = cleanup_orphan_sandboxes()
    if (
        cleanup["workspaces_removed"]
        or cleanup["errors"]
    ):
        record_event(
            "recovery.orphans_cleaned",
            "Recovered orphaned Sandbox workspaces",
            result="failed" if cleanup["errors"] else "success",
            severity="high" if cleanup["errors"] else "info",
            actor="system",
            correlation_id="startup-recovery",
            payload=cleanup,
        )


def _ensure_cron_started():
    """保证全局只启动一个 Cron 调度后台线程。"""
    global _cron_started
    if _cron_started:
        return
    with _cron_start_lock:
        if _cron_started:
            return
        from agent.orchestration.cron import cron_scheduler_loop, load_durable_jobs
        load_durable_jobs()
        t = threading.Thread(target=cron_scheduler_loop, daemon=True)
        t.start()
        _cron_started = True


def _start_persistence_watcher() -> None:
    """Start the JSON-vs-PostgreSQL drift checker when the mirror is on."""
    try:
        from agent.persistence.consistency import start_consistency_watcher

        start_consistency_watcher()
    except Exception:
        logger.exception("Failed to start persistence consistency watcher")


def get_or_create_session(
    session_id: str | None = None,
    principal: Principal | None = None,
) -> tuple[str, dict]:
    """获取或创建 session，返回 (session_id, session_state)。"""
    principal = principal or system_admin_principal()
    _ensure_cron_started()
    try:
        return _session_manager.get_or_create(
            session_id,
            principal,
        )
    except SessionAccessError as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        ) from exc


def _run_agent_sync(session: dict, message: str) -> str:
    """Run one chat turn under the session's cancellation and concurrency guard."""
    return _session_manager.run_sync(session, message)


@app.get("/")
async def root():
    return {"message": "AI DevOps Agent", "workdir": str(WORKDIR)}


@app.get("/health")
async def health():
    from agent.persistence.routing import read_status
    from agent.persistence.writer import mirror_stats, persistence_status

    return {
        "status": "ok",
        "workdir": str(WORKDIR),
        "persistence": {
            **persistence_status(),
            "mirror": mirror_stats(),
            **read_status(),
        },
    }


@app.get("/tools")
async def list_tools(
    _principal: Principal = Depends(require_permissions(AGENT_CHAT)),
):
    """列出所有可用工具（内置 + Agent 注册 + MCP），不依赖 session。"""
    from agent.mcp.client import get_mcp_tool_names
    from agent.tools.policy import get_tool_policy

    registry = ComprehensiveAgent.get_tool_registry()
    mcp_names = get_mcp_tool_names()
    names = registry.names() + mcp_names
    policies = {
        policy.name: policy.to_dict()
        for policy in registry.policies()
    }
    policies.update({
        name: get_tool_policy(name).to_dict()
        for name in mcp_names
    })
    return {
        "tools": names,
        "policies": policies,
    }


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
    if payload.target_id:
        from agent.targets.store import TargetStore

        if TargetStore().get(payload.target_id) is None:
            raise HTTPException(status_code=404, detail="Target not found")
        _session_manager.activate_target(sid, payload.target_id, principal)
    elif session["agent"].target_id:
        _session_manager.activate_target(sid, "", principal)
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
    if payload.target_id:
        from agent.targets.store import TargetStore

        if TargetStore().get(payload.target_id) is None:
            raise HTTPException(status_code=404, detail="Target not found")
        _session_manager.activate_target(sid, payload.target_id, principal)
    elif session["agent"].target_id:
        _session_manager.activate_target(sid, "", principal)

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
    try:
        _session_manager.cancel(payload.session_id, principal)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="Session not found",
        ) from exc
    except SessionAccessError as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        ) from exc
    return {"status": "cancelling"}


@app.get("/api/messages/")
async def get_messages(
    session_id: str = "",
    principal: Principal = Depends(get_request_principal),
):
    if not session_id:
        return {"messages": []}
    from agent.sessions.messages import serialize_visible_messages
    if not _session_manager.exists(session_id):
        return {"messages": []}
    _, session = get_or_create_session(session_id, principal)
    agent = session["agent"]
    return {"messages": serialize_visible_messages(agent.get_messages())}


@app.get("/api/chat/sessions")
async def list_chat_sessions(
    principal: Principal = Depends(get_request_principal),
):
    return {
        "sessions": _session_manager.list_sessions(principal)
    }


@app.post("/api/chat/sessions/{session_id}/rename")
async def rename_chat_session(
    session_id: str,
    payload: SessionRenameRequest,
    principal: Principal = Depends(get_request_principal),
):
    try:
        return _session_manager.rename_session(
            session_id,
            payload.title,
            principal,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")
    except SessionAccessError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/reset/")
async def reset(
    payload: SessionRequest | None = None,
    principal: Principal = Depends(get_request_principal),
):
    session_id = payload.session_id if payload else None
    if not session_id:
        return {"status": "reset"}
    try:
        _session_manager.reset(session_id, principal)
    except SessionAccessError as exc:
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        ) from exc
    return {"status": "reset"}


app.include_router(task_router, prefix="/api/tasks", tags=["tasks"])
app.include_router(cron_router, prefix="/api/cron", tags=["cron"])
app.include_router(mcp_router, prefix="/api/mcp", tags=["mcp"])
app.include_router(skill_router)
app.include_router(action_router, prefix="/api/actions", tags=["actions"])
app.include_router(audit_router, prefix="/api/audit", tags=["audit"])
app.include_router(memory_router, prefix="/api/memory", tags=["memory"])
app.include_router(
    recovery_router,
    prefix="/api/recovery",
    tags=["recovery"],
)
app.include_router(sandbox_router, prefix="/api/sandboxes", tags=["sandboxes"])
app.include_router(target_router, prefix="/api/targets", tags=["targets"])

# 挂载前端静态文件
_static_dir = Path(__file__).parent.parent / "static"
if _static_dir.exists():
    app.mount("/ui", StaticFiles(directory=str(_static_dir), html=True), name="ui")

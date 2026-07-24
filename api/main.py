"""FastAPI 入口 - DevOps Agent API"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent.comprehensive import ComprehensiveAgent
from agent.config import WORKDIR

app = FastAPI(title="AI DevOps Agent API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_agent_instance: ComprehensiveAgent | None = None


def get_agent() -> ComprehensiveAgent:
    global _agent_instance
    if _agent_instance is None:
        # 启动时加载持久化的自定义 MCP 服务器
        from agent.mcp import load_all_custom_servers
        load_all_custom_servers()
        _agent_instance = ComprehensiveAgent()
    return _agent_instance


@app.get("/")
async def root():
    return {"message": "AI DevOps Agent", "workdir": str(WORKDIR)}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/tools")
async def list_tools():
    agent = get_agent()
    return {"tools": [t["name"] for t in agent.tools]}


@app.post("/api/chat/")
async def chat(payload: dict):
    agent = get_agent()
    message = payload.get("message", "")
    reset = payload.get("reset", False)
    if reset:
        agent.reset()
    if not message:
        return {"error": "message is required"}
    response = await agent.run(message)
    return {"response": response}


@app.get("/api/messages/")
async def get_messages():
    agent = get_agent()
    msgs = []
    for msg in agent.get_messages():
        msgs.append({"role": msg["role"]})
    return {"messages": msgs}


@app.post("/api/reset/")
async def reset():
    agent = get_agent()
    agent.reset()
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
from pathlib import Path
_static_dir = Path(__file__).parent.parent / "static"
if _static_dir.exists():
    app.mount("/ui", StaticFiles(directory=str(_static_dir), html=True), name="ui")

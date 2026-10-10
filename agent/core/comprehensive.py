"""
综合 Agent —— 所有运维机制组装在一个 loop 里。

将以下机制整合到同一个 agent loop 中，面向 DevOps 场景：
- 工具分发 (tool dispatch)
- 权限系统 (permission)
- 待办规划 (todo)
- 子 agent (subagent)
- 技能加载 (skills)
- 上下文压缩 (context compaction)
- 记忆系统 (memory)
- 系统提示组装 (prompt assembly)
- 错误恢复 (error recovery)
- 任务图 (task graph)
- 后台任务 (background tasks)
- 定时调度 (cron)

采用模块化拆分，可通过类实例化配置，便于多会话隔离与扩展。
"""

from anthropic import Anthropic

from agent.platform.config import (
    WORKDIR,
    MODEL_ID,
    ANTHROPIC_BASE_URL,
    API_KEY,
    MEMORY_SCOPE,
)
from agent.core.agent_runtime import AgentRuntimeMixin
from agent.tools.business import BusinessToolsMixin
from agent.core.context_manager import ContextManagerMixin

from agent.core.error_recovery import (
    RecoveryState,
)
from agent.memory.service import MemorySystem
from agent.tools.policy import (
    ToolPolicyContext,
)
from agent.tools.executor import ToolExecutor
from agent.tools.registry import ToolRegistry
from agent.orchestration.pending_actions import PendingActionStore
from agent.sessions.state_store import (
    RecoveryStore,
)
from agent.observability.audit import (
    record_event,
)
from agent.platform.identity import MEMORY_MANAGE, Principal, system_admin_principal
from agent.sandbox.manager import SandboxManager
from agent.targets.store import TargetStore


class ComprehensiveAgent(
    BusinessToolsMixin,
    ContextManagerMixin,
    AgentRuntimeMixin,
):
    """综合 Agent —— 所有 harness 机制在一个 loop 里。"""

    @classmethod
    def get_tool_registry(cls) -> ToolRegistry:
        """Build the full registry without requiring an API key."""
        catalog = object.__new__(cls)
        catalog.tool_registry = ToolRegistry.builtin()
        catalog._register_default_tools()
        return catalog.tool_registry

    @classmethod
    def get_tool_catalog(cls) -> list[dict]:
        """Build the complete tool schema list without requiring an API key."""
        return cls.get_tool_registry().schemas()

    def __init__(
        self,
        system_prompt: str = None,
        api_key: str = None,
        memory_scope: str | None = None,
        tool_context: ToolPolicyContext | None = None,
        session_id: str = "",
        target_id: str = "",
        principal: Principal | None = None,
    ):
        base_url = ANTHROPIC_BASE_URL if ANTHROPIC_BASE_URL else None
        key = api_key or API_KEY
        if not key:
            raise ValueError(
                "API Key not found. Set ANTHROPIC_API_KEY or API_KEY in .env file."
            )
        kwargs = {"api_key": key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = Anthropic(**kwargs)
        self.model = MODEL_ID
        self.recovery = RecoveryState()
        self.memory = MemorySystem()
        self.principal = principal or system_admin_principal()
        requested_memory_scope = (memory_scope or MEMORY_SCOPE).strip() or "global"
        if memory_scope is None and not self.principal.has(MEMORY_MANAGE):
            requested_memory_scope = f"user:{self.principal.id}"
        self.memory_scope = requested_memory_scope
        self.tool_context = tool_context or self.principal.to_tool_policy_context()
        self.session_id = session_id
        self.target_id = str(target_id or "")
        self.audit_enabled = bool(session_id)
        self.current_run_id = ""
        self.pending_action_store = PendingActionStore()
        self.state_store = RecoveryStore()
        self.sandbox_manager = SandboxManager()
        self._last_user_query = ""
        self.messages: list = []
        self._pending_compaction = False
        self._register_default_tools()
        self.tool_executor = ToolExecutor(
            self.tool_registry,
            sandbox_manager=self.sandbox_manager,
            sandbox_source=str(WORKDIR),
            principal=self.principal,
            tool_context=self.tool_context,
            audit=self._audit,
            target_id=self.target_id,
        )
        self.system_prompt = system_prompt or self._build_system_prompt()

    @property
    def target(self):
        if not self.target_id:
            return None
        return TargetStore().get(self.target_id)

    def _audit(self, event_type: str, title: str, **kwargs):
        if not getattr(self, "audit_enabled", False):
            return None
        kwargs.setdefault("session_id", getattr(self, "session_id", ""))
        kwargs.setdefault("run_id", getattr(self, "current_run_id", ""))
        return record_event(event_type, title, **kwargs)

    @property
    def tools(self) -> list[dict]:
        return self.tool_registry.schemas()

    @property
    def handlers(self) -> dict:
        return self.tool_registry.handlers()

    def get_messages(self) -> list:
        return list(self.messages)

    def reset(self):
        self.messages = []
        self._pending_compaction = False
        self.recovery = RecoveryState()
        self.current_run_id = ""
        self._current_turn = 0
        store = getattr(self, "state_store", None)
        session_id = getattr(self, "session_id", "")
        if store is not None and session_id:
            store.reset_session(session_id)

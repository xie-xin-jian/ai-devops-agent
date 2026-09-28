"""Deterministic action routing for the DevOps Agent.

The model still decides how to solve a task, but the platform narrows the
task into a known action before the model sees the tool catalog. This keeps
tool access scoped to the current intent and gives approval/audit layers a
stable action code to attach to.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.tool_policy import (
    HIGH,
    LOW,
    MEDIUM,
    READ_ONLY,
    ToolPolicyContext,
    evaluate_tool_policy,
)


DIRECT = "direct"
REACT = "react"
PLAN_REACT = "plan_react"
VALID_AGENT_MODES = {DIRECT, REACT, PLAN_REACT}


@dataclass(frozen=True)
class PreflightField:
    name: str
    label: str
    required: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "required": self.required,
        }


@dataclass(frozen=True)
class ActionDefinition:
    code: str
    display_name: str
    category: str
    description: str
    risk_level: str
    agent_mode: str
    allowed_tools: tuple[str, ...]
    preflight_required: bool = False
    preflight_fields: tuple[PreflightField, ...] = ()
    output_blocks: tuple[str, ...] = ()
    rbac_permissions: tuple[str, ...] = ()

    @property
    def requires_approval(self) -> bool:
        return self.risk_level in {MEDIUM, HIGH}

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "display_name": self.display_name,
            "category": self.category,
            "description": self.description,
            "risk_level": self.risk_level,
            "agent_mode": self.agent_mode,
            "allowed_tools": list(self.allowed_tools),
            "preflight_required": self.preflight_required,
            "preflight_fields": [
                item.to_dict()
                for item in self.preflight_fields
            ],
            "output_blocks": list(self.output_blocks),
            "rbac_permissions": list(self.rbac_permissions),
            "requires_approval": self.requires_approval,
        }


@dataclass(frozen=True)
class ActionRule:
    code: str
    keyword_groups: tuple[tuple[str, ...], ...]
    excluded_keywords: tuple[str, ...] = ()

    def matches(self, message: str) -> bool:
        text = str(message or "").strip().lower()
        if not text:
            return False
        if any(keyword in text for keyword in self.excluded_keywords):
            return False
        return all(
            any(keyword.lower() in text for keyword in group)
            for group in self.keyword_groups
        )


GENERAL_READ_TOOLS = (
    "read_file",
    "glob",
    "service_status",
    "disk_usage",
    "system_info",
    "memory_usage",
    "cpu_usage",
    "process_top",
    "process_search",
    "network_interfaces",
    "port_listen",
    "ping_host",
    "disk_io",
    "system_logs",
    "todo_write",
    "list_tasks",
    "get_task",
    "list_skills",
    "load_skill",
    "search_memory",
    "compact",
    "list_crons",
    "list_cron_logs",
    "list_background_tasks",
)

MEMORY_READ_TOOLS = ("search_memory", "load_skill", "todo_write", "compact")
MEMORY_WRITE_TOOLS = (
    "search_memory",
    "add_memory",
    "update_memory",
    "archive_memory",
    "delete_memory",
    "restore_memory",
    "approve_memory",
    "propose_action",
    "todo_write",
    "compact",
)
FILE_READ_TOOLS = (
    "read_file",
    "glob",
    "search_memory",
    "load_skill",
    "todo_write",
    "compact",
)
FILE_WRITE_TOOLS = (
    "read_file",
    "glob",
    "write_file",
    "edit_file",
    "propose_action",
    "todo_write",
    "compact",
)
COMMAND_TOOLS = (
    "bash",
    "read_file",
    "glob",
    "write_file",
    "edit_file",
    "list_background_tasks",
    "propose_action",
    "todo_write",
    "compact",
)
SYSTEM_INSPECT_TOOLS = (
    "service_status",
    "disk_usage",
    "system_info",
    "memory_usage",
    "cpu_usage",
    "process_top",
    "process_search",
    "network_interfaces",
    "port_listen",
    "ping_host",
    "disk_io",
    "system_logs",
    "search_memory",
    "load_skill",
    "todo_write",
    "compact",
)
NETWORK_INSPECT_TOOLS = (
    "network_interfaces",
    "port_listen",
    "ping_host",
    "system_logs",
    "process_search",
    "read_file",
    "search_memory",
    "load_skill",
    "todo_write",
    "compact",
)
TASK_TOOLS = (
    "create_task",
    "list_tasks",
    "get_task",
    "claim_task",
    "complete_task",
    "todo_write",
    "compact",
)
CRON_TOOLS = (
    "schedule_cron",
    "list_crons",
    "cancel_cron",
    "list_cron_logs",
    "propose_action",
    "todo_write",
    "compact",
)
MCP_TOOLS = (
    "connect_mcp",
    "list_skills",
    "load_skill",
    "propose_action",
    "todo_write",
    "compact",
)
BACKGROUND_TOOLS = (
    "list_background_tasks",
    "read_file",
    "glob",
    "todo_write",
    "compact",
)


ACTION_DEFINITIONS = {
    "general.chat": ActionDefinition(
        code="general.chat",
        display_name="通用只读问答",
        category="通用",
        description="基于现有只读上下文回答问题，不修改系统或长期数据。",
        risk_level=READ_ONLY,
        agent_mode=DIRECT,
        allowed_tools=GENERAL_READ_TOOLS,
        output_blocks=("answer",),
        rbac_permissions=("agent.chat",),
    ),
    "system.inspect": ActionDefinition(
        code="system.inspect",
        display_name="系统巡检",
        category="巡检",
        description="检查服务器资源、服务、进程、磁盘和系统日志。",
        risk_level=READ_ONLY,
        agent_mode=REACT,
        allowed_tools=SYSTEM_INSPECT_TOOLS,
        output_blocks=("inspection_summary", "evidence_timeline"),
        rbac_permissions=("agent.chat", "ops.read"),
    ),
    "service.diagnose": ActionDefinition(
        code="service.diagnose",
        display_name="服务故障诊断",
        category="故障排查",
        description="围绕 systemd 服务、进程和日志定位服务异常。",
        risk_level=READ_ONLY,
        agent_mode=REACT,
        allowed_tools=SYSTEM_INSPECT_TOOLS,
        output_blocks=("incident_card", "evidence_timeline", "next_action"),
        rbac_permissions=("agent.chat", "ops.read"),
    ),
    "network.diagnose": ActionDefinition(
        code="network.diagnose",
        display_name="网络诊断",
        category="故障排查",
        description="检查网络接口、监听端口、连通性和相关日志。",
        risk_level=READ_ONLY,
        agent_mode=REACT,
        allowed_tools=NETWORK_INSPECT_TOOLS,
        output_blocks=("incident_card", "evidence_timeline", "next_action"),
        rbac_permissions=("agent.chat", "ops.read"),
    ),
    "file.read": ActionDefinition(
        code="file.read",
        display_name="文件读取",
        category="文件",
        description="读取、搜索和总结工作区文件。",
        risk_level=READ_ONLY,
        agent_mode=REACT,
        allowed_tools=FILE_READ_TOOLS,
        output_blocks=("file_summary", "evidence_timeline"),
        rbac_permissions=("agent.chat", "filesystem.read"),
    ),
    "file.change": ActionDefinition(
        code="file.change",
        display_name="文件修改",
        category="文件",
        description="创建工作区文件或修改已有代码、配置和脚本。",
        risk_level=MEDIUM,
        agent_mode=PLAN_REACT,
        allowed_tools=FILE_WRITE_TOOLS,
        preflight_required=True,
        preflight_fields=(
            PreflightField("target_path", "目标文件", True),
            PreflightField("change_summary", "修改内容", True),
            PreflightField("rollback_plan", "回滚方案", False),
        ),
        output_blocks=("change_plan", "tool_trace", "risk_notice"),
        rbac_permissions=("agent.chat", "filesystem.write"),
    ),
    "command.execute": ActionDefinition(
        code="command.execute",
        display_name="命令执行",
        category="执行",
        description="执行安装、部署、重启、清理或其他 shell 操作。",
        risk_level=HIGH,
        agent_mode=PLAN_REACT,
        allowed_tools=COMMAND_TOOLS,
        preflight_required=True,
        preflight_fields=(
            PreflightField("target", "目标主机或目录", True),
            PreflightField("command", "执行命令", True),
            PreflightField("impact", "影响范围", True),
            PreflightField("rollback_plan", "回滚方案", True),
            PreflightField("verification", "验证方式", True),
        ),
        output_blocks=("command_plan", "approval_form", "risk_notice"),
        rbac_permissions=("agent.chat", "shell.execute"),
    ),
    "memory.recall": ActionDefinition(
        code="memory.recall",
        display_name="记忆检索",
        category="Memory",
        description="检索与当前任务相关的长期记忆。",
        risk_level=READ_ONLY,
        agent_mode=REACT,
        allowed_tools=MEMORY_READ_TOOLS,
        output_blocks=("memory_evidence", "answer"),
        rbac_permissions=("agent.chat", "memory.read"),
    ),
    "memory.manage": ActionDefinition(
        code="memory.manage",
        display_name="记忆管理",
        category="Memory",
        description="新增、更新、归档、删除或恢复长期记忆。",
        risk_level=MEDIUM,
        agent_mode=PLAN_REACT,
        allowed_tools=MEMORY_WRITE_TOOLS,
        preflight_required=True,
        preflight_fields=(
            PreflightField("scope", "记忆作用域", True),
            PreflightField("content", "记忆内容", True),
            PreflightField("reason", "写入或变更原因", False),
        ),
        output_blocks=("memory_change_plan", "approval_form", "audit_ref"),
        rbac_permissions=("agent.chat", "memory.write"),
    ),
    "task.manage": ActionDefinition(
        code="task.manage",
        display_name="任务管理",
        category="任务",
        description="创建、查看、认领和完成内部任务图节点。",
        risk_level=LOW,
        agent_mode=REACT,
        allowed_tools=TASK_TOOLS,
        output_blocks=("task_summary", "tool_trace"),
        rbac_permissions=("agent.chat", "task.read"),
    ),
    "automation.schedule": ActionDefinition(
        code="automation.schedule",
        display_name="定时调度",
        category="自动化",
        description="创建、查看和取消 Cron 定时任务。",
        risk_level=HIGH,
        agent_mode=PLAN_REACT,
        allowed_tools=CRON_TOOLS,
        preflight_required=True,
        preflight_fields=(
            PreflightField("cron", "执行频率", True),
            PreflightField("prompt", "执行内容", True),
            PreflightField("scope", "影响范围", True),
        ),
        output_blocks=("schedule_plan", "approval_form", "risk_notice"),
        rbac_permissions=("agent.chat", "cron.write"),
    ),
    "background.monitor": ActionDefinition(
        code="background.monitor",
        display_name="后台任务查看",
        category="自动化",
        description="查看后台执行状态和已捕获输出。",
        risk_level=READ_ONLY,
        agent_mode=REACT,
        allowed_tools=BACKGROUND_TOOLS,
        output_blocks=("background_summary", "tool_trace"),
        rbac_permissions=("agent.chat", "background.read"),
    ),
    "mcp.connect": ActionDefinition(
        code="mcp.connect",
        display_name="MCP 工具连接",
        category="MCP",
        description="连接外部 MCP 服务并发现其工具。",
        risk_level=MEDIUM,
        agent_mode=PLAN_REACT,
        allowed_tools=MCP_TOOLS,
        preflight_required=True,
        preflight_fields=(
            PreflightField("server", "MCP 服务", True),
            PreflightField("purpose", "连接目的", False),
        ),
        output_blocks=("mcp_connection", "tool_trace", "risk_notice"),
        rbac_permissions=("agent.chat", "mcp.connect"),
    ),
}


ACTION_RULES = (
    ActionRule(
        "automation.schedule",
        keyword_groups=(
            (
                "定时",
                "计划任务",
                "每天",
                "每小时",
                "每周",
                "周期",
                "cron",
                "自动执行",
            ),
        ),
    ),
    ActionRule(
        "memory.manage",
        keyword_groups=(
            (
                "记住",
                "记下来",
                "保存记忆",
                "更新记忆",
                "删除记忆",
                "删除这条记忆",
                "删除该记忆",
                "忘掉",
                "忘掉这条",
                "归档记忆",
                "恢复记忆",
            ),
        ),
    ),
    ActionRule(
        "memory.recall",
        keyword_groups=(
            ("记得", "之前", "上次", "历史", "记忆", "回忆"),
        ),
    ),
    ActionRule(
        "background.monitor",
        keyword_groups=(
            ("后台任务", "后台执行", "执行进度", "任务进度", "后台结果"),
        ),
    ),
    ActionRule(
        "task.manage",
        keyword_groups=(
            ("任务", "待办", "todo"),
        ),
    ),
    ActionRule(
        "mcp.connect",
        keyword_groups=(
            ("mcp", "外部工具", "工具服务器"),
        ),
    ),
    ActionRule(
        "command.execute",
        keyword_groups=(
            (
                "执行命令",
                "运行命令",
                "运行脚本",
                "执行脚本",
                "运行测试",
                "执行测试",
                "安装",
                "部署",
                "重启",
                "启动服务",
                "停止服务",
                "删除",
                "清理",
                "回滚",
                "docker",
                "systemctl",
            ),
        ),
        excluded_keywords=("原理", "什么是", "教我"),
    ),
    ActionRule(
        "file.change",
        keyword_groups=(
            ("修改", "编辑", "写入", "创建", "新建", "替换", "改一下"),
            ("文件", "代码", "配置", "脚本", ".py", ".json", ".md", ".yaml", ".yml"),
        ),
    ),
    ActionRule(
        "file.read",
        keyword_groups=(
            ("读取", "打开", "查看", "看看", "搜索", "查找", "找一下"),
            ("文件", "目录", "代码", "配置", "脚本", ".py", ".json", ".md", ".yaml", ".yml"),
        ),
    ),
    ActionRule(
        "service.diagnose",
        keyword_groups=(
            (
                "nginx",
                "sshd",
                "systemd",
                "服务状态",
                "服务异常",
                "服务失败",
                "服务日志",
                "服务挂了",
                "服务起不来",
                "进程",
            ),
            ("异常", "失败", "挂了", "起不来", "状态", "日志", "排查", "诊断"),
        ),
    ),
    ActionRule(
        "network.diagnose",
        keyword_groups=(
            ("网络", "端口", "ping", "连接", "dns", "tcp", "超时"),
            ("异常", "失败", "不通", "排查", "诊断", "检查", "查看"),
        ),
    ),
    ActionRule(
        "system.inspect",
        keyword_groups=(
            (
                "巡检",
                "系统",
                "cpu",
                "内存",
                "磁盘",
                "进程",
                "负载",
                "服务器",
                "机器",
            ),
            ("检查", "查看", "分析", "怎么样", "状态", "排查", "巡检", "健康"),
        ),
    ),
)


def get_action(code: str) -> ActionDefinition | None:
    return ACTION_DEFINITIONS.get(code)


def route_action(message: str) -> ActionDefinition:
    for rule in ACTION_RULES:
        if rule.matches(message):
            action = ACTION_DEFINITIONS.get(rule.code)
            if action is not None:
                return action
    return ACTION_DEFINITIONS["general.chat"]


def resolve_action_tool_names(
    action: ActionDefinition,
    context: ToolPolicyContext | None = None,
    available_tool_names: list[str] | tuple[str, ...] | set[str] | None = None,
) -> list[str]:
    candidates = list(action.allowed_tools)
    if available_tool_names is not None:
        available = set(available_tool_names)
        candidates = [
            name for name in candidates
            if name in available
        ]
    return [
        name for name in candidates
        if evaluate_tool_policy(name, context).allowed
    ]


def filter_action_tools(
    tools: list[dict],
    action: ActionDefinition,
    context: ToolPolicyContext | None = None,
    *,
    preflight_mode: bool = False,
) -> list[dict]:
    allowed = set(resolve_action_tool_names(action, context))
    if preflight_mode:
        allowed = {
            name for name in allowed
            if (
                name == "propose_action"
                or not evaluate_tool_policy(name, context).requires_approval
            )
        }
    return [
        tool for tool in tools
        if tool.get("name") in allowed
    ]


def get_action_catalog() -> list[dict]:
    return [
        ACTION_DEFINITIONS[code].to_dict()
        for code in ACTION_DEFINITIONS
    ]


__all__ = [
    "ACTION_DEFINITIONS",
    "ActionDefinition",
    "ActionRule",
    "DIRECT",
    "PLAN_REACT",
    "REACT",
    "filter_action_tools",
    "get_action",
    "get_action_catalog",
    "resolve_action_tool_names",
    "route_action",
]

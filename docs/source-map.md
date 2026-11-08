# 源码底稿（source map）

> 用途：这是事实索引，不是讲解。用于回答"到底读了多少、每个文件干什么、入口在哪、四条待确认点结论是什么"。
> 统计口径：本仓库后端（`api/` `agent/` `mcp_servers/` `scripts/` `alembic/` `tests/` + `run.py`）共 **153 个 `.py` 文件、25,546 行**（行数按文件实际行数统计，含空行；此前用 `Measure-Object -Line` 会漏计空行，本表已全部重算）。状态列含义：**通读**＝本次逐行读完；**抽查**＝读过关键段（入口/主流程/关键分支），未逐行；**跳过**＝仅登记，未读内容。`frontend/`、`static/` 不在范围内，只在第 2 节末尾说明托管关系。

---

## 1. 覆盖率表（逐文件，全量 153 个）

### 1.1 根目录与 api（16 个）

| 路径 | 行数 | 状态 | 关键度 | 说明 |
|---|---|---|---|---|
| run.py | 5 | 通读 | P0 | 启动入口，全 5 行 |
| api/__init__.py | 0 | 跳过 | P2 | 空包标记 |
| api/main.py | 386 | 抽查 | P0 | 读过 L1–L222（启动、鉴权装配、session 门面、/tools、chat 流）；L223–L386 的 session 管理与内部同步执行未逐行 |
| api/auth.py | 77 | 通读 | P0 | 中间件与权限依赖，全读 |
| api/schemas.py | 98 | 跳过 | P2 | 响应模型，未读 |
| api/routes/__init__.py | 0 | 跳过 | P2 | 空包标记 |
| api/routes/action_route.py | 291 | 抽查 | P1 | 仅从调用方确认 confirm/cancel/pending 语义，未逐行 |
| api/routes/audit_route.py | 69 | 跳过 | P2 | 审计查询接口，参数未核 |
| api/routes/cron_route.py | 90 | 跳过 | P2 | CRUD 路由，未读 |
| api/routes/mcp_route.py | 235 | 跳过 | P2 | 三种传输的 connect/disconnect 路由，未读 |
| api/routes/memory_route.py | 111 | 跳过 | P2 | 记忆 CRUD，未读 |
| api/routes/recovery_route.py | 156 | 跳过 | P1 | 续跑接口，仅从前端调用契约推断；见第 3 节待补 |
| api/routes/sandbox_route.py | 25 | 跳过 | P2 | 列表接口，未读 |
| api/routes/skill_route.py | 37 | 跳过 | P2 | 技能列表/详情/reload，未读 |
| api/routes/target_route.py | 126 | 跳过 | P2 | target CRUD，未读 |
| api/routes/task.py | 139 | 跳过 | P2 | 任务路由，未读 |

### 1.2 agent/core（10 个）

| 路径 | 行数 | 状态 | 关键度 | 说明 |
|---|---|---|---|---|
| agent/__init__.py | 0 | 跳过 | P2 | 空 |
| agent/core/__init__.py | 0 | 跳过 | P2 | 空 |
| agent/core/agent_runtime.py | 16 | 通读 | P0 | 三 mixin 组合，全读 |
| agent/core/comprehensive.py | 161 | 抽查 | P0 | 读过 L54–L145（类声明、get_tool_registry、__init__、system prompt）；L1–L53 import 未逐行 |
| agent/core/context_compact.py | 386 | 抽查 | P0 | 读过压缩 8 个函数段（L15–L304 的多数）；`write_transcript`/`compact_history` 未逐行 |
| agent/core/context_manager.py | 120 | 通读 | P0 | 全文件 |
| agent/core/error_recovery.py | 118 | 跳过 | P1 | 429/529 降级逻辑未逐行 |
| agent/core/persistence.py | 80 | 跳过 | P1 | 运行期持久化钩子未逐行 |
| agent/core/pipeline.py | 637 | 抽查 | P0 | 读过 L46–L130、L209–L340、L131–L208；L340–L590 的收尾/取消分支为选择性读 |
| agent/core/tool_loop.py | 327 | 抽查 | P0 | 读过 L19–L115、L116–L303 的判定与审批路径；修复细节未逐行 |

### 1.3 agent/evaluation（7 个）

| 路径 | 行数 | 状态 | 关键度 | 说明 |
|---|---|---|---|---|
| agent/evaluation/__init__.py | 21 | 跳过 | P2 | 导出声明，未读 |
| agent/evaluation/approvals.py | 293 | 跳过 | P2 | 审批样本构造，未读 |
| agent/evaluation/baseline.py | 231 | 跳过 | P2 | 基线比较，仅知存在 |
| agent/evaluation/cases.py | 217 | 跳过 | P2 | 用例加载，未读 |
| agent/evaluation/judge.py | 248 | 抽查 | P1 | 读过 L130–L220（LLMJudge 与模型调用）；前半未读 |
| agent/evaluation/runner.py | 782 | 跳过 | P2 | 评估主循环，未读 |
| agent/evaluation/scoring.py | 355 | 跳过 | P2 | 打分聚合，未读 |

### 1.4 agent/extensions、mcp（9 个）

| 路径 | 行数 | 状态 | 关键度 | 说明 |
|---|---|---|---|---|
| agent/extensions/__init__.py | 0 | 跳过 | P2 | 空 |
| agent/extensions/subagent.py | 92 | 通读 | P1 | 子代理白名单与独立注册表，全读 |
| agent/mcp/__init__.py | 5 | 跳过 | P2 | 空壳导出 |
| agent/mcp/builtin.py | 176 | 跳过 | P2 | 4 个 mock server，未读实现 |
| agent/mcp/client.py | 47 | 抽查 | P1 | 三种传输的调度门面，读过全貌 |
| agent/mcp/custom.py | 210 | 跳过 | P2 | 自定义 server 注册与落盘，未读 |
| agent/mcp/registry.py | 151 | 抽查 | P1 | 读过 L1–L124 的关键函数（可见性、池拼装、破坏性判定） |
| agent/mcp/sse.py | 272 | 跳过 | P2 | SSE 传输实现，未读 |
| agent/mcp/stdio.py | 230 | 跳过 | P2 | stdio JSON-RPC 实现，未读 |

### 1.5 agent/memory（7 个）

| 路径 | 行数 | 状态 | 关键度 | 说明 |
|---|---|---|---|---|
| agent/memory/__init__.py | 0 | 跳过 | P2 | 空 |
| agent/memory/lifecycle.py | 450 | 跳过 | P1 | 记忆写入/合并/淘汰主逻辑，未读 |
| agent/memory/models.py | 293 | 抽查 | P1 | 读过打分与校验函数（L20–L155）；MemoryRecord 字段全貌部分读 |
| agent/memory/policy.py | 103 | 抽查 | P1 | 读过 scope 权限函数签名与内容 |
| agent/memory/retrieval.py | 133 | 抽查 | P1 | 读过检索主流程 |
| agent/memory/service.py | 32 | 通读 | P1 | mixin 组合，全读 |
| agent/memory/store.py | 84 | 抽查 | P1 | 读过 L8–L70 的仓储调用 |

### 1.6 agent/observability、orchestration（10 个）

| 路径 | 行数 | 状态 | 关键度 | 说明 |
|---|---|---|---|---|
| agent/observability/__init__.py | 0 | 跳过 | P2 | 空 |
| agent/observability/audit.py | 196 | 抽查 | P1 | 读过脱敏、record_event、list_events 主干 |
| agent/observability/logger.py | 34 | 跳过 | P2 | 日志配置，未读 |
| agent/orchestration/__init__.py | 0 | 跳过 | P2 | 空 |
| agent/orchestration/approval_coordinator.py | 103 | 通读 | P1 | 跨线程握手，全读 |
| agent/orchestration/background.py | 361 | 跳过 | P1 | 后台任务执行器，仅读过恢复入口名 |
| agent/orchestration/cron.py | 450 | 跳过 | P1 | 五字段 cron 解析与调度，未读实现 |
| agent/orchestration/pending_actions.py | 335 | 抽查 | P0 | 读过状态常量、`PendingAction` 字段与 `create_tool_call`/`confirm`/`cancel` 签名（L13–L270）；DB 落库细节未逐行 |
| agent/orchestration/pending_executor.py | 134 | 跳过 | P1 | 审批通过后的执行器，未逐行 |
| agent/orchestration/tasks.py | 182 | 跳过 | P2 | 任务图 CRUD 与依赖，未读 |

### 1.7 agent/persistence（16 个）

| 路径 | 行数 | 状态 | 关键度 | 说明 |
|---|---|---|---|---|
| agent/persistence/__init__.py | 1 | 跳过 | P2 | 空 |
| agent/persistence/database.py | 127 | 抽查 | P0 | 读过 L1–L45（engine/异常），L77–L110 只知签名 |
| agent/persistence/models.py | 578 | 抽查 | P0 | 读过 L30–L100、L332–L435；其余表字段选择性读 |
| agent/persistence/repositories/__init__.py | 1 | 跳过 | P2 | 空 |
| agent/persistence/repositories/actions.py | 333 | 抽查 | P0 | 读过函数清单与状态迁移签名 |
| agent/persistence/repositories/audit.py | 173 | 抽查 | P1 | 读过持久化/查询签名 |
| agent/persistence/repositories/background.py | 184 | 跳过 | P1 | 仅读函数清单 |
| agent/persistence/repositories/common.py | 180 | 抽查 | P0 | 读过 upsert/版本更新主干 |
| agent/persistence/repositories/cron.py | 278 | 跳过 | P1 | 仅读函数清单（含 claim_due_cron_jobs L186） |
| agent/persistence/repositories/eval.py | 512 | 跳过 | P2 | 仅读函数清单 |
| agent/persistence/repositories/memories.py | 259 | 跳过 | P1 | 仅读函数清单 |
| agent/persistence/repositories/runs.py | 279 | 跳过 | P1 | 仅读函数清单 |
| agent/persistence/repositories/sessions.py | 352 | 抽查 | P0 | 读过消息同步 L110–L191 与读取 L234 |
| agent/persistence/repositories/targets.py | 136 | 跳过 | P2 | 仅读函数清单 |
| agent/persistence/repositories/tasks.py | 246 | 跳过 | P2 | 仅读函数清单 |
| agent/persistence/repositories/usage.py | 55 | 跳过 | P1 | 用量行写入，未读 |

### 1.8 agent/platform、sandbox、sessions（13 个）

| 路径 | 行数 | 状态 | 关键度 | 说明 |
|---|---|---|---|---|
| agent/platform/__init__.py | 0 | 跳过 | P2 | 空 |
| agent/platform/config.py | 138 | 抽查 | P0 | 读过 env 解析区段 |
| agent/platform/identity.py | 103 | 通读 | P0 | 全读（Principal/角色判定/两个默认身份） |
| agent/platform/skill.py | 53 | 抽查 | P1 | 读过扫描与 list/加载接口 |
| agent/sandbox/__init__.py | 18 | 跳过 | P2 | 导出 |
| agent/sandbox/cleanup.py | 35 | 跳过 | P2 | 孤儿清理，仅知入口 |
| agent/sandbox/manager.py | 156 | 抽查 | P1 | 读过工作区生命周期主干 |
| agent/sandbox/models.py | 34 | 跳过 | P2 | 数据结构 |
| agent/sandbox/workspace.py | 94 | 抽查 | P1 | 读过路径解析与文件操作 |
| agent/sessions/__init__.py | 0 | 跳过 | P2 | 空 |
| agent/sessions/manager.py | 344 | 抽查 | P0 | 读过 L1–L172；L173–L307 的 reset/rename/list/append 未逐行 |
| agent/sessions/messages.py | 44 | 跳过 | P2 | 可见消息序列化，未读 |
| agent/sessions/state_store.py | 387 | 抽查 | P0 | 读过 L38–L346 的序列化与快照主干 |

### 1.9 agent/targets（5 个）

| 路径 | 行数 | 状态 | 关键度 | 说明 |
|---|---|---|---|---|
| agent/targets/__init__.py | 12 | 跳过 | P2 | 导出 |
| agent/targets/models.py | 43 | 跳过 | P2 | 数据结构 |
| agent/targets/service.py | 187 | 通读 | P0 | 全读：allowed_roots/浏览校验/规范化 |
| agent/targets/store.py | 54 | 跳过 | P2 | JSON 落盘，未读 |
| agent/targets/tools.py | 633 | 抽查 | P1 | 读过工具声明区（L455–L600）与本地执行函数（L168–L216） |

### 1.10 agent/tools（14 个）

| 路径 | 行数 | 状态 | 关键度 | 说明 |
|---|---|---|---|---|
| agent/tools/__init__.py | 89 | 抽查 | P0 | 读过三组合并与导出 |
| agent/tools/executor.py | 242 | 抽查 | P0 | 读过沙箱文件工具与执行门面 |
| agent/tools/file_tools.py | 129 | 跳过 | P1 | 四个文件工具的 schema/handler，未逐行 |
| agent/tools/ops.py | 495 | 跳过 | P1 | 13 个只读工具实现，未逐行 |
| agent/tools/policy.py | 630 | 抽查 | P0 | 读过 L20–L122 与 L123–L420 抽样；其余同构声明未读 |
| agent/tools/registry.py | 156 | 抽查 | P0 | 读过 L22–L133 |
| agent/tools/shell.py | 118 | 抽查 | P0 | 读过重定向规则 |
| agent/tools/business/__init__.py | 22 | 跳过 | P2 | 导出 |
| agent/tools/business/automation.py | 141 | 跳过 | P1 | cron/后台工具，未读 |
| agent/tools/business/base.py | 17 | 通读 | P0 | 注册顺序，全读 |
| agent/tools/business/integrations.py | 45 | 通读 | P1 | 子代理/compact/MCP 工具注册，全读 |
| agent/tools/business/knowledge.py | 31 | 通读 | P1 | list_skills/load_skill，全读 |
| agent/tools/business/memory.py | 377 | 跳过 | P1 | 7 个记忆工具，未读 |
| agent/tools/business/tasks.py | 93 | 跳过 | P1 | 5 个任务工具，未读 |

### 1.11 alembic（6 个）

| 路径 | 行数 | 状态 | 关键度 | 说明 |
|---|---|---|---|---|
| alembic/env.py | 100 | 跳过 | P1 | 迁移环境（URL 来源未核） |
| alembic/versions/0001_persistence_foundation.py | 87 | 抽查 | P1 | 读过审计/用量两表 |
| alembic/versions/0002_domain_tables.py | 166 | 抽查 | P1 | 读过四表名与约束 |
| alembic/versions/0003_automation_tables.py | 195 | 抽查 | P1 | 读过四表名 |
| alembic/versions/0004_session_tables.py | 142 | 抽查 | P1 | 读过四表名 |
| alembic/versions/0005_eval_tables.py | 196 | 跳过 | P2 | 四张 eval 表，未逐行 |

### 1.12 mcp_servers、scripts（7 个）

| 路径 | 行数 | 状态 | 关键度 | 说明 |
|---|---|---|---|---|
| mcp_servers/alert_server.py | 95 | 跳过 | P2 | 示例 MCP server，未读 |
| scripts/check_persistence.py | 22 | 跳过 | P2 | 健康检查入口 |
| scripts/compare_eval.py | 86 | 跳过 | P2 | 评估对比 CLI |
| scripts/migrate_legacy_json.py | 231 | 跳过 | P2 | JSON→PG 迁移，未读 |
| scripts/persistence_health.py | 86 | 跳过 | P2 | 健康报告 |
| scripts/run_eval.py | 274 | 跳过 | P2 | 评估 CLI |
| scripts/run_start_docker_hyperv_elevated.py | 17 | 跳过 | P2 | 提权启动脚本 |

### 1.13 tests（33 个文件）

| 路径 | 行数 | 状态 | 关键度 | 说明 |
|---|---|---|---|---|
| tests/conftest.py | 35 | 抽查 | P1 | 读过隔离 fixture |
| tests/test_agent_background.py | 74 | 跳过 | P2 | 后台工具 |
| tests/test_api_schemas.py | 44 | 跳过 | P2 | 响应模型 |
| tests/test_audit.py | 88 | 跳过 | P1 | 审计 |
| tests/test_background.py | 52 | 跳过 | P2 | 后台任务 |
| tests/test_bash_redirect.py | 120 | 跳过 | P1 | bash 重定向 |
| tests/test_cancellation.py | 48 | 跳过 | P1 | 取消 |
| tests/test_context_compaction.py | 392 | 跳过 | P0 | 压缩（只知用例数） |
| tests/test_cron.py | 292 | 跳过 | P1 | cron |
| tests/test_eval_store.py | 163 | 跳过 | P2 | eval 存储 |
| tests/test_evaluation_baseline.py | 104 | 跳过 | P2 | 基线 |
| tests/test_evaluation_runner.py | 427 | 跳过 | P2 | 评估运行 |
| tests/test_mcp.py | 117 | 跳过 | P1 | MCP |
| tests/test_memory.py | 169 | 跳过 | P1 | 记忆 |
| tests/test_memory_governance.py | 232 | 跳过 | P2 | 记忆治理 |
| tests/test_memory_p1.py | 67 | 跳过 | P2 | 记忆 P1 |
| tests/test_memory_retrieval.py | 131 | 跳过 | P1 | 检索打分 |
| tests/test_messages.py | 45 | 跳过 | P1 | 消息序列化 |
| tests/test_pending_actions.py | 485 | 跳过 | P0 | 审批状态机 |
| tests/test_persistence_health_script.py | 38 | 跳过 | P2 | 健康脚本 |
| tests/test_persistence_pg_integration.py | 712 | 抽查 | P1 | 读过环境变量门控与迁移前置 |
| tests/test_recovery_api.py | 88 | 跳过 | P1 | 恢复接口 |
| tests/test_sandbox.py | 208 | 跳过 | P1 | 沙箱 |
| tests/test_security_hardening.py | 56 | 跳过 | P1 | 安全加固 |
| tests/test_session_manager.py | 124 | 跳过 | P1 | 会话管理 |
| tests/test_state_store.py | 163 | 跳过 | P1 | 快照 |
| tests/test_subagent.py | 54 | 跳过 | P2 | 子代理 |
| tests/test_targets.py | 282 | 跳过 | P1 | target |
| tests/test_task_system.py | 184 | 跳过 | P2 | 任务图 |
| tests/test_tool_catalog.py | 35 | 跳过 | P1 | 工具目录 |
| tests/test_tool_loop_repair.py | 111 | 跳过 | P1 | 消息配对修复 |
| tests/test_tool_policy.py | 137 | 跳过 | P0 | 策略 |
| tests/test_tool_registry.py | 49 | 跳过 | P0 | 注册表 |

---

## 2. 模块索引（按目录）

> 四字段模板以表格承载：职责 / 对外入口（行号） / 关键机制（行号） / 依赖方向。未细读的文件在"关键机制"如实写"未细读"。

### 2.1 api

| 文件 | 职责 | 对外入口 | 关键机制 | 依赖方向 |
|---|---|---|---|---|
| `api/main.py` | FastAPI 应用装配、启动对账、chat 路由、session 门面 | `lifespan(L49)`、`_recover_startup_state(L79)`、`_ensure_cron_started(L141)`、`get_or_create_session(L156)`、`GET /tools(L196)`、`POST /api/chat/stream(L244)` | 四件对账（L87/L107/L109/L125）；SSE 帧 `data: {...}\n\n`（L272）；`run_lock` 串行（L266）；静态托管（L386 区） | 上游：uvicorn；下游：SessionManager、RecoveryStore、各 router |
| `api/auth.py` | Bearer 中间件 + 权限依赖 + 公开路径白名单 | `BearerAuthMiddleware(L26)`、`require_permissions(L63)`、`get_request_principal(L56)` | 白名单 L13–L23；空 token 直接赋 admin（L33–L35）；`compare_digest`（L43） | 上游：所有请求；下游：`platform/identity` |
| `api/schemas.py` | Pydantic 响应模型 | 未细读 | 未细读 | 被 router 引用 |
| `api/routes/*.py` | 各业务域 REST 路由 | 见各文件（未细读） | 未细读 | 下游：orchestration/persistence/memory/sandbox/targets |

### 2.2 agent/core

| 文件 | 职责 | 对外入口 | 关键机制 | 依赖方向 |
|---|---|---|---|---|
| `agent_runtime.py` | 三个运行期 mixin 的组合声明 | `AgentRuntimeMixin(L8)` | persistence→tool_loop→pipeline 的 MRO（L8–L11） | 被 `comprehensive` 继承 |
| `comprehensive.py` | 组装完整 Agent | `ComprehensiveAgent(L55)`、`get_tool_registry(L63)`、`__init__(L75)` | 类级注册表 `object.__new__`（L65）；按需构造 SDK 客户端与各 store（L75–L126） | 上游：SessionManager 工厂；下游：全部 mixin |
| `pipeline.py` | 主循环、SSE 事件、异常分级 | `run(L76)`、`run_stream(L88)`、`resume_stream(L97)`、`_run_stream_impl(L209)` | 50 轮上限（L291–L296）；每轮压缩（L307）；prompt 过长恢复（L322+）；`_finish_run_state` | 下游：`context_manager`、`tool_loop`、`state_store` |
| `context_manager.py` | 系统提示构建 + 压缩入口 | `_compact_if_needed(L115)`、`_build_system_prompt(L42)` | 三层顺序 micro→snip→trim（L115–L120）；skills 清单注入（L55） | 上游：pipeline；下游：`context_compact`、`platform/skill` |
| `context_compact.py` | 压缩原子函数集 | `estimate_size(L15)`、`persist_large_output(L61)`、`snip_compact(L165)`、`trim_by_size(L210)`、`micro_compact(L241)`、`summarize_history(L281)`、`reactive_compact(L361)` | 字节口径（L15）；删中间保头尾（L165）；超限硬裁（L210） | 被 `context_manager`/`pipeline` 调用 |
| `tool_loop.py` | 工具分派与审批等待 | `_handle_tool_call(L197)`、`_create_tool_approval(L141)`、`_await_tool_approval(L260)` | 策略判定→拒绝/重定向/审批/执行（L197–L258）；轮询等待（L260–L303）；消息配对修复（L19–L115） | 上游：pipeline；下游：`tools.policy`、`orchestration.pending_*`、`tools.executor` |
| `error_recovery.py` | 模型错误分级与降级 | 未细读 | 未细读 | 被 pipeline 调用 |
| `persistence.py` | 运行期落库钩子 | 未细读 | 未细读 | 被 pipeline/state_store 调用 |

### 2.3 agent/tools

| 文件 | 职责 | 对外入口 | 关键机制 | 依赖方向 |
|---|---|---|---|---|
| `tools/__init__.py` | 内置工具总表 | `ALL_TOOL_SCHEMAS/HANDLERS(L1–L46)` | shell 1 + ops 13 + targets 10 合并；file 四件套未纳入（L42–L46） | 被 `registry.builtin()` 调用 |
| `registry.py` | schema/handler/policy 三合一 | `ToolSpec(L22)`、`ToolRegistry(L29)`、`builtin(L36)`、`with_dynamic_tools(L137)` | 注册表不可变复制；动态 MCP 叠加（L137+） | 上游：Agent；下游：executor |
| `policy.py` | 风险元数据与判定 | `ToolPolicy`、`evaluate_tool_policy(L554)` | 风险/权限常量（L15–L38）；`ToolPolicy` 八字段（L52–L60）；逐工具声明（L123+）；`evaluate_tool_policy(L554)` | 上游：tool_loop；下游：audit |
| `shell.py` | bash 重定向规则 | `suggest_tool_for_command(L27)` | 规则表（L12–L19）；只读命令改走专用工具；`force:` 逃生口（L33） | 上游：tool_loop |
| `executor.py` | 工具执行门面 + 沙箱文件操作 | `ToolExecutor.execute`、文件工具实现 | 沙箱工作区隔离；执行开关 | 上游：tool_loop；下游：sandbox |
| `file_tools.py` | 四个文件工具 schema/handler | 未细读 | 未细读 | 被 subagent 独立注册表引用 |
| `ops.py` | 13 个只读观测工具 | 未细读 | 未细读 | 被 `tools/__init__` 引用 |
| `business/base.py` | 业务工具注册顺序 | `_register_default_tools(L9)` | task→skill→memory→subagent→compact→cron→background（L9–L17） | 被 Agent `__init__` 调用 |
| `business/tasks.py` | 5 个任务工具 | 未细读 | 未细读 | 依赖 orchestration.tasks |
| `business/memory.py` | 7 个记忆工具 | 未细读 | 未细读 | 依赖 memory.service |
| `business/automation.py` | cron/后台工具 | 未细读 | 未细读 | 依赖 orchestration |
| `business/knowledge.py` | 技能工具 | `list_skills`、`load_skill`（L6–L29） | 只返回名称+描述 / 按需全文 | 依赖 platform.skill |
| `business/integrations.py` | 子代理、compact、MCP 工具注册 | `_add_subagent_tool` 等（L10–L37） | 子代理用独立注册表与独立执行开关 | 依赖 extensions.subagent、mcp |

### 2.4 agent/sessions 与 persistence

| 文件 | 职责 | 对外入口 | 关键机制 | 依赖方向 |
|---|---|---|---|---|
| `sessions/manager.py` | 内存会话、TTL、锁、还原 | `SessionManager(L55)`、`get_or_create(L91)` | 内存命中直接返回（L99–L104）；未命中从 PG 还原（L106–L137）；`cancel_event`/`run_lock`（L144–L151）；TTL 2h（L61） | 下游：`state_store`、Agent 工厂 |
| `sessions/state_store.py` | 会话/run/快照读写 | `RecoveryStore(L182)`、`save_session`、`save_run(L270)`、`interrupt_stale_runs` | 序列化消息（L38–L100）；安全点快照组装（L145–L181） | 下游：repositories |
| `sessions/messages.py` | 可见消息裁剪 | 未细读 | 未细读 | 被 state_store/manager |
| `persistence/database.py` | engine/session/ping | `persistence_enabled(L15)`、`get_engine(L29)`、`session_scope(L65)`、`ping_database(L77)` | 无 `DATABASE_URL` 直接 raise（L32）；池参数来自 config | 被全部仓储与启动 |
| `persistence/models.py` | 18 张表 ORM | 各 `*Record(L34–L533)` | 见第 1.7 与迁移 | 被 repositories |
| `persistence/repositories/*` | 每表一个仓储模块 | 函数清单（见各文件首部） | `common.upsert_row(L37)`、`update_row_if_version(L127)`；`sessions._sync_messages(L110)`；`cron.claim_due_cron_jobs(L186)` | 被 state_store/各业务 store |

### 2.5 其余 agent 子系统

| 文件 | 职责 | 对外入口 | 关键机制 | 依赖方向 |
|---|---|---|---|---|
| `orchestration/pending_actions.py` | Pending Action 状态机 | `PendingActionStore(L111)`、`create_tool_call(L114)`、`confirm(L191)`、`cancel(L233)`、`finish(L270)`、`recover_interrupted(L311)` | 状态常量（L13–L26）；DB 落库（`actions` 仓储，L9 导入）；无进程内锁 | 上游：tool_loop；下游：actions 仓储 |
| `orchestration/pending_executor.py` | 审批通过后的执行 | 未细读 | 未细读 | 下游：executor |
| `orchestration/approval_coordinator.py` | 跨线程等待/唤醒 | `ApprovalCoordinator(L23)`、`register(L30)`、`resolve(L37)`、`wait(L57)`、单例 `approval_coordinator(L95)` | `threading.Event` + 0.2s 轮询（L80）；超时/取消返回拒绝（L72–L88） | 上游：tool_loop；下游：审批 API |
| `orchestration/cron.py` | 五字段 cron 与调度循环 | `cron_scheduler_loop`、`load_durable_jobs` | 未细读 | 下游：cron 仓储、background |
| `orchestration/background.py` | 后台任务执行 | `recover_interrupted_background_tasks` | 未细读 | 下游：background 仓储 |
| `orchestration/tasks.py` | 任务图与依赖 | 未细读 | 未细读 | 下游：tasks 仓储 |
| `mcp/registry.py` | MCP 连接与工具池 | `assemble_tool_pool(L91)`、`get_mcp_tool_names(L119)` | 进程级 `mcp_clients` 字典（L10）；按 owner/session 可见性（L71–L89）；破坏性判定（L135） | 上游：Agent/tools；下游：三传输 |
| `mcp/client.py` | 传输调度门面（兼容导出） | `connect_mcp` 由 `builtin` 重导出（L5） | http/sse/stdio 三路重导出（L19–L45） | 下游：http/sse/stdio |
| `mcp/custom.py` | 自定义 server 注册 | `register_custom_server(L139)`、`load_all_custom_servers(L171)` | JSON 落盘 + 重建 handler | 上游：session 创建时 |
| `mcp/stdio.py` / `sse.py` | 两种传输 | `connect_*` | JSON-RPC + 事件循环；未细读 | 下游：外部进程/服务 |
| `memory/service.py` | 组合记忆系统 | `MemorySystem(L17)` | store+retrieval+lifecycle 三 mixin | 上游：memory 工具 |
| `memory/store.py` | 记忆读写 mixin | `MemoryStoreMixin(L17)`、`_load(L26)`、`_save(L36)`、`_reload_if_changed(L43)`、`flush_access_stats(L47)` | generation 号用于跨进程失效检测（L43） | 下游：memories 仓储 |
| `memory/retrieval.py` | 检索 | `MemoryRetrievalMixin(L19)`、`select(L54)`、`extract(L102)`、`format_relevant(L118)` | 关键词+bigram 打分；近重复检测（L20） | 下游：models._memory_score |
| `memory/models.py` | 记忆模型与打分 | `tokenize_text(L31)`、`similarity_score(L47)`、`_memory_score(L127)`、`MemoryRecord(L217)` | 无向量；CJK bigram；recency/access 加权 | 被 store/retrieval |
| `memory/lifecycle.py` | 合并/淘汰 | 未细读 | 未细读 | 下游：store |
| `memory/policy.py` | scope 权限 | `can_read_scope(L16)`、`can_write_scope(L38)`、`can_manage_record(L62)` | 私有/会话/全局读权 | 被工具与检索 |
| `sandbox/manager.py` | 沙箱生命周期 | 未细读全貌 | 创建/清理工作区 | 下游：workspace/cleanup |
| `sandbox/workspace.py` | 路径解析与文件操作 | 未细读全貌 | 限根目录 | 下游：file_tools |
| `sandbox/cleanup.py` | 孤儿清理 | `cleanup_orphan_sandboxes` | 启动时调用 | 上游：lifespan |
| `platform/config.py` | env 解析 | 模块级常量 | 模型/DB/记忆/安全四组 | 被全仓 |
| `platform/identity.py` | 身份与权限 | `Principal`、`principal_from_roles`、`system_admin_principal(L82)`、`configured_api_principal(L86)` | 除 SESSION_MANAGE/AUDIT_VIEW 外一律 True | 被 auth/session |
| `platform/skill.py` | 技能扫描 | `scan_skills`、`list_skills`、`load_skill` | 目录+frontmatter | 上游：prompt 构建、knowledge 工具 |
| `targets/service.py` | target 目录校验 | `allowed_roots`、`browse_directories` | `TARGET_BROWSE_ROOTS` 限根（L26–L49） | 上游：target 工具/路由 |
| `targets/tools.py` | 10 个 target 工具 | 工具声明（L455–L600） | 本机路径 + 本机子进程（L168–L216） | 下游：service、subprocess |
| `targets/store.py` | target 元数据落盘 | 未细读 | 未细读 | 被路由 |
| `extensions/subagent.py` | 子代理 | `spawn_subagent(L37)` | 独立注册表含 file 四件套（L46–L47）；`execute_enabled=False`（L58）；30 轮上限（L60） | 上游：integrations 工具 |
| `observability/audit.py` | 审计写入与查询 | `record_event(L138)`、`list_events(L113)` | 脱敏（L40–L57）；截断（L54/L161） | 下游：audit 仓储 |
| `observability/logger.py` | 日志 | 未细读 | 未细读 | 全仓 |
| `evaluation/judge.py` | LLM 判分 | `LLMJudge(L132)` | 真调 `client.messages.create`（L168） | 下游：runner |
| `evaluation/runner.py` | 评估主循环 | 未细读 | 未细读 | 下游：cases/judge/scoring/eval 仓储 |
| `evaluation/scoring.py` | 打分汇总 | 未细读 | 未细读 | 被 runner |
| `evaluation/cases.py` `baseline.py` `approvals.py` | 用例/基线/审批样本 | 未细读 | 未细读 | 被脚本 |

### 2.6 非 Python 与接口边界

- `skills/`：9 个 Markdown 技能目录（docker-debug、git-basics、learning-path、linux-basics、log-monitor、network-security、nginx-troubleshooting、python-deploy、service-deploy）。扫描逻辑在 `platform/skill.py`；清单注入见第 4 节结论 4。
- `mcp_servers/alert_server.py`：唯一示例 MCP 服务（95 行，未读）。
- `frontend/`（排除）：构建产物输出到 `../static`，由 `api/main.py` 以 `StaticFiles` 挂在 `/ui`，因此后端重启即前端重启；接口边界只涉及 `POST /api/chat/stream` 与各 REST 路由。

---

## 3. 三条主数据流（第 1 条已完整；第 2、3 条标"待补"）

### 3.1 `POST /api/chat/stream`（完整）

1. `api/main.py:chat_stream(L244)` 接收请求并取 `message`。
2. `api/main.py:get_or_create_session(L156)` → 默认 principal、确保 cron、转调 manager。
3. `agent/sessions/manager.py:get_or_create(L91)` → 内存命中（L99）或从 PG 还原（L106）。
4. `agent/sessions/manager.py` L121 → `agent_factory(...)`，构造 `ComprehensiveAgent`。
5. `api/main.py` L266 → `with session["run_lock"]`，会话内串行。
6. `agent/core/pipeline.py:run_stream(L88)` → `_run_stream_impl(L209)`。
7. 每轮：`_compact_if_needed`（pipeline L307 → context_manager L115）、`_call_api`（L320 区）。
8. 有 `tool_use` → `tool_loop.py:_handle_tool_call(L197)` → 策略判定（L198）→ 审批或执行（L229/L250）。
9. 工具结果回填 `messages`，下一轮；超过 50 轮退出（L291–L296）。
10. 每事件 `yield f"data: {json.dumps(event)}\n\n"`（main L272），前端逐帧解析。
11. 结束/异常 → `_finish_run_state`，`state_store.save_run`（L270）写 `runs`/`run_snapshots`，用量写 `run_usage`。

### 3.2 recovery resume stream（待补）

已确认节点：`GET /api/recovery/runs`、`.../runs/<run_id>`、`POST /api/recovery/runs/<run_id>/resume/stream`（来自前端契约）；后端入口在 `api/routes/recovery_route.py`（未读）。续跑落到 `pipeline.resume_stream`（L97–L129）与 `safe_to_resume` 判定（main L87–L105 写入）。**函数级剩余步骤待补。**

### 3.3 cron / background（待补）

已确认节点：`lifespan._ensure_cron_started`（main L141）→ `load_durable_jobs` + `Thread(cron_scheduler_loop, daemon=True)`（L149–L151）；`claim_due_cron_jobs`（repositories/cron.py L186）→ `upsert_cron_log`（L229）；后台任务恢复 `recover_interrupted_background_tasks`（main L107）。**调度循环内部、租约判定、执行器调用链待补。**

---

## 4. 四个待确认点的结论

| # | 问题 | 结论 | 证据 |
|---|---|---|---|
| 1 | target 远程执行通道 | **不是 SSH、不是被控端**。target 就是**本机目录**：根路径受 `TARGET_BROWSE_ROOTS` 白名单限制；命令用**本机子进程**执行 | `agent/targets/service.py` 的 `allowed_roots`/`browse_directories`（L26–L49）、`normalize_target(L78)`；`agent/targets/tools.py` `_resolve(L49)`、`_run_project_command(L174)`、`_run_systemctl_restart(L201)` 均为本地 `Path`/`subprocess` |
| 2 | 子代理是否持有 file 四件套 | **是**，但注入的是**子代理自己的注册表**，不是主 Agent 的 | `agent/extensions/subagent.py`：白名单含 read/write/edit/glob（L16–L21）；`ToolRegistry(FILE_TOOL_SCHEMAS, ...)`（L46–L47）；`execute_enabled=False`（L58）；与 `tools/__init__.py` 未合并 file 工具（L42–L46）互为印证 |
| 3 | eval 是否真调 LLM judge | **是**。`LLMJudge` 构造真实 `Anthropic` 客户端并调用 `client.messages.create`，不是静态打分 | `agent/evaluation/judge.py`：`LLMJudge(L132)`、`self.client.messages.create(...)`（L168） |
| 4 | skills 是否预注入 system prompt | **预注入的是"名称+描述"清单，不是全文**；全文由 `load_skill` 工具按需读取 | `agent/core/context_manager.py:_build_system_prompt` 调用 `list_skills()`（L55）；`agent/platform/skill.py:list_skills(L39)` 输出 `name: description`；`agent/tools/business/knowledge.py` 的 `load_skill` handler（L28–L29）转发到 `platform/skill.py:load_skill(L46)` 返回整篇 |

---

## 5. 隐含假设与耦合点（要点）

| 假设/耦合 | 为什么是"没写明但依赖" | 证据 |
|---|---|---|
| 启动必须有 DB | 无 `DATABASE_URL` 时 `get_engine` 直接 raise，lifespan 第一步行对账即失败，服务不启动 | `database.py#L32`、`main.py#L51` |
| session 必须同进程 | 内存字典 + `cancel_event`/`run_lock` 都是进程内对象，跨进程无法共享 | `manager.py#L68`、`#L144-L151` |
| MCP 连接生命周期绑进程 | 全局 `mcp_clients` 字典，进程退出即丢；重连靠会话创建时 `load_all_custom_servers` | `mcp/registry.py#L10`、`manager.py#L113-L115` |
| 单 worker 才安全 | cron 用进程内布尔标记 + daemon 线程；多 worker 各自起一个 | `main.py#L74-L76`、`#L141-L153` |
| 鉴权默认放开 | 未配 token 时请求被赋 admin 身份 | `auth.py#L33-L35`、`identity.py#L86-L90` |
| 上下文按字节而非 token | 压缩阈值用 JSON 字节长度估算 | `context_compact.py#L15` |
| target 是本机 | 浏览根、路径校验、subprocess 都基于本机 | `targets/service.py#L26-L49`、`targets/tools.py#L174` |
| 审计长文本会丢信息 | 标题/摘要/字段有长度截断 | `audit.py#L54`、`#L161-L162` |

---

## 6. 未读清单（按优先级）

**本轮未读、后续值得补（P0/P1）**
- `agent/orchestration/cron.py`(450)、`background.py`(361)、`pending_executor.py`(134)、`tasks.py`(182)
- `agent/memory/lifecycle.py`(450)、`agent/tools/business/memory.py`(377)、`tasks.py`(93)、`automation.py`(141)
- `agent/tools/ops.py`(495)、`file_tools.py`(129)
- `agent/core/error_recovery.py`(118)、`agent/core/persistence.py`(80)
- `api/routes/recovery_route.py`(156)、`action_route.py`(291)
- `agent/persistence/repositories/runs.py`(279)、`cron.py`(278)、`memories.py`(259)、`usage.py`(55)

**结构性未读（P2，不影响主线判断）**
- `agent/evaluation/runner.py`(782)、`scoring.py`(355)、`approvals.py`(293)、`baseline.py`(231)、`cases.py`(217)
- `agent/mcp/sse.py`(272)、`stdio.py`(230)、`custom.py`(210)、`builtin.py`(176)
- `scripts/*`（migrate 231 / run_eval 274 等）
- `alembic/env.py`、`0005` 的字段细节
- `tests/` 全部 32 个 `test_*.py`（仅按文件名与个别片段归纳，未逐条断言）

**说明**：25,546 行里本轮逐行读完的只有 12 个文件（约 830 行），其余为抽查或登记。这份底稿的价值在"入口与结论可核"，不在"已读完全部实现"。

# 后端阅读路线（排除 frontend）

> 用途：这是一份可勾选的走读清单。目标是**读完之后能独立判断系统行为**（一次请求怎么跑、在哪失败、为什么需要审批、重启后还剩什么），而不是把每个文件读完。前端只在接口边界出现一次，不列入阅读项。
>
> 用法：按阶段顺序读，读完一个文件就打一个勾；每阶段末尾的"验证"是可执行命令，前置缺失就记下缺什么，不要跳过验证直接打勾。

---

## 最短主线（P0，约 2.5–3 小时）

按"一个请求怎么活下来"的顺序，只读 P0：

- [ ] [run.py](run.py) + [api/main.py](api/main.py#L48-L70) — 启动与中间件（10m）
- [ ] [api/main.py](api/main.py#L244-L290) — SSE 入口与会话锁（10m）
- [ ] [agent/core/comprehensive.py](agent/core/comprehensive.py#L55-L126) — Agent 装配（10m）
- [ ] [agent/core/pipeline.py](agent/core/pipeline.py#L76-L130) + [L209-L340](agent/core/pipeline.py#L209-L340) — 一轮循环骨架（30m）
- [ ] [agent/core/context_manager.py](agent/core/context_manager.py#L115-L120) + [context_compact.py](agent/core/context_compact.py#L15-L20) / [L165-L240](agent/core/context_compact.py#L165-L240) — 压缩三层（20m）
- [ ] [agent/core/tool_loop.py](agent/core/tool_loop.py#L197-L258) — 工具分派（15m）
- [ ] [agent/tools/policy.py](agent/tools/policy.py#L52-L122) + 抽样 `_build_builtin_policies` — 风险与审批判定（15m）
- [ ] [agent/tools/registry.py](agent/tools/registry.py#L22-L133) + [tools/\_\_init\_\_.py](agent/tools/__init__.py#L42-L52) — 工具池构成（10m）
- [ ] [agent/persistence/models.py](agent/persistence/models.py#L30-L100) + [L332-L435](agent/persistence/models.py#L332-L435) — 核心落库形状（15m）
- [ ] [agent/sessions/state_store.py](agent/sessions/state_store.py#L182-L346) — run 快照与安全点（15m）

**主线排除**：`api/routes/*`（除 action/recovery）、`ops.py`/`targets/tools.py` 明细、`memory/*`、`mcp/*`、`cron/background`、`sandbox/*`、`evaluation/*`、`scripts/*`、全部 `frontend/`。

---

## 阶段 1｜入口与启动（P0，约 25 分钟）

**读完能回答**：谁在什么时刻做崩溃对账？cron 线程为什么只能起一次？鉴权在什么条件下等于关闭？

- [ ] [run.py](run.py) 全文件
- [ ] [api/main.py](api/main.py#L48-L153) lifespan / 启动恢复 / cron 单例
- [ ] [api/main.py](api/main.py#L156-L178) session 获取门面
- [ ] [api/auth.py](api/auth.py) 全文件
- [ ] [agent/platform/config.py](agent/platform/config.py) 全文件（读 env 名）

**可选深挖**：`_recover_startup_state` 四个恢复分支各自对应的 store（main.py#L79-L139）。
**可跳过**：`/tools`、`/api/messages/`、`/api/chat/sessions` 的实现细节。

**验证**

1. `python -c "import api.main"`（前置：依赖已安装，无 .env 也可，不要启动服务）
2. `python run.py` 后 `curl http://localhost:8000/health`（短超时后台起再关，不要占着 8000）
3. `curl http://localhost:8000/tools` 数工具数（应为 45）
4. 临时把 `API_AUTH_TOKEN` 设为非空（用环境变量覆盖，不改 `.env`），验证不带 Header 是否 401/403

---

## 阶段 2｜Agent 装配（P0，约 15 分钟）

**读完能回答**：一个会话拿到的是哪个对象？初始化时构造了哪些外部依赖？工具在什么时候注册完？

- [ ] [agent/core/comprehensive.py](agent/core/comprehensive.py#L55-L126) 类声明 + `__init__`
- [ ] [agent/core/agent_runtime.py](agent/core/agent_runtime.py#L1-L11) 三 mixin 组合
- [ ] [agent/tools/business/base.py](agent/tools/business/base.py#L9-L17) 注册顺序
- [ ] [agent/core/persistence.py](agent/core/persistence.py) 全文件

**可跳过**：`get_tool_registry/get_tool_catalog` 两个 classmethod（测试才用）。

**验证**

1. `curl http://localhost:8000/tools` 数工具总数
2. `python -m pytest tests/test_tool_catalog.py -q`（不需要 key）

---

## 阶段 3｜主流水线与状态（P0，约 50 分钟）

**读完能回答**：50 轮里每轮干什么？Prompt 过长为什么最多重试 2 次？失败后为什么是"可续跑"而非"自动重放"？

- [ ] [agent/core/pipeline.py](agent/core/pipeline.py#L46-L130) 三个入口 `run/run_stream/resume_stream`
- [ ] [agent/core/pipeline.py](agent/core/pipeline.py#L209-L340) 循环头 + 压缩 + 调模型 + 过长恢复
- [ ] [agent/core/pipeline.py](agent/core/pipeline.py#L340-L470) 异常分级与工具分派衔接 ≈
- [ ] [agent/core/pipeline.py](agent/core/pipeline.py#L470-L590) 收尾、done/error、`_finish_run_state` ≈
- [ ] [agent/core/pipeline.py](agent/core/pipeline.py#L131-L208) usage 记账

**可选深挖**：[error_recovery.py](agent/core/error_recovery.py)（429/529 降级）。
**可跳过**：`_repair_message_sequence` 内部四个函数（tool_loop.py#L19-L115），知道"有配对修复"即可。

**验证**

1. `python -m pytest tests/test_cancellation.py tests/test_context_compaction.py tests/test_tool_loop_repair.py -q`
2. 起服务后跑一次真实对话：`curl -N -X POST http://localhost:8000/api/chat/stream ...`
3. 中途调 cancel 接口，确认流以 cancelled 收尾

---

## 阶段 4｜上下文压缩（P0，约 25 分钟）

**读完能回答**：常规轮次压缩走哪几层？阈值是字节还是 token？大结果去哪了？

- [ ] [agent/core/context_manager.py](agent/core/context_manager.py) 全文件
- [ ] [agent/core/context_compact.py](agent/core/context_compact.py#L15-L110) `estimate_size` / `persist_large_output` / `head_tail_truncate`
- [ ] [agent/core/context_compact.py](agent/core/context_compact.py#L165-L240) `snip_compact` / `trim_by_size`
- [ ] [agent/core/context_compact.py](agent/core/context_compact.py#L281-L304) `summarize_history` / `reactive_compact`

**可跳过**：`write_transcript`、`compact_history` 细节。

**验证**

1. `python -m pytest tests/test_context_compaction.py -q`
2. 手动调用 `estimate_size` 验证"字节口径"

---

## 阶段 5｜工具注册、策略、执行（P0，约 40 分钟）

**读完能回答**：45 个工具怎么分三组？为什么 bash 会被改写？判定后到执行之间还有哪些点？

- [ ] [agent/tools/registry.py](agent/tools/registry.py#L22-L133) 全文件
- [ ] [agent/tools/\_\_init\_\_.py](agent/tools/__init__.py#L42-L52) 三组合并（注意 file 工具不在内）
- [ ] [agent/tools/executor.py](agent/tools/executor.py) 全文件
- [ ] [agent/tools/shell.py](agent/tools/shell.py) 全文件（重定向规则）
- [ ] [agent/tools/policy.py](agent/tools/policy.py#L20-L122) + `evaluate_tool_policy` 段
- [ ] [agent/tools/policy.py](agent/tools/policy.py#L123-L420) 抽样 6–8 条（bash/target_write/restart/deploy）

**可选深挖**：[ops.py](agent/tools/ops.py#L1-L80)、[targets/tools.py](agent/targets/tools.py#L455-L600)。
**可跳过**：policy 剩余同构声明。

**验证**

1. `python -m pytest tests/test_tool_registry.py tests/test_tool_policy.py tests/test_bash_redirect.py -q`
2. 对话里发"用 bash 看磁盘"，观察返回 `Redirected: use ...`

---

## 阶段 6｜审批与安全闸门（P1，约 40 分钟）

**读完能回答**：审批记录存哪？跨线程怎么等？重启时在途审批怎么收场？

- [ ] [agent/core/tool_loop.py](agent/core/tool_loop.py#L141-L196) `_create_tool_approval`
- [ ] [agent/core/tool_loop.py](agent/core/tool_loop.py#L260-L303) `_await_tool_approval`
- [ ] [agent/orchestration/pending_actions.py](agent/orchestration/pending_actions.py#L1-L120) 状态机与条件更新
- [ ] [agent/orchestration/pending_executor.py](agent/orchestration/pending_executor.py) 全文件
- [ ] [api/routes/action_route.py](api/routes/action_route.py) confirm/cancel

**可选深挖**：[approval_coordinator.py](agent/orchestration/approval_coordinator.py)。
**可跳过**：分页与鉴权装饰器细节。

**验证**

1. `python -m pytest tests/test_pending_actions.py -q`
2. 触发需审批命令 → `curl /api/actions/pending` → confirm
3. `curl /api/audit/events?limit=20` 应见 `pending_action.created` / `policy.allowed`

---

## 阶段 7｜数据层与迁移（P1，约 40 分钟）

**读完能回答**：18 张表怎么分五批建？谁直接碰 SQL？池与超时配在哪？

- [ ] [agent/persistence/models.py](agent/persistence/models.py#L30-L100) 前两表
- [ ] [agent/persistence/models.py](agent/persistence/models.py#L332-L435) 会话/消息/run/快照
- [ ] [agent/persistence/database.py](agent/persistence/database.py) 全文件
- [ ] [agent/persistence/repositories/common.py](agent/persistence/repositories/common.py) 全文件
- [ ] [agent/persistence/repositories/sessions.py](agent/persistence/repositories/sessions.py#L110-L191) 消息同步
- [ ] `alembic/versions/0001–0005` 每个读首尾（表名 + 约束）

**可跳过**：eval 4 张表字段逐个看；`repositories/actions.py` 全文。

**验证（需 DB）**

1. `docker compose up -d postgres` → `alembic upgrade head`
2. 设 `PERSISTENCE_TEST_DATABASE_URL` 后跑 `tests/test_persistence_pg_integration.py`
3. `python scripts/check_persistence.py`

---

## 阶段 8｜会话、记忆、恢复（P1，约 45 分钟）

**读完能回答**：重启后会话靠什么还原？memory 打分是什么算法？恢复 API 能续跑到哪？

- [ ] [agent/sessions/manager.py](agent/sessions/manager.py#L55-L160) 会话生命周期
- [ ] [agent/sessions/manager.py](agent/sessions/manager.py#L219-L311) run_sync / cancel / reset / list / rename
- [ ] [agent/sessions/state_store.py](agent/sessions/state_store.py#L38-L181) 序列化与记录组装
- [ ] [agent/memory/store.py](agent/memory/store.py) 全文件
- [ ] [agent/memory/retrieval.py](agent/memory/retrieval.py#L40-L100) 检索打分
- [ ] [api/routes/recovery_route.py](api/routes/recovery_route.py) 续跑流

**可跳过**：recency/access 细节；`_can_access_owner` 权限继承。

**验证**

1. `python -m pytest tests/test_session_manager.py tests/test_state_store.py tests/test_recovery_api.py -q`
2. `python -m pytest tests/test_memory.py tests/test_memory_retrieval.py -q`
3. 对话一轮 → 重启进程 → `curl /api/chat/sessions` 与 `/api/messages/?session_id=...` 回读

---

## 阶段 9｜周边子系统（P2，约 60–90 分钟，按需）

- [ ] 任务图 [orchestration/tasks.py](agent/orchestration/tasks.py)
- [ ] Cron [orchestration/cron.py](agent/orchestration/cron.py#L1-L120) 解析与调度循环
- [ ] 后台任务 [orchestration/background.py](agent/orchestration/background.py#L1-L120)
- [ ] MCP [mcp/registry.py](agent/mcp/registry.py#L1-L124) + [stdio.py](agent/mcp/stdio.py#L1-L80) + [sse.py](agent/mcp/sse.py#L1-L80)
- [ ] 沙箱 [sandbox/manager.py](agent/sandbox/manager.py) + [workspace.py](agent/sandbox/workspace.py)
- [ ] 子代理 [business/integrations.py](agent/tools/business/integrations.py#L10-L60)
- [ ] Eval [evaluation/runner.py](agent/evaluation/runner.py#L1-L120) + [cases.py](agent/evaluation/cases.py) + [baseline.py](agent/evaluation/baseline.py)

**可跳过**：`judge.py` / `scoring.py`（除非要改判分）、`mcp/custom.py` 迁移、`sandbox/cleanup.py`。

**验证**

1. `python -m pytest tests/test_cron.py tests/test_background.py tests/test_task_system.py -q`
2. `python -m pytest tests/test_mcp.py tests/test_sandbox.py -q`
3. `python -m pytest tests/test_evaluation_runner.py tests/test_evaluation_baseline.py tests/test_eval_store.py -q`

---

## 阶段 10｜测试与 CI（P2，约 30 分钟）

- [ ] [pytest.ini](pytest.ini) + [tests/conftest.py](tests/conftest.py) fixture 与隔离方式
- [ ] [.github/workflows/ci.yml](.github/workflows/ci.yml#L17-L71) 两个 job 差异（Windows 全量 vs Ubuntu 带 PG）

**可跳过**：`test_api_schemas.py`、单条断言逐个读。

**验证**：`python -m pytest -q --basetemp=.pytest_tmp`（全绿即基线）。

---

## 优先级取舍

| 级别 | 范围 | 理由 |
|---|---|---|
| **P0** | 阶段 1–5 | 决定"请求是否跑、跑几轮、压缩什么、工具怎么选"，判断系统行为绕不开 |
| **P1** | 阶段 6–8 | 审批是安全核心、数据层是事实来源、会话/恢复决定重启后表现 |
| **P2** | 阶段 9–10 | 周边能力，不读也能解释主链路 |

**完整路径 vs 最短主线**：主线约 2.5–3h，只读 P0；完整路径约 7–9h，并**必须**加做阶段 7 的 DB 验证与阶段 8 的重启验证——这两处读代码看不出，必须跑起来。

---

## 需要当场确认的四个点

| # | 待确认 | 阶段 | 怎么确认 |
|---|---|---|---|
| 1 | target 远程执行通道（SSH？被控机装 agent？） | 5 / 9 | 读 [targets/service.py](agent/targets/service.py#L1-L158) 与 targets/tools.py L455–600 |
| 2 | 子代理是否持有 file 四件套 | 9 | 读 [business/integrations.py](agent/tools/business/integrations.py#L10-L60)，看注入哪个注册表 |
| 3 | eval 判分是否真调 LLM Judge | 9 | 读 [evaluation/judge.py](agent/evaluation/judge.py#L1-L120) |
| 4 | skills 是否预注入 system prompt | 2 / 3 | 读 comprehensive.py 的 `_build_system_prompt`（#L126 之后） |

---

## 与前端无关的边界

- **只碰接口边界**：[frontend/src/api/index.ts](frontend/src/api/index.ts#L65-L119) 可看一眼，理解为什么后端要 `data: {json}\n\n` 且禁缓冲；其余页面/组件/样式一律不读。
- 后端只需记住：`/ui` 由 `StaticFiles` 托管（[api/main.py](api/main.py#L386)），所以后端重启即前端重启，验证时不用单独起 vite。

---

## 30 秒上手命令

```powershell
# 1. 依赖与环境
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env   # 填入 ANTHROPIC_API_KEY / MODEL_ID

# 2. 数据库（阶段 7 前必须）
docker compose up -d postgres
$env:DATABASE_URL="postgresql+psycopg://ai_devops:change-me@127.0.0.1:5432/ai_devops"
alembic upgrade head

# 3. 跑起来
python run.py
curl http://localhost:8000/health
```

建议节奏：先跑通上面 5 条命令，再按阶段 1 开始读——带着"服务已经活着"的状态读代码，比先读后跑更省时间。

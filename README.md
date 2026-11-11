# AI DevOps Agent

一个可本地运行的 **Agent Harness**：模型负责推理和选工具，框架负责工具治理、人工审批、审计、上下文预算、持久化和崩溃恢复。

目标场景是单机运维：看磁盘、查日志、定位进程、改配置、重启服务、跑部署。写操作不会由模型直接落地，而是先生成一条待审批记录，等人点确认后在宿主机执行。

> 设计取向：**治理优先于能力扩张**。工具数量、自治程度都刻意收着，把审批、审计、恢复语义做扎实。当前定位是单进程、单租户的可信环境工具，不是多副本生产平台。

规模（当前代码）：45 个主 Agent 可见工具、18 张 PostgreSQL 表、5 个 Alembic 迁移、206 个测试通过 / 11 个跳过。

---

## 1. 它解决什么问题

给 Agent 一个目标，它自己决定调用哪些工具、看哪些输出、要不要继续查。框架在中间做四件事：

1. **约束**：每个工具都有策略（只读/写/风险等级/是否需审批）；未登记的工具一律按最高风险处理，必须人工批准后才能执行。
2. **留痕**：策略判定、工具调用、审批、恢复都写审计事件，能按 run 或 session 回放。
3. **兜底**：上下文超限有分层压缩，模型报错有重试与降级，进程崩溃有安全点和中断标记。
4. **不重复执行**：崩溃恢复只标记中断，绝不自动重放工具——部署和删除不能因为重启跑两遍。

## 2. 边界（先说清楚，避免误用）

- **单进程**：运行锁、取消事件、MCP 连接、审批等待者都在进程内存里。多副本部署需要额外分布式协调，当前没有。
- **单租户**：身份模型有意简化，权限上下文恒为全量；`required_scopes` 只是声明，不做实际拦截（见 `agent/platform/identity.py`）。
- **不是 OS 级隔离**：`bash` 和 `target_deploy` 以 Agent 进程的权限在宿主机执行。安全边界是「策略 + 审批 + 审计」，不是容器或沙箱。
- **认证是静态 Token**：`API_AUTH_TOKEN` 为空时全部请求按管理员处理，这是本地开发便利，不是可部署默认值。

## 3. 快速开始

### 3.1 依赖

- Python 3.11+
- Node.js 18+（构建前端时需要）
- PostgreSQL 16（业务状态唯一存储）

### 3.2 安装

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 3.3 配置

最小可用配置（`.env`）：

```env
# 模型：任何兼容 Anthropic Messages API 的服务
MODEL_ID=deepseek-chat
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_API_KEY=your-api-key

# 数据库：必须配置，且先跑迁移
DATABASE_URL=postgresql+psycopg://ai_devops:change-me@127.0.0.1:5432/ai_devops

# 本地可以留空；一旦对外提供服务必须设置
API_AUTH_TOKEN=
```

完整配置项见[第 13 节](#13-配置)。

### 3.4 初始化数据库并启动

```bash
alembic upgrade head
python scripts/check_persistence.py   # 确认表结构与连接
python run.py
```

启动后：

```text
API      http://localhost:8000
接口文档  http://localhost:8000/docs
可视化    http://localhost:8000/ui      # 需要先构建前端
健康检查  http://localhost:8000/health
```

`/health` 会返回数据库类型、是否可达、URL 是否已配置，不会暴露密码。数据库不可达时该接口降级，聊天和大部分 `/api/*` 会直接失败——**没有文件存储兜底**。

冒烟一条：

```bash
curl -N -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "看一下磁盘使用率"}'
```

### 3.5 前端

开发模式（热更新，跨端口调 API）：

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

构建后由后端托管：

```bash
cd frontend && npm run build   # 产物输出到 ../static
```

如果启用了认证，需要 `frontend/.env`：

```env
VITE_API_TOKEN=与后端 API_AUTH_TOKEN 相同的值
```

> 该 Token 会打进浏览器产物。只适合本地或可信内网，不能当作公网多用户认证方案。

### 3.6 Docker Compose

```bash
docker compose up --build
```

Compose 会启动 `postgres:16-alpine` 并等待健康检查，然后在 API 容器里先执行 `alembic upgrade head` 再起 Uvicorn。数据库端口只绑定 `127.0.0.1:5432`，数据落在 `postgres_data` 卷。

### 3.7 用独立 PostgreSQL 实例（不用 Docker）

本机没有 PostgreSQL 时，可以用 conda 装一个只监听本地、使用 `trust` 认证的开发实例，仅用于验证：

```bash
conda create -y -p ./pglocal -c conda-forge --override-channels postgresql=16
./pglocal/Library/bin/initdb.exe -D ./pgdata -U postgres -E UTF8 --locale=C -A trust
./pglocal/Library/bin/pg_ctl.exe -D ./pgdata \
  -o "-p 5433 -c listen_addresses=127.0.0.1" -l ./pgdata/server.log start
```

对应 `DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:5433/ai_devops`。`trust` + 本地监听只适合开发机。

---

## 4. 架构

```text
┌─ 入口层  api/ ────────────────────────────────────────────────┐
│  BearerAuthMiddleware → 路由 → SSE / JSON                     │
│  /api/chat/stream 是唯一的主对话入口                          │
└───────────────────────┬───────────────────────────────────────┘
                        │ session_id
┌─ 会话层  agent/sessions/ ─────────────────────────────────────┐
│  Session 缓存（TTL 2h）+ run_lock 串行 + cancel_event          │
│  未命中则从 PostgreSQL 还原消息历史                            │
└───────────────────────┬───────────────────────────────────────┘
                        │
┌─ 运行时  agent/core/ ─────────────────────────────────────────┐
│  pipeline.run_stream():                                       │
│    压缩 → 组 system prompt / 工具池 → 调模型 → 执行工具 → 回填  │
│      ├─ context_manager   系统提示、记忆注入、缓存友好布局      │
│      ├─ context_compact   预算、微压缩、裁剪、摘要              │
│      ├─ tool_loop         策略判定、重定向、审批、模型调用      │
│      └─ error_recovery    429 / 529 / 超长 / 输出上限           │
└───────────────────────┬───────────────────────────────────────┘
                        │ tool_use
┌─ 执行面  agent/tools/ + sandbox/ + targets/ ──────────────────┐
│  ToolExecutor:                                                │
│    只读工具      → 直接执行 + 审计                             │
│    文件工具      → Sandbox 临时工作区（仅子 Agent 持有）        │
│    bash/target_* → 建 PendingAction，等人工批准后宿主执行       │
└───────────────────────┬───────────────────────────────────────┘
                        │
┌─ 状态面  agent/persistence/ ──────────────────────────────────┐
│  18 张表；upsert 做字段 diff + version 乐观锁                  │
│  审批 / Cron / Run 恢复用条件更新（CAS）保证并发安全            │
└───────────────────────────────────────────────────────────────┘
```

关键目录：

| 路径 | 职责 | 主要入口 |
|---|---|---|
| `api/main.py` | 应用装配、对话接口、SSE | `chat_stream` |
| `api/routes/` | 任务、Cron、MCP、审批、审计、恢复、Target 等 REST | 每个文件一个域 |
| `api/auth.py` | Bearer Token 中间件、公开路径 | `BearerAuthMiddleware` |
| `agent/core/pipeline.py` | 推理循环、事件产出、取消与收尾 | `run_stream` |
| `agent/core/tool_loop.py` | 策略判定、审批、工具执行、模型调用 | `_execute_tool_blocks` |
| `agent/core/context_manager.py` | 系统提示组装、记忆召回、压缩调度 | `_compact_if_needed` |
| `agent/core/context_compact.py` | 落盘、预算、微压缩、裁剪、摘要 | `tool_result_budget` 等 |
| `agent/core/error_recovery.py` | 退避、降级、超长恢复、输出扩容 | `call_model_with_recovery` |
| `agent/tools/registry.py` | Schema + Handler 双注册表 | `ToolRegistry` |
| `agent/tools/policy.py` | 每个工具的风险与审批声明 | `get_tool_policy` |
| `agent/orchestration/` | 任务图、Cron、后台任务、审批与执行 | 见第 5.4、9 节 |
| `agent/persistence/` | SQLAlchemy 模型与仓储 | `models.py` |
| `frontend/src/` | React 单页应用（无 router，store 切视图） | `store/useAppStore.ts` |

### 一次对话的完整路径

1. `POST /api/chat/stream` → Bearer 校验 → 取请求身份。
2. `get_or_create_session(session_id)`：内存命中直接用；否则从 `sessions/messages` 还原历史并重建 Agent。
3. 取 `session["run_lock"]`，同一会话串行；`cancel_event.clear()`。
4. `Pipeline` 分配 `run_id`，`create_run` 落库，追加 user 消息（同时增量同步到 `messages` 表）。
5. 每轮：发 `status` → 估算大小并按需压缩 → `thinking` → 组装工具 schema 与 system prompt → 调模型。
6. 模型返回 `tool_use`：`evaluate_tool_policy` 判定。
   - 只读：直接执行，审计 `policy.allowed`。
   - `bash` 且命中专用工具规则：不执行、不建审批，直接回 `Redirected: use xxx`。
   - 需审批：写 `pending_actions`，发 `pending_action` 事件，**在同一个流里阻塞等待**（默认 1800s）。
7. 工具结果按 8000 字符阈值落盘，上下文只保留头尾预览；发 `tool_result`。
8. 无 `tool_use`：把最终文本按词切分发 `text_delta`，再发 `done`。
9. 收尾：更新 run 状态与用量，释放 `run_lock`，释放该 run 的临时任务归属。

取消、异常、超时都会补齐未闭合的工具消息对，避免下一次调用因消息序列非法直接 400。

---

## 5. 工具治理

### 5.1 三层注册

- **Schema**：给模型看的 JSON Schema。
- **Handler**：真正执行。
- **Policy**：`risk_level / read_only / requires_approval / required_scopes / timeout_seconds / idempotent / sandbox_required`。

策略是**集中查表**（`agent/tools/policy.py`），不在工具实现里散落判断。

### 5.2 默认拒绝

| 情况 | 行为 |
|---|---|
| 未登记的工具名 | `HIGH` 风险 + 需审批（fail-closed） |
| 动态 MCP 工具（`mcp__*`） | `HIGH` + 需审批 |
| 已登记只读工具 | 直接执行 |
| 5 个内建写操作 | 需审批：`bash`、`target_write_file`、`target_edit_file`、`target_restart`、`target_deploy` |

### 5.3 Bash 重定向

模型对 `df -h`、`free -h`、`ps aux | grep`、`pgrep`、`ss -tln`、`uptime`、只读 `curl` 有很强的肌肉记忆。这些命令即使批准执行也只是在浪费人工打断，所以在**创建审批之前**先拦一道，返回：

```text
Redirected: use `disk_usage` instead (查看磁盘用量). If it truly cannot cover
this case, retry bash with the command prefixed by `force:`.
```

规则表在 `agent/tools/shell.py` 的 `BASH_REDIRECT_RULES`；`force:` 是显式逃生门。含 `&&` 或 `;` 的复合命令不做重定向。

### 5.4 审批闭环

```text
pending    --confirm-->  confirmed  --执行成功--> executed
pending    --cancel--->  canceled    --执行失败--> failed
confirmed  --cancel--->  canceled
confirmed  --进程重启-->  failed（带 interrupted 标记）
```

- 状态迁移用 `UPDATE ... WHERE status IN (...)` 条件更新，重复点击确认不会执行两次。
- 等待者注册在 `ApprovalCoordinator`，`threading.Event` 每 0.2s 检查一次，同时响应取消。
- 超时（1800s）视为拒绝，动作标 `canceled`，模型收到「未执行」的结果，run 继续往下走而不是崩溃。
- 批准后执行结果写回同一个 run，不需要用户再发一条消息。
- 崩溃时只处理 `confirmed` 的动作；仍是 `pending` 的动作重启后还能通过 API 确认，此时没有等待者，会直接执行并触发一次会话续跑，但已中断的 run 本身不会恢复。

### 5.5 工具结果落盘

单个结果超过 `PERSIST_THRESHOLD = 8000` 字符时，完整内容写到 `DATA_DIR/.task_outputs/tool-results/`，上下文里放路径 + 头尾 `HISTORY_TOOL_LIMIT = 6000` 字符的预览。模型需要细节时可以再读文件，而不是把 10 万字符塞进下一轮。

---

## 6. 上下文与缓存

### 6.1 四层预算

`context_manager._compact_if_needed` 的实际顺序：

| 层 | 触发条件 | 动作 |
|---|---|---|
| `tool_result_budget` | 每轮 | 所有工具结果合计超过 60000 字符时，从最大的开始落盘、替换为「路径 + 预览」，直到总量回到预算内 |
| `micro_compact` | 估算大小 > `CONTEXT_LIMIT = 50000` | 除最近 6 个工具结果外，其余替换为一行摘要 |
| `snip_compact` | 仍 > 50000 | 消息数超过 50 时按配对边界裁掉中段 |
| `trim_by_size` | 每轮兜底 | 超过 `CONTEXT_BYTES_BUDGET = 120000` 时强制裁剪 |

另有两条显式路径：`compact` 工具调用 `compact_history` 做 LLM 摘要；模型报 prompt too long 时走 `error_recovery` 的 `reactive_compact`。

### 6.2 为什么不是「每轮都压缩」

`micro_compact` 会改写中段历史。前缀一变，prompt cache 全部失效，成本和延迟都会上去。所以只有真的越过水位才做有损压缩，`tool_result_budget` 和 `trim_by_size` 这类不改变稳定前缀的操作才可以每轮跑。

同理，时间、记忆检索结果、MCP 连接状态这些**每轮都变**的内容被注入到最后一条 user 消息尾部，system prompt 只保留静态部分。

### 6.3 口径说明

`estimate_size()` 是 `len(json.dumps(messages))`，即 **JSON 字符数**，不是字节数，也不是 token 数。中文内容按 UTF-8 通常是字符数的 3 倍字节。所有阈值都以这个口径为准，日志里出现的 `bytes` 是历史命名，读代码时不要按字节理解。

### 6.4 消息配对

Anthropic 要求 `tool_use` 与 `tool_result` 严格配对，缺一个就整个会话 400。项目在三个位置兜底：

1. 取消时补齐剩余 `tool_result`（用「已取消」占位）。
2. 压缩裁剪只在配对边界切分。
3. 每次调 API 前跑 `_repair_message_sequence` 扫一遍孤儿块。

---

## 7. 错误恢复

| 情况 | 处理 |
|---|---|
| 429 / RateLimit | 指数退避 + 随机抖动，最多 3 次 |
| 529 / Overloaded | 重试；连续 2 次过载且有 `FALLBACK_MODEL_ID` 时切换模型 |
| Prompt 过长 | 依次：结果预算 → 微压缩 → 反应式摘要 → 裁剪，并校验压缩后确实变小 |
| 输出被截断（max_tokens） | 识别后把单次输出预算从 8000 提到 16000，本轮重试 |

`DEFAULT_MAX_TOKENS` / `ESCALATED_MAX_TOKENS` 是代码常量（`agent/platform/config.py`），不是环境变量。

---

## 8. 状态与并发

### 8.1 表

| 域 | 表 |
|---|---|
| 会话与运行 | `sessions`、`messages`、`runs`、`run_snapshots` |
| 审批与审计 | `pending_actions`、`audit_events` |
| 任务 | `tasks`、`task_dependencies` |
| 自动化 | `cron_jobs`、`cron_logs`、`background_tasks` |
| 记忆 | `memories` |
| 运维对象 | `targets` |
| 用量 | `run_usage` |
| 评估 | `eval_batches`、`eval_trials`、`eval_tool_calls`、`eval_scores` |

迁移顺序：`0001` 基础 → `0002` 领域表 → `0003` 自动化 → `0004` 会话与消息 → `0005` 评估表。

### 8.2 三处真正的并发控制

1. **仓储 upsert**：先比字段（`is_distinct_from`），有变化才写，并用 `version` 做乐观锁；无变化不产生写放大。
2. **审批状态迁移**：`UPDATE ... WHERE id = ? AND status IN ('pending')`，返回受影响行数判断是否抢到。
3. **Cron 抢占**：`FOR UPDATE SKIP LOCKED` 按分钟粒度认领，重启或多 worker 不会重复触发。

其余地方（任务图、记忆写回、MCP 连接）仍是进程内锁或「最后写者胜」，不要按强一致理解。

### 8.3 崩溃恢复语义

进程启动时：

1. 仍为 `running` 的 run 标为 `interrupted`，记录中断原因和当时在途的工具。
2. 只有「最后一个安全点没有工具在途」的 run 才允许人工继续。
3. 崩溃时仍在跑的 background task 标失败。
4. 已确认但没执行完的 pending action 标失败。
5. 清理遗留 Sandbox 工作区。

**不会自动重放任何工具。** 恢复接口只从安全点继续对话。

---

## 9. 其他机制

### 9.1 长期记忆

结构化记录：类型、scope、实体、标签、来源、置信度、重要性、生命周期状态。

检索打分（`agent/memory/models.py::_memory_score`）：

```text
0.50 × 词法相关（关键词 + 中文 bigram）
0.25 × 元数据（标签 / 实体 / 类型）
0.10 × 重要性
0.05 × 置信度
0.05 × 新近度
0.05 × 访问频次
```

词法和元数据都为 0 直接不入选；再按 `MEMORY_MIN_SCORE`（默认 0.25）过滤，取 `MEMORY_TOP_K`（默认 5）条。写入前做精确去重，相似度在 `0.85` 以上视为近重复候选，`0.95` 以上自动合并。访问计数按批次刷盘（默认 300s / 20 条）。

没有向量检索。写路径是「整表读入 → 改内存 → 整表 `upsert(force=True)`」；读之前会用 generation 版本号检测并重载外部变更，但并发写仍然是最后写者胜。

### 9.2 任务图

`tasks` + `task_dependencies` 表达 `blockedBy`，任务归属到 session，计划会进入上下文。claim / complete 有状态校验，但依赖环检测和 claim 的 CAS 在数据库层并不完整，复杂依赖图不要指望它自动解死锁。

### 9.3 Cron

- 自实现五字段解析，支持 `*`、`*/n`、范围、列表。
- 调度线程每秒 tick 一次，按分钟截断匹配。
- durable 任务落 `cron_jobs`，用 `FOR UPDATE SKIP LOCKED` 认领；非 durable 任务只在内存，进程重启即丢。
- 执行走单执行器队列，串行执行，结果写 `cron_logs`。

### 9.4 后台任务

`bash` 带 `run_in_background=true`，或命令命中慢操作关键词（`install`、`build`、`test`、`deploy`、`curl`、`rsync` 等）时转后台。worker 完成后结果暂存，在后续轮次由 `collect_background_results` 注入。进程重启时未完成的后台任务标失败。

### 9.5 MCP

四种来源，统一进入动态工具池，工具名格式 `mcp__{server}__{tool}`：

| 类型 | 说明 |
|---|---|
| 内置 mock | 需 `ENABLE_MOCK_MCP=1`，默认关闭，避免伪造部署结果 |
| 自定义 handler | 需 `ENABLE_UNSAFE_MCP_SHELL=1`，会用 `shell=True` 执行模板 |
| stdio | 启动子进程，JSON-RPC over stdin/stdout |
| SSE | 连接远程 HTTP SSE 端点 |

动态工具的策略是 `HIGH` + 需审批。stdio 子进程在断开时清理不彻底，长时间反复连接需要注意僵尸进程。

### 9.6 子 Agent

`spawn_subagent` 派生独立上下文，只给 4 个文件工具（`read_file` / `write_file` / `edit_file` / `glob`），在 Sandbox 工作区副本里操作，最多 30 轮，禁止宿主 shell，也禁止再派生子 Agent。结果以一段文本回传给主 Agent。

---

## 10. SSE 协议

`POST /api/chat/stream` 返回 `text/event-stream`，每行 `data: {json}`：

| type | 关键字段 | 含义 |
|---|---|---|
| `status` | `message`, `turn` | 阶段变化 |
| `thinking` | `turn` | 即将调用模型 |
| `tool_use` | `tool`, `input`, `turn` | 准备执行工具 |
| `tool_result` | `tool`, `output`, `turn`, `duration_ms` | 工具完成 |
| `pending_action` | 动作详情 | 已建审批，等待确认 |
| `text_delta` | `delta` | 最终文本增量 |
| `done` | `text`, `total_turns` | 本轮循环结束 |
| `cancelled` | `text` | 用户取消 |
| `error` | `message` | 不可恢复错误 |

`text_delta` 是拿到完整响应后按词切分推送，**不是模型原生 token 流**。工具调用和状态事件是实时的。

---

## 11. 工具清单（45）

### 内建（24）

| 类别 | 工具 |
|---|---|
| 项目 Target（10） | `target_status` `target_logs` `target_http` `target_list_files` `target_read_file` `target_glob` `target_write_file` `target_edit_file` `target_restart` `target_deploy` |
| Shell（1） | `bash` |
| 服务与系统（6） | `service_status` `system_info` `memory_usage` `cpu_usage` `process_top` `process_search` |
| 磁盘与网络（6） | `disk_usage` `disk_io` `network_interfaces` `port_listen` `ping_host` `http_check` |
| 日志（1） | `system_logs` |

### 业务（21）

| 类别 | 工具 |
|---|---|
| 任务（5） | `create_task` `list_tasks` `get_task` `claim_task` `complete_task` |
| Skill / 子 Agent（3） | `list_skills` `load_skill` `spawn_subagent` |
| 记忆（7） | `add_memory` `approve_memory` `search_memory` `update_memory` `archive_memory` `delete_memory` `restore_memory` |
| 上下文（1） | `compact` |
| Cron（4） | `schedule_cron` `list_crons` `cancel_cron` `list_cron_logs` |
| 后台任务（1） | `list_background_tasks` |

### 仅子 Agent（4，不进入主 Agent 工具目录）

`read_file` `write_file` `edit_file` `glob`

MCP 连接成功后动态追加 `mcp__{server}__{tool}`。

### Target 工具的执行语义

| 工具 | 行为 | 审批 |
|---|---|---|
| `target_status` / `target_logs` / `target_http` / `target_list_files` / `target_read_file` / `target_glob` | 限定在 Target `root` 内只读 | 否 |
| `target_write_file` / `target_edit_file` | 改项目文件，默认保留修改前备份 | 是 |
| `target_restart` | 默认 `systemctl restart <service>`，参数列表执行，不过 shell | 是 |
| `target_deploy` | 在 Target `root` 执行 `deploy_command` | 是 |

`service` 只接受合法 systemd 单元名（字母、数字、`.`、`_`、`@`、`-`）。目录浏览范围由 `TARGET_BROWSE_ROOTS` 限制。

---

## 12. API 端点

### 服务与对话

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 服务信息与工作目录 |
| GET | `/health` | 健康检查（含数据库状态） |
| GET | `/tools` | 内置 + 已连接 MCP 工具 |
| POST | `/api/chat/` | 非流式对话 |
| POST | `/api/chat/stream` | SSE 流式对话 |
| POST | `/api/chat/cancel` | 取消当前会话执行 |
| GET | `/api/messages/` | 可见消息 |
| GET | `/api/chat/sessions` | 会话列表 |
| POST | `/api/chat/sessions/{session_id}/rename` | 重命名会话 |
| POST | `/api/reset/` | 重置会话 |

### 审批 / 记忆 / 审计 / 恢复 / Sandbox

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/actions/pending` | 待审批与执行记录 |
| GET | `/api/actions/pending/{action_id}` | 单条详情 |
| POST | `/api/actions/pending/{action_id}/confirm` | 批准并执行 |
| POST | `/api/actions/pending/{action_id}/cancel` | 拒绝 |
| GET | `/api/memory/` | 记忆列表 |
| GET | `/api/memory/{memory_id}` | 记忆详情 |
| POST | `/api/memory/{memory_id}/approve` | 批准候选记忆 |
| GET | `/api/audit/events` | 审计事件 |
| GET | `/api/audit/timeline` | 会话时间线 |
| GET | `/api/audit/runs/{run_id}` | 按 run 查审计 |
| GET | `/api/recovery/runs` | 会话与中断 run |
| GET | `/api/recovery/runs/{run_id}` | 安全点与中断原因 |
| POST | `/api/recovery/runs/{run_id}/resume/stream` | 从安全点继续 |
| GET | `/api/sandboxes/` | 活动 Sandbox |

### 任务 / Cron

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/tasks/` | 列表 |
| POST | `/api/tasks/` | 创建 |
| GET | `/api/tasks/{task_id}` | 详情 |
| POST | `/api/tasks/{task_id}/claim` | 认领 |
| POST | `/api/tasks/{task_id}/complete` | 完成 |
| DELETE | `/api/tasks/{task_id}` | 删除 |
| GET | `/api/cron/` | 定时任务与最近状态 |
| GET | `/api/cron/logs` | 执行日志 |
| POST | `/api/cron/` | 创建 |
| DELETE | `/api/cron/{job_id}` | 取消 |

### MCP / Skill

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/mcp/` | 连接状态与可用服务器 |
| POST | `/api/mcp/connect` | 连接内置 |
| POST | `/api/mcp/disconnect` | 断开 |
| GET | `/api/mcp/tools` | 当前 MCP 工具名 |
| GET | `/api/mcp/custom` | 自定义服务器 |
| POST | `/api/mcp/custom` | 注册自定义 |
| DELETE | `/api/mcp/custom/{name}` | 删除自定义 |
| POST | `/api/mcp/reload` | 重载自定义配置 |
| POST | `/api/mcp/stdio/connect` | 连接 stdio |
| POST | `/api/mcp/stdio/disconnect` | 断开 stdio |
| POST | `/api/mcp/sse/connect` | 连接 SSE |
| POST | `/api/mcp/sse/disconnect` | 断开 SSE |
| GET | `/api/skills` | Skill 列表 |
| GET | `/api/skills/{name}` | Skill 详情 |
| POST | `/api/skills/reload` | 重新扫描 |

### Target

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/targets/browse` | 服务端目录浏览（受 `TARGET_BROWSE_ROOTS` 限制） |
| GET | `/api/targets/` | 列表 |
| POST | `/api/targets/` | 创建 |
| GET | `/api/targets/{target_id}` | 详情 |
| PATCH | `/api/targets/{target_id}` | 修改 |
| DELETE | `/api/targets/{target_id}` | 删除 |
| POST | `/api/targets/{target_id}/activate` | 绑定到当前会话 |

### 认证

设置 `API_AUTH_TOKEN` 后，`/api/*` 与 `/tools` 需要：

```http
Authorization: Bearer <token>
```

公开路径：`/`、`/health`、`/docs`、`/redoc`、`/openapi.json`、`/ui`。

---

## 13. 配置

| 变量 | 默认 | 说明 |
|---|---|---|
| `MODEL_ID` | `claude-3-5-sonnet-20240620` | 主模型 |
| `ANTHROPIC_BASE_URL` | 空 | 兼容服务地址，空则官方 |
| `ANTHROPIC_API_KEY` | 空 | 也接受 `API_KEY` / `DEEPSEEK_API_KEY` |
| `FALLBACK_MODEL_ID` | 空 | 529 连续过载时的降级模型 |
| `DATA_DIR` | 当前目录 | 运行时数据根目录 |
| `DATABASE_URL` | 空 | PostgreSQL 连接串，**必填** |
| `DB_POOL_SIZE` | 5 | 连接池大小 |
| `DB_MAX_OVERFLOW` | 10 | 溢出连接数 |
| `DB_CONNECT_TIMEOUT` | 5 | 连接超时秒数，避免死库拖住请求 |
| `API_AUTH_TOKEN` | 空 | 空 = 不校验并按管理员处理 |
| `API_AUTH_USER` | `api-user` | Token 对应身份 |
| `API_AUTH_ROLES` | `platform-admin` | 仅用于记忆可见性边界 |
| `SANDBOX_ENABLED` | 1 | 是否启用隔离工作区 |
| `TARGET_BROWSE_ROOTS` | 空 | 允许浏览的服务端目录，逗号分隔 |
| `ENABLE_MOCK_MCP` | 0 | 内置 mock MCP |
| `ENABLE_UNSAFE_MCP_SHELL` | 0 | 自定义 MCP shell handler |
| `ALLOWED_ORIGINS` | 本地 5173/8000 | CORS 来源 |
| `MEMORY_SCOPE` | `global` | 默认记忆作用域 |
| `MEMORY_MIN_SCORE` | 0.25 | 召回最低分 |
| `MEMORY_TOP_K` | 5 | 召回条数 |
| `MEMORY_NEAR_DUP_THRESHOLD` | 0.85 | 近重复阈值 |
| `MEMORY_AUTO_MERGE_THRESHOLD` | 0.95 | 自动合并阈值 |
| `MEMORY_ACCESS_FLUSH_INTERVAL_SECONDS` | 300 | 访问统计刷盘间隔 |
| `MEMORY_ACCESS_FLUSH_BATCH` | 20 | 刷盘批量 |

代码常量（改需改代码）：

| 常量 | 值 | 含义 |
|---|---|---|
| `CONTEXT_LIMIT` | 50000 | 触发压缩的估算大小 |
| `CONTEXT_BYTES_BUDGET` | 120000 | 硬上限 |
| `PERSIST_THRESHOLD` | 8000 | 工具结果落盘阈值 |
| `HISTORY_TOOL_LIMIT` | 6000 | 预览长度 |
| `CONTEXT_SOFT_LIMIT` | 30000 | 软水位，只降级工具结果 |
| `REPEAT_GUARD_LIMIT` | 3 | 同一调用重复执行几次后拦截 |
| `DEFAULT_MAX_TOKENS` | 8000 | 单次输出预算 |
| `ESCALATED_MAX_TOKENS` | 16000 | 截断后扩容值 |
| `MAX_RETRIES` | 3 | 429 重试次数 |
| `MAX_CONSECUTIVE_529` | 2 | 降级触发次数 |

单次 Agent Loop 上限 50 轮（`pipeline.py`），子 Agent 30 轮。

---

## 14. 测试与评估

```bash
pytest -q          # 206 passed, 11 skipped
```

11 个跳过项是需要真实 PostgreSQL 的集成测试，设置后自动启用：

```bash
PERSISTENCE_TEST_DATABASE_URL="postgresql+psycopg://ai_devops:change-me@127.0.0.1:5432/ai_devops" \
  python -m pytest tests/test_persistence_pg_integration.py -q
```

覆盖范围：工具策略与路径约束、取消与消息配对、任务图状态、Cron 解析与调度、MCP JSON-RPC、上下文压缩边界、Session 持久化与 Run 恢复、原子写入。

### 评估

结果表结构在迁移 `0005` 中（`eval_batches` / `eval_trials` / `eval_tool_calls` / `eval_scores`）。试跑器会复制 fixture、创建隔离 Session、按用例策略自动审批、采集工具轨迹并评分。

```bash
python scripts/check_eval_cases.py                      # 校验用例
python scripts/run_eval.py --validate-only              # 只校验不调模型
python scripts/run_eval.py --case inspect-disk-usage    # 跑单个用例
python scripts/run_eval.py --category faq --judge       # 启用 LLM Judge
python scripts/run_eval.py --category core \
  --baseline eval/reports/baseline.json --fail-on-regression
```

评估用例目录 `eval/` 默认不提交（见 `.gitignore`），只保留表结构和示例。干净 clone 上需要自己准备用例才能跑评估。

CI：`.github/workflows/ci.yml` 跑普通测试；`evaluation-regression.yml` 用 baseline/current 报告做回归门禁，接入方式见 `docs/evaluation-ci.md`。

---

## 15. 安全边界与已知限制

**必须先理解的三条**

1. `API_AUTH_TOKEN` 为空时中间件直接放行并赋予管理员身份（`api/auth.py`）。对外提供服务前必须设置。
2. `/api/mcp/stdio/connect` 接受 `command / args / cwd` 并启动子进程，等价于远程命令执行。该接口只应在可信环境暴露，或加前置网关。
3. `ENABLE_UNSAFE_MCP_SHELL=1` 时自定义 MCP 用 `command_template.format(**kwargs)` + `shell=True` 拼命令，参数可控即可注入。

**架构性限制**

- 运行锁、取消事件、审批等待、MCP 连接、Cron 非 durable 任务都是进程内状态，多实例部署会失效。
- `required_scopes` 不生效：`ToolPolicyContext.permissions` 恒为 `"*"`。身份模型是有意简化的单用户模型，不是权限矩阵。
- 审批等待发生在 SSE 请求内部，最长 1800s。等待期间连接被占用，反向代理超时要大于这个值。
- `bash` 以宿主权限执行，`shell=True`；文件工具和 Target 文件工具靠 `resolve + is_relative_to` 限制路径，没有 OS 级隔离。
- 记忆写回是整表覆盖，多进程最后写者胜；检索是词法 + 元数据打分，没有向量语义。
- 上下文大小按 JSON 字符数估算，不是 token 计数；中文会显著低估实际字节。
- `text_delta` 是伪流式（完整响应后按词切分）。
- Sandbox 只在 Run 期间存在，Run 结束即删；不能当持久工作目录。
- 任务依赖图没有环检测，claim 也没有数据库 CAS，复杂图不要依赖自动解死锁。

---

## 16. 文档索引

| 文档 | 内容 | 时效 |
|---|---|---|
| `docs/project-map.md` | 模块地图与职责边界 | 带行号，会随代码漂移 |
| `docs/source-map.md` | 按文件索引关键函数 | 同上 |
| `docs/backend-reading-plan.md` | 7–9 小时后端走读路线 | 稳定 |
| `docs/tool-reference.md` | 工具逐个参数说明 | 以代码为准 |
| `docs/context-compression-reference.md` | 上下文压缩设计与阈值推导 | 稳定 |
| `docs/pitfall-log.md` | 线上/调试踩坑记录（带数字） | 只增不改 |
| `docs/optimization-log.md` | 性能与成本优化记录 | 只增不改 |
| `docs/evaluation-ci.md` | 评估回归门禁接入 | 稳定 |
| `docs/frontend-test-cases.md` | 前端测试用例 | 稳定 |
| `docs/interview-guide.md` 等 | 面试讲解材料 | 非工程文档 |

> 工具数量、端点、默认值以本 README 和代码为准；历史文档中的「44 个工具」「JSON/JSONL 持久化」等描述已过期。

## License

MIT

# AI DevOps Agent

一个基于 Agent Harness 模式的 AI DevOps 助手，通过自然语言完成服务器巡检、故障排查和运维流程编排。

核心是一个“模型推理 -> 工具调用 -> 结果回填”的 Agent Loop。项目集成内置工具、MCP 动态工具、会话隔离、上下文压缩、长期记忆、任务图、后台任务、Cron 调度和 SSE 执行轨迹。

> 当前实现更适合本地开发、学习和可信环境使用。Session 消息和 Run 安全点已经持久化，但活动锁、取消事件和 MCP 连接仍是进程内状态，不是完整的多租户生产系统。

## 核心特性

- **Agent Loop**：最多 50 轮模型调用，支持多轮推理、工具执行和结果回填
- **内置工具系统**：44 个 Agent 可见工具，使用 `Schema + Handler` 双注册表
- **MCP 动态工具池**：支持内置、自定义、stdio 和 SSE MCP，运行时注入 `mcp__server__tool`
- **会话级上下文隔离**：每个 Session 拥有独立 Agent、消息历史、运行锁和取消事件
- **轻量崩溃恢复**：Session 原始消息和 Run 安全点持久化，启动时标记未完成 Run，并支持人工从安全点继续
- **上下文压缩**：大结果持久化、微压缩、消息裁剪、摘要压缩和反应式压缩
- **错误恢复**：429 指数退避、529 模型降级、Prompt 过长恢复和输出 Token 预算扩容
- **任务系统**：支持 Todo 清单和带 `blockedBy` 依赖关系的持久化任务图
- **长期记忆**：结构化 `MemoryRecord`，支持类型、scope、实体、标签、来源、置信度和生命周期管理，提供精确去重、软删除与 JSONL 持久化
- **后台任务**：已批准的慢 Bash 命令异步执行，完成后在后续 Agent 轮次注入结果
- **Cron 调度**：五字段 Cron 解析、持久化任务、单执行器队列和运行日志
- **Skill 与 SubAgent**：按需加载 Markdown Skill，派生独立上下文执行子任务
- **SSE 实时事件**：展示 Agent 状态、工具调用、工具结果、审批通知和最终文本
- **可视化管理界面**：React 页面覆盖聊天、任务、Cron、工具、MCP、Skill、审批、审计和 Sandbox

## 技术栈

- **语言**：Python 3.11+
- **LLM**：Anthropic SDK，可通过 `ANTHROPIC_BASE_URL` 接入兼容 Messages API 的服务
- **后端**：FastAPI + Uvicorn
- **前端**：React 18 + TypeScript + Vite + TailwindCSS + Zustand
- **持久化**：JSON / JSONL 文件，无数据库依赖
- **调度**：自实现五字段 Cron 解析器
- **测试**：pytest + pytest-asyncio
- **部署**：Docker + Docker Compose

## 核心工作流

```text
用户消息
  -> FastAPI Session
  -> ComprehensiveAgent
  -> 组装 System Prompt / 工具 / 记忆 / Skill / MCP
  -> 调用模型
      -> 有 tool_use：由 Tool Policy 统一判断执行方式
          -> 只读巡检：直接执行
          -> 文件 / 子 Agent：在隔离临时工作区中执行
          -> Bash：生成 Pending Action，批准后在宿主机执行
      -> 无 tool_use：生成最终回答
  -> SSE 推送状态和执行轨迹
```

一次聊天请求可能包含多轮模型调用和多次工具调用。Agent Loop 在以下情况结束：

- 模型不再返回 `tool_use`
- 用户取消
- 出现不可恢复错误
- 达到 50 轮安全上限

达到 50 轮不代表业务任务成功，只表示循环被保护性终止。

## 快速开始

### 1. 安装依赖

Windows PowerShell：

```powershell
python -m venv .venv313
.\.venv313\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Linux / macOS：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. 配置环境变量

编辑项目根目录的 `.env`：

```env
MODEL_ID=deepseek-chat
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_API_KEY=your-api-key
FALLBACK_MODEL_ID=

DATA_DIR=
MEMORY_SCOPE=global
MEMORY_MIN_SCORE=0.25
MEMORY_TOP_K=5
MEMORY_NEAR_DUP_THRESHOLD=0.85
MEMORY_AUTO_MERGE_THRESHOLD=0.95
MEMORY_ACCESS_FLUSH_INTERVAL_SECONDS=300
MEMORY_ACCESS_FLUSH_BATCH=20
API_AUTH_TOKEN=
API_AUTH_USER=api-user
API_AUTH_ROLES=platform-admin
SANDBOX_ENABLED=1
ENABLE_UNSAFE_MCP_SHELL=0
ENABLE_MOCK_MCP=0
```

主要配置：

| 变量 | 说明 |
|---|---|
| `MODEL_ID` | 主模型 ID |
| `ANTHROPIC_BASE_URL` | Anthropic 兼容服务地址，留空使用官方地址 |
| `ANTHROPIC_API_KEY` | 模型 API Key |
| `FALLBACK_MODEL_ID` | 529 过载时可切换的备用模型 |
| `DATA_DIR` | 运行时数据目录，留空则放在当前工作目录 |
| `MEMORY_SCOPE` | 默认长期记忆作用域 |
| `MEMORY_MIN_SCORE` | 记忆召回最低相关性分数 |
| `MEMORY_TOP_K` | 每次自动召回的最大记忆数量 |
| `MEMORY_NEAR_DUP_THRESHOLD` | 近重复候选阈值 |
| `MEMORY_AUTO_MERGE_THRESHOLD` | 自动合并阈值 |
| `MEMORY_ACCESS_FLUSH_INTERVAL_SECONDS` | 访问统计批量写入间隔 |
| `MEMORY_ACCESS_FLUSH_BATCH` | 访问统计批量写入条数 |
| `API_AUTH_TOKEN` | 可选的 API Bearer Token |
| `API_AUTH_USER` | 当前 API Token 对应的用户 ID |
| `API_AUTH_ROLES` | 当前用户角色；仅用于记忆全局管理和只读边界，不再启用细粒度权限矩阵 |
| `SANDBOX_ENABLED` | 是否启用隔离临时工作区 |
| `TARGET_BROWSE_ROOTS` | 前端服务器目录浏览器允许访问的绝对路径，逗号分隔 |
| `ENABLE_UNSAFE_MCP_SHELL` | 是否允许自定义 MCP Shell Handler，默认关闭 |
| `ENABLE_MOCK_MCP` | 是否启用内置 Mock MCP，默认关闭，避免伪造部署结果 |
| `ALLOWED_ORIGINS` | 逗号分隔的 CORS 来源 |

注意：`DEFAULT_MAX_TOKENS` 和 `ESCALATED_MAX_TOKENS` 当前由代码常量控制，不是 `.env` 配置项。

### 3. 运行时数据目录

设置 `DATA_DIR` 后，任务、记忆、日志和工具结果会集中保存：

```text
DATA_DIR/
├── .cron_logs/
├── .audit/
├── .background/
├── .memory/
├── .sandboxes/
├── .sessions/
├── .runs/
├── .tasks/
├── .task_outputs/
├── .transcripts/
├── .scheduled_tasks.json
└── logs/
```

`DATA_DIR` 只决定应用运行数据的默认位置。Sandbox 文件工具使用隔离的临时工作区副本，不执行容器命令。

`.sessions/` 保存 Session 原始消息，保证刷新页面和后端重启后仍能恢复对话历史。`.runs/` 只保存轻量 Run 状态、阶段和安全点快照，不恢复旧版 Action Router 或完整 Checkpoint。

进程异常退出后，启动恢复会：

1. 将仍为 `running` 的 Run 标记为 `interrupted`。
2. 记录中断原因和中断时正在执行的工具。
3. 只有最后一个安全点没有工具在途时才允许人工继续。
4. 将崩溃时仍在运行的 Background Task 标记为失败。
5. 将已确认但没有完成的 Pending Action 标记为失败。
6. 清理遗留的 Sandbox 临时工作区。

如果进程在工具执行期间崩溃，系统不会自动重放该工具，避免重复执行 Bash、部署或删除操作。

### 4. 启动后端

```bash
python run.py
```

### 5. 启动前端开发服务器

```bash
cd frontend
npm install
npm run dev
```

如果启用了 API 认证，还需要创建 `frontend/.env`：

```env
VITE_API_TOKEN=与后端 API_AUTH_TOKEN 相同的值
```

### 6. 构建前端并由后端托管

```bash
cd frontend
npm run build
cd ..
python run.py
```

构建结果输出到 `static/`，通过以下地址访问：

```text
http://localhost:8000/ui
```

### 7. Docker Compose

```bash
docker compose up --build
```

默认端口：

```text
API：http://localhost:8000
API 文档：http://localhost:8000/docs
可视化界面：http://localhost:8000/ui
```

Sandbox 不再创建 Docker 容器，也不再提供容器内命令执行能力。它只负责把源工作区复制到隔离目录，供 `read_file`、`write_file`、`edit_file`、`glob` 和子 Agent 使用；Run 结束后自动删除工作区。已批准的 Bash 直接在 Target 宿主机执行。

## 工具执行策略

所有工具调用先经过同一个 `Tool Policy`：

| 类型 | 策略 |
|---|---|
| CPU、内存、磁盘、进程、网络等只读巡检 | 直接执行并记录审计 |
| `target_status`、`target_logs`、`target_http`、`target_list_files`、`target_read_file`、`target_glob` | 在 Session 当前选中的项目根目录内只读执行 |
| `target_write_file`、`target_edit_file` | 修改项目文件，创建 Pending Action 并等待审批，默认保存修改前备份 |
| `target_restart`、`target_deploy` | 在项目根目录执行，创建 Pending Action 并等待审批 |
| `read_file`、`write_file`、`edit_file`、`glob` | 仅注册给 Subagent 内部使用，不进入主 Agent 工具目录 |
| `spawn_subagent` | 子 Agent 只允许使用上述 Sandbox 文件工具，禁止宿主 Bash |
| `bash` | 创建 Pending Action，用户批准后直接在宿主机执行，默认工作目录为当前 Target 根目录 |
| Memory、Task、Cron、普通 MCP | 按策略执行并记录轻量日志 |

高风险动态 MCP 工具仍会由 Tool Policy 标记为需要审批。这里不再维护 Action Router、Preflight 和跨系统 Run Checkpoint 等重复治理层。

## 运维项目 Target

前端“运维项目”页面通过服务端目录浏览器选择项目目录，目录范围由
`TARGET_BROWSE_ROOTS` 限制。每个 Session 绑定一个当前 Target，Target 配置
持久化在 `DATA_DIR/.targets/targets.json`。

Target 支持以下可选配置：

| 字段 | 用途 |
|---|---|
| `root` | 项目根目录，所有项目文件工具的限制边界 |
| `service` | systemd 服务名，用于状态和重启 |
| `health_url` | 部署或重启后的健康检查 URL |
| `deploy_command` | 审批后执行的部署命令，工作目录为项目根目录 |
| `restart_command` | 自定义重启命令；留空时使用 `systemctl restart <service>` |
| `log_path` | 项目日志文件相对路径，供 `target_logs` 使用 |

`service` 只接受合法 systemd 单元名（字母、数字、`.`、`_`、`@`、`-`）。
默认重启使用参数列表执行，不经过宿主 Shell；自定义 `restart_command` 和
`deploy_command` 会在审批记录中保存并展示完整命令。

## PostgreSQL 持久化

持久化改造保持 JSON 为默认运行方式，并支持可选双写：

```env
PERSISTENCE_BACKEND=json
DATABASE_URL=postgresql+psycopg://ai_devops:change-me@postgres:5432/ai_devops
```

支持三种模式：

| 模式 | 行为 |
|---|---|
| `json` | 保持原有 JSON / JSONL 持久化，不依赖 PostgreSQL |
| `dual` | 继续写 JSON，同时把已接入的领域镜像写入 PostgreSQL |
| `postgres` | 已接入的领域只写 PostgreSQL |

已接入 PostgreSQL 的数据：

- `audit_events`
- `run_usage`
- `targets`
- `tasks` / `task_dependencies`
- `memories`
- `pending_actions`
- `cron_jobs` / `cron_logs`
- `background_tasks`
- `sessions` / `messages`
- `runs` / `run_snapshots`

状态转换（审批确认 / 拒绝 / 执行结果）通过 PostgreSQL 条件更新实现 CAS，
Cron 抢占使用 `FOR UPDATE SKIP LOCKED`，因此多进程和重启都不会重复触发；
数据库不可用时调度器会退回进程内判断，而不是停止调度。

读路径默认仍走本地 JSON，可以按域切换：

```env
PERSISTENCE_READ=postgres
PERSISTENCE_READ_DOMAINS=targets
```

支持切读的域：`targets`、`tasks`、`memories`、`actions`、`sessions`、`runs`。
留空 `PERSISTENCE_READ_DOMAINS` 表示全部切换。数据库不可达时读操作会自动
回退到本地 Store，记录不存在时则按不存在处理，不会把已删除的数据“读回来”。
当前读路由可以从 `GET /health` 的 `persistence` 字段查看。

**本地文件与 PostgreSQL 同时写，这是有意的**：读全部来自数据库，本地文件不再作为
事实来源，而是数据库故障时的写入日志、独立副本与对账参照。关掉本地写入会让"数据库
故障"从"镜像延迟"变成"数据丢失"，所以这条路径（以及对应的开关）在评估后被删除。

数据库自身的备份（与本地文件副本互补）：

```bash
pg_dump --format=custom --file=D:\ai_agent\data\pg-backups\ai_devops-YYYYmmdd.dump \
  "postgresql://ai_devops:change-me@127.0.0.1:5433/ai_devops"
```

`GET /health` 的 `persistence.mirror` 给出镜像写的健康度：

```json
{"enabled": true, "totals": {"calls": 65, "failures": 0, "skipped": 0}}
```

`failures` 是抛异常的尝试（数据库不可达、约束冲突），`skipped` 是 repository
拒绝的记录（数据本身不合法），后者是 `calls` 的子集。判断双写是否稳定看
`failures` 是否为 0。

切读期间建议打开灰度双读：每次单条查询都会再读一遍本地 Store 做对比，只报告
不改变返回值，专门覆盖过滤器、归属判断、一侧缺失这类定期对账看不到的问题。

```env
PERSISTENCE_SHADOW=1
PERSISTENCE_SHADOW_COOLDOWN_SECONDS=60
```

`GET /health` 会返回 `shadow_checks` / `shadow_mismatches` / `shadow_last_mismatch`，
不一致时写 `persistence.shadow.mismatch` 审计事件（high 级，按域冷却）。

读取路径仍然走 JSON，PostgreSQL 目前是影子副本；切换读取属于后续阶段，
在一致性校验完成前不要把 `dual` 改成 `postgres`。

Redis 将放到下一阶段，用于运行锁、取消信号、审批唤醒和任务租约，
当前不进入第一轮依赖和 Compose。

启动 PostgreSQL：

```bash
docker compose up -d postgres
```

创建数据库表：

```bash
alembic upgrade head
```

检查连接状态：

```bash
python scripts/check_persistence.py
```

把历史 `events.jsonl` 幂等导入 PostgreSQL：

```bash
python scripts/migrate_audit_to_postgres.py
```

把 Domain 与自动化域的 JSON 数据幂等导入 PostgreSQL：

```bash
python scripts/migrate_store_to_postgres.py --domain all
```

可选域：`targets`、`tasks`、`memories`、`actions`、`cron`、`background`、`sessions`、`runs`。

切换读取之前必须先在真实数据库上跑一致性对账，它只读不修复：

```bash
PERSISTENCE_BACKEND=dual python scripts/check_persistence_consistency.py
```

退出码为 0 表示 JSON 与 PostgreSQL 没有漂移；非 0 会列出缺失与内容不一致的记录。

发现漂移后的修复命令（`--force` 会忽略 `updated_at` 判据，重写每一行）：

```bash
python scripts/migrate_store_to_postgres.py --domain memories --force
```

双写模式下还会启动一个后台巡检线程（默认 900 秒一次，可用
`PERSISTENCE_CONSISTENCY_INTERVAL_SECONDS=0` 关闭），只在漂移域集合发生变化时
写审计事件，避免刷日志。

### 写路径覆盖验证

单元测试证明映射逻辑正确，但不能证明"每条真实写路径都走到了镜像"。这个脚本把
每个域的写操作真跑一遍（建/改/删/状态流转），再按 key 逐个确认记录进了 PostgreSQL：

```bash
python scripts/verify_persistence_coverage.py \
  --database-url postgresql+psycopg://ai_devops:change-me@127.0.0.1:5433/ai_devops
```

默认把本地数据写进系统临时目录，并在结束时删掉本次创建的镜像行，跑完数据库保持原样
（`--keep-records` / `--keep-data` 可以保留现场）。覆盖 10 个域、50+ 个写操作，
输出里 `ok: true` 表示每条写路径都进了镜像。

脚本会在 PostgreSQL 里创建并随后删除一个独立的 `coverage_<随机>` schema：覆盖过程
包含"把所有非终态 run 标为中断""把所有 confirmed 审批标为失败""归档最老的记忆"这类
全局操作，跑在真实 schema 上会改写用户数据。`--keep-schema` 可以保留现场排查，
`--schema` 可以指定固定 schema 名。

### 本地 PostgreSQL（不用 Docker）

如果本机没有可用的 PostgreSQL，可以装一份独立的、不进系统服务的实例：

```powershell
conda create -y -p D:\pglocal -c conda-forge --override-channels postgresql=16
D:\pglocal\Library\bin\initdb.exe -D D:\ai_agent\data\pg-local -U postgres -E UTF8 --locale=C -A trust
D:\pglocal\Library\bin\pg_ctl.exe -D D:\ai_agent\data\pg-local -o "-p 5433 -c listen_addresses=127.0.0.1" -l D:\ai_agent\data\pg-local\server.log start
```

建库并跑迁移：

```bash
DATABASE_URL=postgresql+psycopg://ai_devops:change-me@127.0.0.1:5433/ai_devops alembic upgrade head
```

停止与启动：

```powershell
D:\pglocal\Library\bin\pg_ctl.exe -D D:\ai_agent\data\pg-local stop
D:\pglocal\Library\bin\pg_ctl.exe -D D:\ai_agent\data\pg-local -o "-p 5433 -c listen_addresses=127.0.0.1" start
```

这个实例用 `trust` 认证、只监听 `127.0.0.1`，仅适合本机开发验证，不要当成部署方案。
集成测试通过环境变量启用：

```bash
PERSISTENCE_TEST_DATABASE_URL="postgresql+psycopg://ai_devops:change-me@127.0.0.1:5433/ai_devops" \
  python -m pytest tests/test_persistence_pg_integration.py -q
```

项目自带的 `docker-compose.yml` 仍然以 `postgres:16-alpine` 为准，两种方式不要同时用。

需要真实数据库的集成测试（未设置环境变量时自动跳过）：

```bash
PERSISTENCE_TEST_DATABASE_URL="postgresql+psycopg://ai_devops:change-me@127.0.0.1:5432/ai_devops" \
  python -m pytest tests/test_persistence_pg_integration.py -q
```

## API 认证

当 `.env` 中设置：

```env
API_AUTH_TOKEN=my-secret-token
```

以下接口需要：

```http
Authorization: Bearer my-secret-token
```

受保护范围包括 `/api/*` 和 `/tools`。

公开路径：

```text
/
/health
/docs
/redoc
/openapi.json
/ui
```

curl 示例：

```bash
curl http://localhost:8000/tools \
  -H "Authorization: Bearer my-secret-token"
```

`VITE_API_TOKEN` 会进入浏览器构建产物，只适合本地或可信内网，不应作为公网多用户系统的长期认证方案。

## API 端点

### Agent 对话

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 服务信息和工作目录 |
| GET | `/health` | 健康检查 |
| GET | `/tools` | 列出内置与已连接 MCP 工具 |
| POST | `/api/chat/` | 非流式 Agent 对话 |
| POST | `/api/chat/stream` | SSE 流式 Agent 对话 |
| POST | `/api/chat/cancel` | 取消指定 Session 的当前执行 |
| GET | `/api/messages/` | 获取 Session 可见消息 |
| POST | `/api/reset/` | 重置指定 Session |

### 审批、记忆、审计与 Sandbox

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/actions/pending` | 查询待审批和执行记录 |
| POST | `/api/actions/pending/{id}/confirm` | 批准并执行 |
| POST | `/api/actions/pending/{id}/cancel` | 拒绝动作 |
| GET | `/api/memory/` | 查询当前身份可见的长期记忆 |
| POST | `/api/memory/{id}/approve` | 批准候选记忆 |
| GET | `/api/audit/events` | 查询审计事件 |
| GET | `/api/audit/timeline` | 查询 Session 时间线 |
| GET | `/api/sandboxes/` | 查询活动 Sandbox |
| GET | `/api/recovery/runs` | 查询 Session 和中断 Run |
| GET | `/api/recovery/runs/{id}` | 查看安全点和中断原因 |
| POST | `/api/recovery/runs/{id}/resume/stream` | 从安全点手动继续 |

### 任务管理

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/tasks/` | 列出任务 |
| POST | `/api/tasks/` | 创建任务 |
| GET | `/api/tasks/{id}` | 查看任务 |
| DELETE | `/api/tasks/{id}` | 删除任务 |
| POST | `/api/tasks/{id}/claim` | 认领任务 |
| POST | `/api/tasks/{id}/complete` | 完成任务 |

### Cron 调度

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/cron/` | 列出定时任务及最近执行状态 |
| GET | `/api/cron/logs` | 查询 Cron 执行日志 |
| POST | `/api/cron/` | 创建定时任务 |
| DELETE | `/api/cron/{id}` | 取消定时任务 |

### Skill

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/skills` | 列出 Skill |
| GET | `/api/skills/{name}` | 查看 Skill 详情 |
| POST | `/api/skills/reload` | 重新扫描 Skill |

### MCP

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/mcp/` | 列出 MCP Server 和连接状态 |
| POST | `/api/mcp/connect` | 连接内置 MCP Server |
| POST | `/api/mcp/disconnect` | 断开内置 MCP Server |
| GET | `/api/mcp/tools` | 列出当前 MCP 工具 |
| POST | `/api/mcp/custom` | 注册自定义 MCP Server |
| GET | `/api/mcp/custom` | 列出自定义 MCP Server |
| DELETE | `/api/mcp/custom/{name}` | 删除自定义 MCP Server |
| POST | `/api/mcp/reload` | 重新加载自定义 MCP 配置 |
| POST | `/api/mcp/stdio/connect` | 连接 stdio MCP Server |
| POST | `/api/mcp/stdio/disconnect` | 断开 stdio MCP Server |
| POST | `/api/mcp/sse/connect` | 连接 SSE MCP Server |
| POST | `/api/mcp/sse/disconnect` | 断开 SSE MCP Server |

## SSE 事件

`/api/chat/stream` 返回 `text/event-stream`，事件数据为 JSON：

```text
status       当前阶段和轮次
thinking     开始模型调用
tool_use     准备执行工具
tool_result  工具执行完成
pending_action 已创建待审批动作
text_delta   最终文本增量
done         当前 Agent Loop 完成
cancelled    用户取消
error        错误事件
```

示例：

```bash
curl -N -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "检查磁盘空间"}'
```

当前 `text_delta` 是拿到完整模型响应后按词拆分发送，不是模型原生 Token Streaming。工具调用和状态事件是实时产生的。

## 主 Agent 工具（44 个）

| 类别 | 工具 |
|---|---|
| 项目 Target | `target_status` `target_logs` `target_http` `target_list_files` `target_read_file` `target_glob` `target_write_file` `target_edit_file` `target_restart` `target_deploy` |
| Shell | `bash` |
| 服务与系统 | `service_status` `system_info` `memory_usage` `cpu_usage` `process_top` `process_search` |
| 磁盘与网络 | `disk_usage` `disk_io` `network_interfaces` `port_listen` `ping_host` |
| 日志 | `system_logs` |
| 任务 | `create_task` `list_tasks` `get_task` `claim_task` `complete_task` |
| Skill / SubAgent | `list_skills` `load_skill` `spawn_subagent` |
| 记忆 | `add_memory` `search_memory` `update_memory` `archive_memory` `delete_memory` `restore_memory` |
| 上下文 | `compact` |
| Cron | `schedule_cron` `list_crons` `cancel_cron` `list_cron_logs` |
| 后台任务 | `list_background_tasks` |

MCP 连接成功后，还会动态增加 `mcp__{server}__{tool}` 工具。

## 上下文与错误恢复

自动上下文控制顺序：

```text
tool_result_budget
  -> micro_compact
  -> 超过 CONTEXT_LIMIT 时 snip_compact
```

完整恢复策略包括：

1. 大工具结果持久化，上下文中保留路径和预览
2. 旧工具结果微压缩
3. 消息头尾保留和中段裁剪
4. `compact` 显式摘要压缩
5. Prompt 过长后的反应式摘要压缩

错误恢复：

- 429 / RateLimit：指数退避和随机抖动
- 529 / Overloaded：重试，连续过载可切换 `FALLBACK_MODEL_ID`
- Prompt 过长：执行有上限的上下文恢复，包含大结果预算、微压缩、反应式摘要和裁剪，并验证压缩是否有效
- 输出 Token 限制：单独识别并在允许时将最大输出预算从 8000 提升到 16000

`estimate_size()` 使用 JSON 字符长度近似上下文大小，不是精确 Token 计数。

## 项目结构

```text
ai-devops-agent/
├── agent/
│   ├── core/
│   │   ├── comprehensive.py    # Agent facade 和依赖组装
│   │   ├── agent_runtime.py    # Runtime Mixin 组合入口
│   │   ├── pipeline.py         # 推理循环和运行事件
│   │   ├── persistence.py      # Session / Run 安全点持久化
│   │   ├── tool_loop.py        # 工具策略、审批和模型调用
│   │   ├── context_manager.py  # Prompt、记忆召回和上下文压缩
│   │   ├── context_compact.py  # 上下文预算、裁剪和摘要
│   │   ├── error_recovery.py   # 重试、降级和 Token 扩容
│   ├── tools/
│   │   ├── registry.py         # Schema + Handler + Policy 注册表
│   │   ├── executor.py         # 宿主、Sandbox、审批工具执行入口
│   │   ├── policy.py           # 工具执行策略
│   │   ├── business/           # 业务工具按领域拆分
│   │   │   ├── tasks.py
│   │   │   ├── knowledge.py
│   │   │   ├── memory.py
│   │   │   ├── automation.py
│   │   │   └── integrations.py
│   │   ├── file_tools.py       # 文件工具
│   │   ├── shell.py            # Bash 工具
│   │   └── ops.py              # 运维工具
│   ├── sessions/
│   │   ├── manager.py          # Session 生命周期、TTL、锁和恢复
│   │   ├── state_store.py      # Session 与 Run 安全点持久化
│   │   └── messages.py         # 可见消息序列化
│   ├── memory/
│   │   ├── models.py           # Memory 模型、校验和评分
│   │   ├── store.py            # JSONL 持久化和访问统计
│   │   ├── retrieval.py        # 检索、相关性和格式化
│   │   ├── lifecycle.py        # 新增、更新、归档、删除和合并
│   │   ├── service.py          # MemorySystem 组合入口
│   │   └── policy.py           # Memory 作用域和所有权规则
│   ├── mcp/
│   │   ├── registry.py         # MCP Client 和动态工具池
│   │   ├── builtin.py          # 内置 Mock MCP
│   │   ├── custom.py           # 自定义 MCP Handler
│   │   ├── stdio.py            # stdio JSON-RPC
│   │   ├── sse.py              # SSE JSON-RPC
│   │   └── client.py           # 兼容门面
│   ├── sandbox/
│   │   ├── models.py           # Sandbox 工作区模型和异常
│   │   ├── workspace.py        # 工作区隔离和路径约束
│   │   ├── cleanup.py          # 孤儿工作区清理
│   │   └── manager.py          # Sandbox 工作区生命周期
│   ├── orchestration/
│   │   ├── tasks.py            # 持久化依赖任务图
│   │   ├── cron.py             # Cron 调度和日志
│   │   ├── background.py       # 后台任务
│   │   ├── pending_actions.py  # 待审批动作持久化
│   │   └── pending_executor.py # 审批后的统一执行
│   ├── observability/
│   │   ├── audit.py            # 审计事件
│   │   └── logger.py           # 日志
│   ├── platform/
│   │   ├── config.py           # 环境配置和路径
│   │   ├── storage.py          # 原子写入
│   │   ├── identity.py         # 用户身份模型
│   │   └── skill.py            # Skill 扫描和加载
│   └── extensions/
│       └── subagent.py         # 子 Agent
├── api/
│   ├── main.py                 # FastAPI 入口
│   ├── auth.py                 # API Bearer Token 中间件
│   ├── schemas.py              # Pydantic 请求模型
│   └── routes/
│       ├── task.py
│       ├── cron_route.py
│       ├── mcp_route.py
│       ├── skill_route.py
│       ├── action_route.py
│       ├── memory_route.py
│       ├── audit_route.py
│       ├── recovery_route.py
│       └── sandbox_route.py
├── frontend/
│   ├── src/api/
│   ├── src/components/
│   ├── src/pages/              # 聊天、任务、审批、审计、工作区等页面
│   ├── src/store/
│   └── src/types/
├── mcp_servers/
├── skills/
├── tests/
├── static/                     # 前端构建产物
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── pytest.ini
├── run.py
└── .env.example
```

## 使用示例

### Agent 对话

```bash
curl -X POST http://localhost:8000/api/chat/ \
  -H "Content-Type: application/json" \
  -d '{"message": "列出当前目录下所有 Python 文件"}'
```

### 创建任务

```bash
curl -X POST http://localhost:8000/api/tasks/ \
  -H "Content-Type: application/json" \
  -d '{
    "subject": "每日服务器巡检",
    "description": "检查磁盘、内存和 CPU",
    "priority": "high"
  }'
```

### 创建 Cron 任务

```bash
curl -X POST http://localhost:8000/api/cron/ \
  -H "Content-Type: application/json" \
  -d '{
    "cron": "0 9 * * 1-5",
    "prompt": "执行每日服务器巡检",
    "recurring": true,
    "name": "工作日巡检"
  }'
```

## 测试

### Agent 评估（数据层）

评估结果的表结构已包含在迁移里（`eval_batches` / `eval_trials` /
`eval_tool_calls` / `eval_scores`），建议跑在独立的 `ai_devops_eval` 数据库上。
用例库与执行器暂未纳入本仓库。

```bash
pytest -q
```

测试覆盖：

- 权限和路径检查
- 会话取消与工具消息配对
- 任务图状态和依赖
- Cron 解析、调度、持久化和日志
- MCP JSON-RPC 和并发串行
- 上下文压缩安全边界
- 消息序列化
- Session 持久化、Run 安全点和启动恢复
- 文件原子写入
- 安全加固

部分 API 集成测试依赖 FastAPI 环境，未安装相关依赖时会自动跳过。

## 已知限制

- Session 消息和 Run 安全点会持久化，但活动取消事件、运行锁和 MCP 连接仍保存在进程内存中
- 只有不在工具执行中的安全点允许人工继续；工具在途时只标记中断，不自动重放
- 启动恢复按单实例 DATA_DIR 设计，多实例共享目录需要增加分布式租约
- 任务、记忆和 MCP 连接仍包含进程级全局状态
- 记忆检索以关键词、中文 bigram、标签、实体和元数据排序为主，尚未接入向量语义检索
- 记忆仅做精确内容去重，语义相近记录仍需后续合并策略
- Cron 去重只保证单进程范围，多实例需要分布式租约
- `cancel_event` 不能抢占正在运行的同步工具
- Shell 和 MCP 由 Tool Policy、审批和审计治理，不是操作系统级隔离
- `VITE_API_TOKEN` 会进入浏览器产物，不适合公网多用户认证
- 上下文按字符近似计算，不是精确 Token 计数

## License

MIT

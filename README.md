# AI DevOps Agent

一个面向受信基础设施环境的 AI 运维 Agent 运行时。系统将自然语言任务转换为可观测的模型-工具循环，并在工具权限、人工审批、项目边界、状态持久化和执行恢复上提供工程化约束。

## 项目定位

AI DevOps Agent 不是通用聊天界面，而是一个可审计的运维执行框架，主要解决以下问题：

- 将服务器巡检、日志分析、配置修改、服务重启和部署等操作统一到 Agent 工作流。
- 对工具调用实施统一策略，区分只读操作、写入操作和高风险操作。
- 将每个会话绑定到明确的运维项目目录，并对项目文件操作实施路径约束。
- 对高风险操作引入人工审批，并记录完整审计轨迹。
- 在进程重启后恢复 Session、Run 和模型上下文，同时避免自动重放非幂等工具。
- 通过版本化评估用例验证 Prompt、模型和工具策略变更。

当前实现适用于可信的本地环境、单机部署和私有网络。它尚未实现多租户隔离、分布式执行或操作系统级安全沙箱。

## 核心能力

### Agent Runtime

- Anthropic Messages API 兼容调用，可通过 `ANTHROPIC_BASE_URL` 接入兼容服务。
- 最多 50 轮模型/工具循环，支持多工具调用、工具结果回填和取消。
- 针对 `429`、`529`、Prompt 超长和输出 Token 不足提供恢复策略。
- 同一 Run 内完全相同的工具调用默认在第 3 次执行前拦截，避免无效循环。
- 支持子 Agent，独立上下文只返回摘要，降低主会话上下文压力。

### 工具治理

- Schema、Handler 和 Policy 在统一 Registry 中注册。
- 只读巡检工具默认直接执行。
- Bash、文件修改、服务重启、部署及高风险 MCP 工具进入 Pending Action 审批流程。
- Bash 的常见只读巡检命令会重定向到结构化专用工具。
- 项目文件访问限制在 active Target 根目录内，默认阻止 `.env`、凭证和私钥文件。
- 工具策略判定、调用结果和审批状态写入审计事件。

### 状态与恢复

- PostgreSQL 是唯一业务状态存储。
- 完整会话历史与模型上下文分离保存。
- Run 在模型调用前保存安全点；工具执行期间标记为不可自动恢复。
- 进程异常退出后，运行中的 Run 标记为 `interrupted`，不会自动重放工具。
- 审批、Cron 认领和 Run 恢复使用数据库条件更新或行锁，支持基本并发控制。

### 上下文管理

- 上下文 JSON 文本不超过 30,000 字符时保持原样。
- 30,000 至 50,000 字符之间只降级大型工具结果，不调用摘要模型。
- 超过 50,000 字符时生成检查点交接摘要，只替换模型上下文。
- 摘要失败时直接开启新窗口，保留本轮目标和近期用户原话。
- 完整前端会话历史不会因上下文压缩而被覆盖。
- 压缩前 transcript 持久化到 `DATA_DIR/.transcripts/`。

### 运维自动化

- Target 管理：项目根目录、systemd 服务、健康检查、部署和重启命令。
- 任务图：任务依赖、认领、完成和 Run 归属。
- 长期 Memory：作用域、标签、实体、访问计数、归档和去重。
- Cron：持久化五字段 Cron 任务、跨进程认领和执行日志。
- 后台任务：慢命令异步执行，结果在后续 Agent 轮次注入。
- MCP：支持 built-in、custom、stdio 和 SSE 连接。
- Skill：从 `skills/` 目录按需加载 Markdown 运维知识。

### 评估

- 版本化 YAML 用例和隔离 fixture。
- 验证工具选择、运行状态、审批、文件结果、答案、成本和耗时。
- 支持多 Trial、并发执行和 LLM Judge。
- 支持 Wilson 置信区间和显著性感知的回归门禁。
- 前端提供批次报告、用例下钻、工具轨迹和基线对比。

## 系统架构

```text
Browser
  |
  v
FastAPI / Bearer Auth / SSE
  |
  v
SessionManager
  +-- complete history
  +-- model context
  +-- run lock
  +-- cancellation
  |
  v
ComprehensiveAgent
  +-- ContextManager
  +-- ToolLoop
  +-- ErrorRecovery
  +-- RunPersistence
  |
  +--> ToolPolicy --> ToolExecutor
  |       |              |
  |       |              +--> Target tools
  |       |              +--> Host Bash
  |       |              +--> Sandbox workspace
  |       |              +--> MCP
  |       |
  |       +--> approval / denial / audit
  |
  +--> PostgreSQL
          +-- sessions / messages
          +-- session_contexts
          +-- runs / run_snapshots
          +-- pending_actions
          +-- tasks / memories / cron
          +-- audit_events / run_usage
          +-- evaluation tables
```

### 一次对话的执行路径

1. 请求通过 API Bearer Token 校验。
2. SessionManager 加载完整历史、模型上下文和 active Target。
3. 用户消息追加到 Session 历史与模型上下文。
4. Run 创建安全点并开始模型循环。
5. 每轮按阈值检查上下文，再调用模型。
6. 工具调用经过统一 Policy：
   - 只读工具直接执行。
   - 高风险工具创建 Pending Action 并等待审批。
   - 拒绝或超时不会执行工具。
7. 工具结果追加到模型上下文和完整历史。
8. 最终响应通过 SSE 返回，Run 和用量状态落库。

## 快速开始

### 前置依赖

- Python 3.11+
- PostgreSQL 16+
- Node.js 18+（仅前端构建）
- Docker 与 Docker Compose（可选）

### 1. 安装后端依赖

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Linux/macOS：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

### 2. 配置环境

至少配置模型凭据和 PostgreSQL：

```env
MODEL_ID=deepseek-chat
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_API_KEY=your-api-key

DATABASE_URL=postgresql+psycopg://ai_devops:change-me@127.0.0.1:5432/ai_devops
API_AUTH_TOKEN=replace-with-a-long-random-token
TARGET_BROWSE_ROOTS=/opt,/srv
```

`TARGET_BROWSE_ROOTS` 必须是绝对路径，多个目录以逗号分隔。Windows 环境可使用 `D:\Projects,E:\Services`。该变量为空时，目录浏览和 Target 创建不可用。

### 3. 初始化数据库

```bash
alembic upgrade head
python scripts/check_persistence.py
```

当前迁移头为：

```text
0006_session_contexts
```

### 4. 启动后端

```bash
python run.py
```

默认地址：

```text
API:      http://localhost:8000
OpenAPI:  http://localhost:8000/docs
UI:       http://localhost:8000/ui
Health:   http://localhost:8000/health
```

如果尚未构建前端，`/ui` 不可用。

### 5. 构建前端

```bash
cd frontend
npm ci
npm run dev
```

Vite 开发服务器默认通过 `5173` 端口代理到后端 `8000`。

如果后端设置了 `API_AUTH_TOKEN`，在 `frontend/.env.local` 中配置相同的 Token：

```env
VITE_API_TOKEN=replace-with-a-long-random-token
```

该值会被编译进浏览器产物，只适用于可信内网或本地环境。对外部署应在网关层实现登录和访问控制。

生产构建：

```bash
cd frontend
npm run build
cd ..
python run.py
```

构建产物输出到 `static/`，由 FastAPI 挂载到 `/ui`。

### 6. Docker Compose

```bash
docker compose up --build
```

Compose 会启动 API 和 PostgreSQL，并在 API 启动前执行 Alembic 迁移。容器内访问数据库时，`DATABASE_URL` 的主机名应为 `postgres`，不能使用宿主机地址 `127.0.0.1`。

Compose 不包含前端构建步骤。需要 `/ui` 页面时，先在宿主机执行 `cd frontend && npm ci && npm run build`，再启动 Compose。

## 配置项

| 变量 | 必填 | 说明 |
|---|---|---|
| `MODEL_ID` | 是 | 主模型 ID |
| `ANTHROPIC_API_KEY` | 是 | Anthropic Messages API 兼容服务密钥 |
| `ANTHROPIC_BASE_URL` | 否 | 第三方兼容服务地址 |
| `FALLBACK_MODEL_ID` | 否 | `529` 连续过载时使用的备用模型 |
| `DATABASE_URL` | 是 | PostgreSQL SQLAlchemy URL |
| `DATA_DIR` | 否 | transcript、工具结果、Sandbox 和日志目录 |
| `API_AUTH_TOKEN` | 对外部署必填 | API Bearer Token；为空时不进行身份校验 |
| `API_AUTH_USER` | 否 | Token 对应的用户 ID |
| `API_AUTH_ROLES` | 否 | API 身份角色，目前仅用于 Memory 可见性边界 |
| `TARGET_BROWSE_ROOTS` | 是* | 可浏览和绑定的项目根目录 |
| `SANDBOX_ENABLED` | 否 | 是否启用临时工作区 |
| `ENABLE_UNSAFE_MCP_SHELL` | 否 | 是否允许自定义 MCP Shell Handler |
| `ENABLE_MOCK_MCP` | 否 | 是否加载内置 Mock MCP Server |
| `ALLOWED_ORIGINS` | 否 | CORS 允许来源，逗号分隔 |
| `DB_POOL_SIZE` | 否 | PostgreSQL 连接池大小 |
| `DB_MAX_OVERFLOW` | 否 | PostgreSQL 连接池溢出上限 |
| `DB_CONNECT_TIMEOUT` | 否 | 数据库连接超时，单位秒 |

`*` Target 功能使用前必须配置。

## Target 模型

Target 表示 Agent 当前操作的运维项目。Target 直接存储在 PostgreSQL 中，不通过 SSH 或远程 Agent 连接。

| 字段 | 说明 |
|---|---|
| `root` | 本机项目根目录，所有 Target 文件工具的作用边界 |
| `service` | systemd 服务名，用于状态和重启 |
| `health_url` | 健康检查 URL |
| `deploy_command` | 审批通过后在项目根目录执行的部署命令 |
| `restart_command` | 自定义重启命令 |
| `log_path` | 项目日志相对路径 |

文件工具通过路径解析和 `is_relative_to` 限制在 Target root 内。Bash 命令审批通过后在宿主机执行，默认工作目录为 active Target root。

## 工具策略

| 工具类别 | 执行方式 |
|---|---|
| CPU、内存、磁盘、进程、端口、网络巡检 | 直接执行，写审计 |
| Target 状态、日志、HTTP、文件读取和 glob | 限定在 Target root 内执行 |
| Target 文件写入和编辑 | 创建 Pending Action，人工审批 |
| Target 重启和部署 | 创建 Pending Action，人工审批 |
| 宿主机 Bash | 创建 Pending Action，人工审批 |
| 任务、Memory、Skill、Cron | 按工具 Policy 执行 |
| MCP 工具 | 根据名称与风险动态判定；写入类默认审批 |

常见只读 Bash 命令会重定向到专用工具。例如：

```text
ss/netstat -> port_listen
df -h      -> disk_usage
free -h    -> memory_usage
pgrep      -> process_search
tail/cat   -> target_logs
curl GET   -> http_check
```

只读日志管道会被重定向；包含文件写入、混合写命令或 `tail -f` 的管道不会自动放行。

## 数据模型

### 会话数据

| 表 | 用途 |
|---|---|
| `sessions` | Session 元数据、Target、标题和 TTL |
| `messages` | 完整、追加式会话历史，供前端和审计读取 |
| `session_contexts` | 当前模型使用的压缩上下文，只供模型调用 |
| `runs` | Run 生命周期、安全点状态和中断原因 |
| `run_snapshots` | Run 安全点消息快照 |

上下文压缩只修改 `session_contexts`，不会覆盖 `messages`。Session 重启时分别加载两套状态。

### 业务数据

| 表 | 用途 |
|---|---|
| `targets` | 运维项目配置 |
| `tasks` / `task_dependencies` | 任务图和依赖 |
| `memories` | 长期记忆 |
| `pending_actions` | 人工审批动作 |
| `cron_jobs` / `cron_logs` |定时任务和执行日志 |
| `background_tasks` | 后台命令 |
| `audit_events` | 审计事件 |
| `run_usage` | Token 用量与成本估算 |
| `eval_*` | 评估结果 |

## 崩溃恢复

启动恢复过程会：

1. 将仍为 `running` 的 Run 标记为 `interrupted`。
2. 记录中断原因和 active tool。
3. 仅允许从没有工具在途的安全点人工恢复。
4. 将中断时仍在运行的 Background Task 标记为失败。
5. 将未完成的 Pending Action 标记为失败。
6. 清理孤儿 Sandbox 工作区。

系统不会自动重放 Bash、部署、删除或其他非幂等操作。

## API 概览

完整接口以 `/openapi.json` 和 `/docs` 为准。

### 对话与 Session

```text
POST   /api/chat/
POST   /api/chat/stream
POST   /api/chat/cancel
GET    /api/chat/sessions
GET    /api/messages/
POST   /api/reset/
```

SSE 事件：

```text
status
thinking
tool_use
tool_result
pending_action
compaction
text_delta
done
cancelled
error
```

### 运维资源

```text
GET    /api/targets/
POST   /api/targets/
POST   /api/targets/{id}/activate
GET    /api/actions/pending
POST   /api/actions/pending/{id}/confirm
POST   /api/actions/pending/{id}/cancel
GET    /api/tasks/
GET    /api/cron/
GET    /api/memory/
GET    /api/audit/events
GET    /api/recovery/runs
```

### 扩展能力

```text
GET    /api/mcp/
POST   /api/mcp/stdio/connect
POST   /api/mcp/sse/connect
GET    /api/skills
GET    /api/eval/batches
POST   /api/eval/run
GET    /api/eval/runs
```

## 评估

评估目录：

```text
eval/
  cases/       # 版本化 YAML 用例
  fixtures/    # 隔离测试项目
  reports/     # 本地报告，Git 忽略
  .runtime/    # Trial 工作目录，Git 忽略
```

当前运维用例覆盖：

- 服务健康巡检与日志分析
- 配置读取与安全写入
- 敏感文件和路径越界
- 缺失日志和无 Target
- 危险 Bash 和重启审批
- 长日志专用工具选择
- 开放问答 Judge

执行方式：

```bash
# 只校验用例，不调用模型
python scripts/run_eval.py --validate-only

# 运行核心用例
python scripts/run_eval.py --category core --trials 5 --label core-v2

# 启用 LLM Judge
python scripts/run_eval.py --category faq --trials 5 --judge

# 与基线比较
python scripts/run_eval.py \
  --category core \
  --trials 5 \
  --baseline eval/reports/baseline.json \
  --fail-on-regression
```

回归判断在两侧样本均不少于 5 个 Trial 时使用单侧双比例检验。样本不足时退回数值下降判定。

`.github/workflows/evaluation-regression.yml` 是可复用工作流；调用方必须先生成并上传 baseline/current 报告。

## 测试

```bash
python -m pytest -q
python scripts/run_eval.py --validate-only
```

PostgreSQL 集成测试：

```bash
PERSISTENCE_TEST_DATABASE_URL=postgresql+psycopg://ai_devops:change-me@127.0.0.1:5432/ai_devops \
python -m pytest tests/test_persistence_pg_integration.py -q
```

前端构建同时执行 TypeScript 检查：

```bash
cd frontend
npm run build
```

## 安全边界

部署到任何非可信网络前，应确认以下事项：

1. **API 鉴权**

   `API_AUTH_TOKEN` 为空时，所有请求按管理员身份处理。对外部署必须设置 Token 或前置认证网关。

2. **Bash 执行**

   Bash、部署和重启以 Agent 进程权限在宿主机执行。审批和审计不是操作系统级隔离。

3. **MCP**

   `/api/mcp/stdio/connect` 可以启动本地子进程，风险等价于命令执行。`ENABLE_UNSAFE_MCP_SHELL=1` 时，自定义 MCP Handler 使用 Shell 模板，只应在受信配置中使用。

4. **Target 路径**

   Target root 必须位于 `TARGET_BROWSE_ROOTS` 下。敏感文件默认阻止读取，但无法替代系统级权限控制。

5. **单实例状态**

   Session 缓存、运行锁、取消事件、审批等待和 MCP 连接仍保存在进程内。当前部署模型为单实例。

## 已知限制

- 不支持多租户。
- 不支持跨实例 Session 调度。
- `cancel_event` 不能终止已经进入同步执行的系统工具。
- 任务依赖图没有环检测和完整 CAS。
- Memory 检索基于词法、CJK bigram 和元数据，不是向量检索。
- 上下文大小按 JSON 字符数估算，不是精确 Token 计数。
- `text_delta` 是完整响应后的分段发送，不是模型原生 Token Streaming。
- Sandbox 只在 Run 期间存在，不作为持久工作目录。
- 当前评估门禁需要调用方完成 baseline/current 报告生成与 artifact 上传。

## 项目结构

```text
agent/
  core/              Agent loop, tools, context, recovery
  evaluation/        Evaluation runner, scoring, judge
  extensions/        Subagents
  mcp/               MCP transports and registry
  memory/            Long-term memory
  orchestration/     Tasks, cron, background, approvals
  persistence/       PostgreSQL models and repositories
  platform/          Config, identity, skills
  sandbox/           Temporary workspaces
  sessions/          Session lifecycle and recovery
  targets/           Project target tools
  tools/             Registry, policy, executor and built-ins
api/
  main.py            FastAPI application
  auth.py            Bearer auth
  routes/            REST domains
frontend/
  src/pages/         Chat, tasks, eval, targets and admin views
  src/store/         Zustand state
  src/api/           REST and SSE client
alembic/             PostgreSQL migrations
eval/                Evaluation cases, fixtures and local reports
tests/               Unit and integration tests
```

## 文档

- `docs/software-manual.md`：功能操作、架构、代码结构和运维手册
- `docs/architecture.md`：系统架构、主链路和状态机
- `docs/tools-and-policies.md`：工具注册、策略和执行流程
- `docs/context-management.md`：上下文管理、压缩和恢复设计
- `docs/evaluation-regression-ci.md`：评估回归 CI
- `docs/incident-postmortems.md`：工程故障复盘与改进记录
- `docs/performance-tuning.md`：性能与成本调优记录

## License

MIT

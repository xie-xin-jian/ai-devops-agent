# AI DevOps Agent

一个基于 Agent Harness 模式的 AI DevOps 助手，通过自然语言完成服务器巡检、故障排查和运维流程编排。

核心是一个“模型推理 -> 工具调用 -> 结果回填”的 Agent Loop。项目集成内置工具、MCP 动态工具、会话隔离、上下文压缩、长期记忆、任务图、后台任务、Cron 调度和 SSE 执行轨迹。

> 当前实现更适合本地开发、学习和可信环境使用。Session 和运行状态仍主要保存在进程内存中，不是完整的多租户生产安全系统。

## 核心特性

- **Agent Loop**：最多 50 轮模型调用，支持多轮推理、工具执行和结果回填
- **内置工具系统**：39 个内置工具，使用 `Schema + Handler` 双注册表
- **MCP 动态工具池**：支持内置、自定义、stdio 和 SSE MCP，运行时注入 `mcp__server__tool`
- **会话级上下文隔离**：每个 Session 拥有独立 Agent、消息历史、恢复状态、运行锁和取消事件
- **上下文压缩**：大结果持久化、微压缩、消息裁剪、摘要压缩和反应式压缩
- **错误恢复**：429 指数退避、529 模型降级、Prompt 过长恢复和输出 Token 预算扩容
- **任务系统**：支持 Todo 清单和带 `blockedBy` 依赖关系的持久化任务图
- **长期记忆**：结构化 `MemoryRecord`，支持类型、scope、实体、标签、来源、置信度和生命周期管理，提供精确去重、软删除与 JSONL 持久化
- **后台任务**：慢 Bash 命令异步执行，完成后在后续 Agent 轮次注入结果
- **Cron 调度**：五字段 Cron 解析、持久化任务、单执行器队列和运行日志
- **Skill 与 SubAgent**：按需加载 Markdown Skill，派生独立上下文执行子任务
- **SSE 实时事件**：展示 Agent 状态、工具调用、工具结果和最终文本
- **可视化管理界面**：React 页面覆盖聊天、任务、Cron、工具、MCP 和 Skill

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
      -> 有 tool_use：执行工具并写回 tool_result
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
API_AUTH_TOKEN=
ENABLE_UNSAFE_MCP_SHELL=0
```

主要配置：

| 变量 | 说明 |
|---|---|
| `MODEL_ID` | 主模型 ID |
| `ANTHROPIC_BASE_URL` | Anthropic 兼容服务地址，留空使用官方地址 |
| `ANTHROPIC_API_KEY` | 模型 API Key |
| `FALLBACK_MODEL_ID` | 529 过载时可切换的备用模型 |
| `DATA_DIR` | 运行时数据目录，留空则放在当前工作目录 |
| `API_AUTH_TOKEN` | 可选的 API Bearer Token |
| `ENABLE_UNSAFE_MCP_SHELL` | 是否允许自定义 MCP Shell Handler，默认关闭 |
| `ALLOWED_ORIGINS` | 逗号分隔的 CORS 来源 |

注意：`DEFAULT_MAX_TOKENS` 和 `ESCALATED_MAX_TOKENS` 当前由代码常量控制，不是 `.env` 配置项。

### 3. 运行时数据目录

设置 `DATA_DIR` 后，任务、记忆、日志和工具结果会集中保存：

```text
DATA_DIR/
├── .cron_logs/
├── .memory/
├── .tasks/
├── .task_outputs/
├── .transcripts/
├── .scheduled_tasks.json
└── logs/
```

`DATA_DIR` 只决定应用运行数据的默认位置，不是文件系统 Sandbox。

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

默认配置不挂载宿主 Docker Socket，也不提供 Docker 运行时检查工具。

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

## 内置工具（39 个）

| 类别 | 工具 |
|---|---|
| 文件 | `read_file` `write_file` `edit_file` `glob` |
| Shell | `bash` |
| 服务与系统 | `service_status` `system_info` `memory_usage` `cpu_usage` `process_top` `process_search` |
| 磁盘与网络 | `disk_usage` `disk_io` `network_interfaces` `port_listen` `ping_host` |
| 日志 | `system_logs` |
| Todo 与任务 | `todo_write` `create_task` `list_tasks` `get_task` `claim_task` `complete_task` |
| Skill / SubAgent | `list_skills` `load_skill` `spawn_subagent` |
| 记忆 | `add_memory` `search_memory` `update_memory` `archive_memory` `delete_memory` `restore_memory` |
| 上下文 | `compact` |
| Cron | `schedule_cron` `list_crons` `cancel_cron` `list_cron_logs` |
| MCP | `connect_mcp` |
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
│   ├── comprehensive.py        # Agent Loop 和子系统组装
│   ├── config.py               # 环境配置和路径
│   ├── permission.py           # 工具权限和路径检查
│   ├── hooks.py                # PreToolUse / PostToolUse / Stop Hook
│   ├── context_compact.py      # 上下文预算、裁剪和摘要
│   ├── error_recovery.py       # 重试、降级和 Token 扩容
│   ├── memory.py               # 长期记忆
│   ├── task_system.py          # 持久化依赖任务图
│   ├── todo.py                 # 会话待办清单
│   ├── background.py           # 后台任务
│   ├── cron.py                 # Cron 调度和执行日志
│   ├── mcp.py                  # MCP Client 和动态工具池
│   ├── skill.py                # Skill 扫描和加载
│   ├── subagent.py             # 子 Agent
│   ├── messages.py             # 可见消息序列化
│   ├── storage.py              # 原子写入
│   ├── logger.py               # 日志
│   └── tools/
│       ├── __init__.py         # 工具聚合注册
│       ├── shell.py            # Bash 执行
│       ├── file_tools.py       # 文件工具
│       └── ops.py              # 运维工具
├── api/
│   ├── main.py                 # FastAPI 入口
│   ├── auth.py                 # API Bearer Token 中间件
│   ├── schemas.py              # Pydantic 请求模型
│   └── routes/
│       ├── task.py
│       ├── cron_route.py
│       ├── mcp_route.py
│       └── skill_route.py
├── frontend/
│   ├── src/api/
│   ├── src/components/
│   ├── src/pages/              # 6 个功能页面
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
- 文件原子写入
- 安全加固

部分 API 集成测试依赖 FastAPI 环境，未安装相关依赖时会自动跳过。

## 已知限制

- Session、取消状态和运行锁保存在进程内存中，重启后丢失
- 当前 Agent Loop 不支持崩溃后继续执行
- 任务、记忆和 MCP 连接仍包含进程级全局状态
- 记忆检索以关键词和元数据排序为主，尚未接入向量语义检索
- 记忆仅做精确内容去重，语义相近记录仍需后续合并策略
- Cron 去重只保证单进程范围，多实例需要分布式租约
- `cancel_event` 不能抢占正在运行的同步工具
- Shell 和 MCP 权限是基础 Hook 防护，不是完整 Sandbox
- `VITE_API_TOKEN` 会进入浏览器产物，不适合公网多用户认证
- 上下文按字符近似计算，不是精确 Token 计数

## License

MIT

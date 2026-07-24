# AI DevOps Agent

一个基于 Harness 工程范式的 AI 运维助手，通过自然语言对话完成 DevOps 任务。核心是一个带工具调用、权限管控、上下文压缩、错误恢复的 Agent 循环，支持任务编排、定时巡检、后台任务和 MCP 动态工具扩展。

灵感来源于 [learn-claude-code s20 教学课程](https://github.com/shareAI-lab/learn-claude-code/blob/main/s20_comprehensive/code.py)，并在此基础上做了模块化工程重构，接入 FastAPI 后端与 React 可视化前端。

## 核心特性

- **Agent Loop**：最多 30 轮的工具调用循环，支持多轮推理与执行
- **权限系统**：黑名单拦截 + 破坏性命令审批 + 工作区路径逃逸防护
- **上下文压缩**：5 层压缩策略（大输出持久化 / 微压缩 / 摘要压缩 / 反应式压缩 / token 扩容），长对话不爆 token
- **错误恢复**：429 限流退避重试 + 529 过载自动降级模型 + Prompt 过长反应式压缩
- **任务图系统**：支持任务依赖关系（blockedBy），JSON 持久化
- **Cron 定时调度**：自实现 5 字段 cron 解析器，持久化 + 队列消费，适合定时巡检
- **后台任务**：慢命令（如 `apt install`）异步执行，不阻塞主循环
- **MCP 动态工具池**：运行时连接 MCP 服务器，动态注入工具
- **子 Agent**：派生独立上下文执行副任务
- **记忆系统**：三层记忆（select / extract / consolidate），JSONL 持久化
- **REST API**：FastAPI 实现
- **可视化前端**：React + TypeScript + TailwindCSS，暗色/亮色主题，5 个功能面板

## 技术栈

- **语言**：Python 3.11+
- **LLM**：Anthropic Claude API（兼容 DeepSeek 等第三方 base_url）
- **后端**：FastAPI + Uvicorn
- **前端**：React 18 + TypeScript + Vite + TailwindCSS + Zustand
- **持久化**：JSON 文件（轻量化，零数据库依赖）
- **调度**：自实现 cron 解析器
- **部署**：Docker + docker-compose

## 快速开始

### 安装

```bash
git clone <repository-url>
cd ai-devops-agent
pip install -r requirements.txt
cp .env.example .env
```

### 配置

编辑 `.env` 文件：

```
MODEL_ID=deepseek-chat
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_API_KEY=your-api-key
FALLBACK_MODEL_ID=
DEFAULT_MAX_TOKENS=8000
```

### 启动后端

```bash
python run.py
```

### 启动前端（开发模式）

```bash
cd frontend
npm install
npm run dev
```

### 生产部署（前端打包到后端）

```bash
cd frontend && npm run build   # 构建到 ../static/
cd .. && python run.py         # 后端同时托管前端
```

或使用 Docker：

```bash
docker-compose up --build
```

启动后访问：
- 可视化界面：http://localhost:8000/ui
- 开发模式：http://localhost:5173
- API 文档：http://localhost:8000/docs

## API 端点

### 核心

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 健康检查 + 工作目录 |
| GET | `/health` | 健康状态 |
| GET | `/tools` | 列出所有 Agent 工具 |
| POST | `/api/chat/` | 与 Agent 对话 |
| GET | `/api/messages/` | 获取对话历史 |
| POST | `/api/reset/` | 重置对话 |

### 任务管理

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/tasks/` | 列出所有任务 |
| POST | `/api/tasks/` | 创建任务 |
| GET | `/api/tasks/{id}` | 查看任务详情 |
| DELETE | `/api/tasks/{id}` | 删除任务 |
| POST | `/api/tasks/{id}/claim` | 认领任务 |
| POST | `/api/tasks/{id}/complete` | 完成任务 |

### Cron 调度

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/cron/` | 列出定时任务 |
| POST | `/api/cron/` | 创建定时任务 |
| DELETE | `/api/cron/{id}` | 取消定时任务 |

### MCP 服务器

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/mcp/` | 列出 MCP 服务器 |
| POST | `/api/mcp/connect` | 连接 MCP 服务器 |
| POST | `/api/mcp/disconnect` | 断开 MCP 服务器 |
| GET | `/api/mcp/tools` | 列出所有 MCP 工具 |
| POST | `/api/mcp/reload` | 重载 MCP 配置 |
| GET/POST/DELETE | `/api/mcp/custom` | 管理自定义工具集 |

## 项目结构

```
ai-devops-agent/
├── agent/                      # Agent 核心引擎
│   ├── comprehensive.py        # 综合 Agent 主类（核心循环）
│   ├── config.py               # 全局配置
│   ├── permission.py           # 权限系统（黑名单+审批+路径安全）
│   ├── hooks.py                # 钩子系统（PreToolUse/PostToolUse 等）
│   ├── todo.py                 # 待办规划
│   ├── task_system.py          # 任务图系统（依赖关系+持久化）
│   ├── subagent.py             # 子 Agent
│   ├── skill.py                # 技能加载（YAML frontmatter）
│   ├── context_compact.py      # 5 层上下文压缩
│   ├── memory.py               # 3 层记忆系统
│   ├── error_recovery.py       # 错误恢复（重试+降级+扩容）
│   ├── background.py           # 后台任务
│   ├── cron.py                 # Cron 定时调度（自实现解析器）
│   ├── mcp.py                  # MCP 模型上下文协议
│   └── tools/                  # 工具集
│       ├── __init__.py         # 工具聚合注册
│       ├── shell.py            # bash 命令执行
│       ├── file_tools.py       # 文件读写/编辑/glob
│       └── ops.py              # 运维工具（服务状态/磁盘/Docker）
├── api/                        # FastAPI 后端
│   ├── main.py                 # API 入口
│   └── routes/                 # 路由模块
│       ├── task.py             # 任务管理路由
│       ├── cron_route.py       # Cron 管理路由
│       └── mcp_route.py        # MCP 管理路由
├── frontend/                   # React 可视化前端
│   ├── src/
│   │   ├── api/                # API 适配层
│   │   ├── components/         # 通用 UI 组件
│   │   ├── pages/              # 5 个功能页面
│   │   ├── store/              # Zustand 状态管理
│   │   └── types/              # TypeScript 类型定义
│   ├── package.json
│   ├── vite.config.ts
│   └── tailwind.config.js
├── static/                     # 前端构建产物（供后端托管）
├── reference/                  # 参考资料
│   └── s20_code.py             # 原始教学版代码
├── run.py                      # 启动入口
├── Dockerfile                  # Docker 部署
├── docker-compose.yml          # 容器编排
├── requirements.txt            # Python 依赖
├── test_permission.py          # 权限系统测试
└── test_task_system.py         # 任务系统测试
```

## Agent 工具（22 个）

| 类别 | 工具 | 说明 |
|---|---|---|
| 基础工具 | `bash` `read_file` `write_file` `edit_file` `glob` | Shell 执行与文件操作 |
| 运维工具 | `service_status` `disk_usage` `docker_ps` | 服务状态/磁盘空间/Docker 容器 |
| 任务管理 | `todo_write` `create_task` `list_tasks` `get_task` `claim_task` `complete_task` | 任务图全生命周期 |
| 技能/子Agent | `list_skills` `load_skill` `spawn_subagent` | 技能加载与副任务派发 |
| 上下文 | `compact` | 主动压缩对话历史 |
| Cron 调度 | `schedule_cron` `list_crons` `cancel_cron` | 定时任务管理 |
| MCP | `connect_mcp` | 动态连接 MCP 服务器 |

## 使用示例

### 与 Agent 对话

```bash
curl -X POST http://localhost:8000/api/chat/ \
  -H "Content-Type: application/json" \
  -d '{"message": "列出当前目录下的所有 Python 文件"}'
```

### 创建任务

```bash
curl -X POST http://localhost:8000/api/tasks/ \
  -H "Content-Type: application/json" \
  -d '{"subject": "每日服务器巡检", "description": "检查磁盘、内存、CPU 使用率"}'
```

### 创建定时任务

```bash
curl -X POST http://localhost:8000/api/cron/ \
  -H "Content-Type: application/json" \
  -d '{"cron": "0 9 * * 1-5", "prompt": "执行每日服务器巡检", "recurring": true}'
```

## 测试

```bash
python test_permission.py
python test_task_system.py
```

## License

MIT

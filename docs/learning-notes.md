# AI DevOps Agent 学习笔记

> 这份笔记按学习顺序整理，代码引用均相对于项目根目录。
>
> 新增学习内容时，在文末“后续学习记录”中继续追加，保留已有内容不变。

## 目录

1. 项目全景
2. 一条消息的完整调用链
3. Agent Loop
4. 工具系统
5. Todo 与 Task Graph
6. 后台任务
7. 上下文压缩
8. 长期记忆
9. Skill 与 SubAgent
10. MCP
11. Cron
12. 权限与安全
13. 第一阶段安全加固落地
14. DATA_DIR 与项目清理
15. 面试速查
16. 后续学习记录

---

## 1. 项目全景

### 项目定位

这是一个基于 Harness 工程范式的 AI DevOps Agent：

- FastAPI 提供后端 API。
- React + TypeScript + Vite 提供管理界面。
- `ComprehensiveAgent` 负责 Agent Loop。
- 模型通过工具调用执行 Shell、文件、任务、Cron、MCP 等能力。
- 工具结果重新进入模型上下文，直到模型返回最终回答。

### 主要目录

```text
agent/          Agent 核心、工具、任务、记忆、Cron、MCP
api/            FastAPI 入口、Schema、路由、认证
frontend/       React 前端
mcp_servers/    标准 MCP Server 实现
skills/         Markdown 技能库
tests/          pytest 测试
scripts/        本机启动与维护脚本（当前未纳入 Git 跟踪）
```

### 核心源码

- `run.py`：启动 Uvicorn。
- `api/main.py`：FastAPI 应用、Session、聊天与 SSE 路由。
- `agent/comprehensive.py`：Agent Loop 与所有子系统组装。
- `agent/tools/`：文件、Shell、运维工具。
- `agent/permission.py`：工具调用权限检查。
- `agent/context_compact.py`：上下文预算、截断、摘要。
- `agent/memory.py`：长期记忆。
- `agent/task_system.py`：任务图。
- `agent/background.py`：后台任务。
- `agent/cron.py`：Cron 调度。
- `agent/mcp.py`：MCP Client 与动态工具池。
- `agent/skill.py`：Skill 扫描和加载。
- `agent/subagent.py`：独立上下文的子 Agent。

### 当前测试基线

```text
55 passed, 3 skipped
```

跳过项主要与当前 Python 环境是否安装 FastAPI 有关。

---

## 2. 一条消息的完整调用链

### 核心结论

浏览器只发起一次 `/api/chat/stream` 请求，但这一个 HTTP 流可能包含多轮模型推理和多次工具调用。

### 调用链

```text
用户输入
  -> Chat.tsx
  -> Zustand sendMessage
  -> chatApi.stream
  -> POST /api/chat/stream
  -> FastAPI chat_stream
  -> get_or_create_session
  -> ComprehensiveAgent.run_stream
  -> 模型调用
      -> 有 tool_use：执行工具并回到模型
      -> 无 tool_use：输出最终文本
  -> SSE JSON 事件
  -> 前端更新 Zustand
```

### 前端流程

1. `Chat.tsx` 调用 `sendMessage()`。
2. 前端先乐观追加用户消息。
3. 设置 `isStreaming=true`。
4. 清空上一轮工具轨迹和流式文本。
5. 创建 `AbortController`。
6. `chatApi.stream()` 发送 POST 请求。
7. 使用 `response.body.getReader()` 增量读取 SSE。
8. 维护 buffer，按 `\n\n` 切分完整事件。
9. 解析 `data: {...}` 并更新界面。

这里没有使用原生 `EventSource`，因为需要 POST JSON、自定义请求头和 `AbortSignal`。

### SSE 事件

```text
status       当前阶段和轮次
thinking     开始调用模型
tool_use     准备执行工具
tool_result  工具执行完成
text_delta   最终文本增量
done         Agent Loop 完成
cancelled    用户取消
error        流程错误
```

### Session

`api/main.py` 使用进程内字典保存 Session：

```text
session_id
  -> agent
  -> last_used
  -> cancel_event
  -> run_lock
```

每个 Session 有独立 Agent 和对话历史。`run_lock` 防止同一 Session 同时运行两个 Agent Loop。默认两小时未使用会清理。

### 取消

`cancel_event` 会在 Agent Loop 的轮次和工具调用边界检查。前端停止按钮同时调用取消 API 和 `AbortController.abort()`。

已发出的工具调用必须有对应 `tool_result`。如果取消时还有未执行工具，需要补齐：

```text
Error: cancelled by user
```

### 面试重点

- 为什么使用 SSE，而不是 WebSocket？
- 为什么不能直接用 `EventSource`？
- SSE 为什么会粘包和拆包？
- 为什么工具结果要作为 `user` 消息写回？
- 为什么每个 Session 需要 `run_lock`？
- 前端断开连接能保证后端任务停止吗？

---

## 3. Agent Loop

### 核心结论

一个 `turn` 是一次模型调用，不是一轮用户消息。用户发一次消息，Agent 可能调用模型多次。

### 主循环

```python
for turn in range(50):
    if cancelled:
        return

    self.messages = self._compact_if_needed(self.messages)
    response = self._call_api(self.messages)

    self.messages.append({
        "role": "assistant",
        "content": response.content,
    })

    if not has_tool_use(response.content):
        final_text = extract_text(response.content)
        break

    results = []
    for block in response.content:
        if block.type == "tool_use":
            output = self._handle_tool_call(block)
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": str(output),
            })

    self.messages.append({
        "role": "user",
        "content": results,
    })
```

### 每轮六个动作

1. 检查取消。
2. 压缩上下文。
3. 调用模型。
4. 保存并解析响应。
5. 执行工具。
6. 决定继续还是完成。

### 模型调用前

`_call_api()` 会：

- 动态合并内置工具和 MCP 工具。
- 重建 System Prompt。
- 加入时间、技能目录、相关记忆、MCP Server 信息。
- 使用当前恢复状态中的模型和最大输出 token。
- 通过 `with_retry()` 处理限流和过载。

### 响应处理

如果响应没有 `tool_use`：

1. 提取文本。
2. 发送 `text_delta`。
3. 退出循环。
4. 发送 `done`。

如果响应有 `tool_use`：

1. 顺序执行工具。
2. 前端展示结果最多 2000 字符。
3. 模型上下文接收完整原始结果。
4. 所有结果作为一条 user 消息写回。
5. 进入下一轮模型调用。

### 退出条件

- 模型不再返回 `tool_use`。
- 用户取消。
- 不可恢复的 API 异常。
- 达到 50 轮安全上限。

### 面试重点

- `turn` 的定义是什么？
- 谁决定是否继续调用工具？
- 多工具是并行还是串行？
- 为什么 `tool_use` 和 `tool_result` 必须配对？
- 达到 50 轮是否表示任务成功？
- `run()` 和 `run_stream()` 是什么关系？

---

## 4. 工具系统

### 核心结论

```text
Schema  = 给模型看的工具接口说明
Handler = 本地真正执行的 Python 函数
```

模型不会直接执行代码。它只生成工具名和参数，由程序路由并执行。

### 工具组成

```python
{
    "name": "read_file",
    "description": "Read file contents.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
        },
        "required": ["path"],
    },
}
```

```python
FILE_TOOL_HANDLERS = {
    "read_file": run_read,
}
```

### 注册层级

```text
基础工具模块
  -> FILE_TOOL_SCHEMAS / HANDLERS
  -> SHELL_TOOL_SCHEMAS / HANDLERS
  -> OPS_TOOL_SCHEMAS / HANDLERS
  -> ALL_TOOL_SCHEMAS / ALL_TOOL_HANDLERS
  -> ComprehensiveAgent self.tools / self.handlers
```

实例相关工具随后注册：

- `todo_write`
- 任务图工具
- Skill 工具
- 记忆工具
- `spawn_subagent`
- `compact`
- Cron 工具
- `connect_mcp`
- `list_background_tasks`

### 工具调用生命周期

```text
模型返回 tool_use
  -> PreToolUse hooks
  -> 权限检查
  -> 判断是否后台执行
  -> 合并 MCP handlers
  -> 查找 handler
  -> 执行 handler(**input)
  -> PostToolUse hooks
  -> 转成字符串
  -> 封装为 tool_result
```

### 参数与结果

- JSON Schema 主要约束模型生成，不是统一运行时校验器。
- 部分 handler 自己校验参数。
- `call_tool_handler()` 主要捕获 `TypeError`。
- 其他异常由 Agent Loop 转成错误字符串。
- 当前工具结果主要返回字符串。

### 工具描述的重要性

工具描述属于模型可见 Prompt。应说明：

- 做什么。
- 何时使用。
- 参数含义。
- 输出格式。
- 是否有副作用。
- 成功和失败含义。

### 面试重点

- Schema 和 handler 有什么区别？
- JSON Schema 是否会自动保证参数安全？
- 工具找不到时如何处理？
- MCP 工具为什么要命名空间？
- 工具结果为什么通常转成字符串？
- 工具描述如何影响 Agent 成功率？

---

## 5. Todo 与 Task Graph

### 核心区别

```text
Todo = 当前推理步骤清单
Task = 可持久化、可认领、可依赖的工作流状态
```

### Todo

数据结构：

```python
CURRENT_TODOS = [
    {"content": "检查磁盘", "status": "pending"},
]
```

特点：

- 无 ID。
- 无依赖。
- 无负责人。
- 无持久化。
- `todo_write` 当前整体替换列表。
- `format_todos()` 当前没有自动注入 System Prompt。

### Task

字段：

```text
id
subject
description
status
owner
blockedBy
priority
created_at
updated_at
result
```

状态机：

```text
pending -> in_progress -> completed
```

### 依赖判断

任务可启动需要：

- 所有 `blockedBy` 依赖存在。
- 依赖状态均为 `completed`。

### 持久化和并发

- 每个任务一个 JSON 文件。
- `atomic_write_json()` 防止半个文件。
- `_tasks_lock` 保护单进程读改写。
- 多进程仍可能丢失更新。

### 当前问题

- 无循环依赖检测。
- 无 failed/cancelled/blocked 持久状态。
- 删除任务不处理依赖引用。
- `in_progress` 没有租约或心跳。
- 优先级没有参与调度排序。
- 完成任务没有结果验证。

### 面试重点

- Todo 与 Task Graph 的区别是什么？
- 如何检测循环依赖？
- `_tasks_lock` 是否支持多进程？
- 原子写能否解决业务并发冲突？
- 完成状态能否证明任务业务成功？

---

## 6. 后台任务

### 核心结论

```text
前台调用：立即执行，完成后进入下一轮
后台任务：立即返回任务 ID，在线程中继续执行
Cron：未来按时间表达式触发
```

### 进入后台的条件

```python
def should_run_background(tool_name, tool_input):
    return (
        bool(tool_input.get("run_in_background"))
        or is_slow_operation(tool_name, tool_input)
    )
```

慢操作关键词包括：

```text
install, build, test, deploy, compile,
pip install, npm install, pytest, curl, wget
```

### 执行流程

```text
生成 bg_id
  -> 创建任务记录
  -> 启动 daemon thread
  -> 返回 Background task started
  -> 后台线程执行命令
  -> 触发 PostToolUse
  -> 保存完整结果
  -> 标记 completed
```

### 结果返回

隐式路径：

- 下一次 `run_stream()` 开始时调用 `collect_background_results()`。
- 已完成结果作为内部 user 消息注入。

显式路径：

```text
list_background_tasks
list_background_tasks(full=true)
```

### 当前问题

- 状态是模块级全局变量，不按 Session 隔离。
- 进程重启丢失。
- 没有所有者、开始时间和结束时间。
- 没有超时、取消、重试和配额。
- 失败和成功都标记为 completed。
- 完成后不会主动推送到当前 SSE 流。
- `run_bash_long()` 没有超时。

### 面试重点

- 原 `tool_use` 能否收到真实后台结果？
- 后台结果何时回到模型？
- 用户取消聊天是否会停止后台线程？
- `daemon=True` 表示什么？
- 如何把后台任务生产化为可靠任务队列？

---

## 7. 上下文压缩

### 核心结论

```text
上下文压缩不是单一算法
自动路径主要控制预算和消息数量
模型摘要主要出现在显式 compact 和 prompt 过长后的恢复路径
```

### 自动顺序

```python
messages = tool_result_budget(messages)
messages = micro_compact(messages)
if estimate_size(messages) > CONTEXT_LIMIT:
    messages = snip_compact(messages)
```

### 各层策略

1. `estimate_size()`
   JSON 字符长度，不是实际 token。

2. `tool_result_budget()`
   大工具结果写入 `.task_outputs/tool-results`，上下文保留路径和预览。

3. `micro_compact()`
   保留最近三个工具结果，旧结果替换为标记。

4. `snip_compact()`
   消息过多时保留头部、尾部和截断标记。

5. `compact_history()`
   写 transcript 并调用模型生成完整摘要。

6. `reactive_compact()`
   API 报 prompt 过长后，保留最近消息并摘要旧历史。

7. token 扩容
   最大输出 token 从 8000 提升到 16000。

### 重要限制

- 不包含 System Prompt 和工具 Schema。
- 不是精确 token 计数。
- 自动 snip 不会生成语义摘要。
- 摘要调用缺少重试和结果验证。
- 频繁改写历史会累积信息损失。

### 已修复的 P1

原 `compact` handler 在工具结果尚未写回时替换历史，产生孤立 `tool_result`。

现在改为：

```text
compact handler 只设置 _pending_compaction
  -> 当前所有 tool_result 写回
  -> 安全边界执行 compact_history
```

提交：

```text
093f18e fix(compact): P1 defer compaction until tool result is paired
```

### 面试重点

- 自动压缩是否等于模型摘要？
- 微压缩、截断、摘要有什么区别？
- 为什么压缩必须保持工具调用配对？
- 为什么估算大小必须包含 System Prompt 和工具定义？
- 如何测试压缩器？

---

## 8. 长期记忆

### 四类信息

```text
消息历史：当前会话完整过程
上下文压缩：当前会话工作摘要
长期记忆：跨会话可复用事实
外部存储：任务、日志、工具结果和转录
```

### 数据

每条记忆包含：

```text
id
content
importance
category
created_at
access_count
```

存储：

```text
DATA_DIR/.memory/memories.jsonl
```

### 三层方法

`select()`：

- 查询按空格拆词。
- 关键词匹配。
- 重要性和访问次数加权。
- 返回前 5 条。

`extract()`：

- 将记忆格式化为文本。

`consolidate()`：

- 至少 10 条时处理最旧的 5 条。
- 当前只是拼接前三段，不是模型摘要。
- 当前没有自动调用点。

### 自动注入

System Prompt 构建时使用上一轮用户问题检索记忆：

```text
Relevant memories:
[1] ...
[2] ...
```

显式工具：

```text
add_memory
search_memory
```

### 当前问题

- 全局共享，没有用户和租户隔离。
- 中文关键词召回效果弱。
- 所有记忆都有重要性基础分，可能注入无关内容。
- `access_count` 不持久化。
- 无更新、删除、过期和冲突处理。
- 记忆直接进入 System Prompt，存在 Prompt Injection。

### 面试重点

- 压缩和长期记忆的区别是什么？
- 什么信息值得长期保存？
- 当前检索是语义搜索还是关键词搜索？
- 为什么需要去重、过期和来源追踪？
- 如何防止记忆污染？

---

## 9. Skill 与 SubAgent

### 核心区别

```text
Skill：把知识按需交给主 Agent
SubAgent：把任务交给独立上下文执行
```

### Skill

目录：

```text
skills/{skill-name}/SKILL.md
```

使用 YAML Front Matter：

```markdown
---
name: nginx-troubleshooting
description: Nginx 故障排查指南
---
```

机制：

- 启动时扫描。
- System Prompt 只放技能摘要目录。
- 模型按需调用 `load_skill(name)`。
- 完整内容作为 `tool_result` 进入上下文。

优点：

- 渐进式披露。
- 避免所有技能全文占用上下文。

问题：

- 注册表是全局内存。
- 文件变更后不会自动重扫。
- 无版本、大小和权限控制。
- 技能内容可能形成 Prompt Injection。

### SubAgent

入口：

```text
spawn_subagent(description)
```

固定工具：

```text
bash
read_file
write_file
edit_file
glob
```

特点：

- 独立 messages。
- 独立 System Prompt。
- 最多 30 轮。
- 只把最终摘要返回主 Agent。

不是完全隔离：

- 不隔离文件系统。
- 不隔离进程和网络。
- 可以修改主工作区。
- 没有取消和独立超时。
- 没有 MCP、记忆、任务图和压缩。

### 面试重点

- Skill 和 Tool 的区别是什么？
- 为什么采用目录摘要 + 按需加载？
- SubAgent 为什么能节省主上下文？
- SubAgent 是否真的隔离？
- 如何限制 SubAgent 的权限和递归？

---

## 10. MCP

### 核心定义

```text
Tool：固定注册的本地能力
MCP：运行时连接外部 Server 并发现工具
```

### 命名空间

```text
mcp__{server}__{tool}
```

例子：

```text
mcp__docs__search
mcp__deploy__trigger
mcp__metrics__cpu
```

### 动态工具池

每次模型调用前执行：

```python
tools, _ = assemble_tool_pool(self.tools, self.handlers)
```

连接或断开 MCP Server 后，后续模型调用直接看到变化。

### 传输方式

Mock：

- 内存中的演示 Server。

Custom：

- `echo`
- `http`
- `shell`，现在默认禁用

Standard stdio：

- JSON-RPC over stdin/stdout。
- 启动本地子进程。

Standard SSE：

- SSE 接收服务端消息。
- HTTP POST 发送客户端请求。

### 协议握手

```text
initialize
notifications/initialized
tools/list
tools/call
```

JSON-RPC 响应通过 `id` 匹配，不能假设响应顺序。

### 当前问题

- 连接状态全局共享。
- Agent 的 `connect_mcp` 只支持 Mock Server。
- 没有 Resources、Prompts、Sampling、Progress 完整支持。
- 输出只提取 text，并截断到 5000 字符。
- stdio stderr 没有持续消费。
- SSE 断线没有自动重连。
- HTTP handler 有 SSRF 风险。
- stdio 和 SSE 管理接口是高权限入口。

### 面试重点

- MCP 和普通 Tool 的区别是什么？
- stdio 和 SSE 的差异是什么？
- 为什么需要 JSON-RPC ID？
- MCP 工具为什么需要命名空间？
- 如何保护 stdio 和 SSE 管理接口？

---

## 11. Cron

### 定位

```text
后台任务：现在开始，异步执行
Cron：未来按时间表达式触发
```

### CronJob

```text
id
cron
prompt
recurring
durable
name
description
enabled
created_at
```

持久化：

```text
DATA_DIR/.scheduled_tasks.json
```

### 五字段

```text
分钟 小时 日 月 星期
```

支持：

- `*`
- 单值和列表
- 范围
- `*/step`
- `start-end/step`

星期：

```text
0 = 星期日
1 = 星期一
...
7 = 星期日
```

### 调度结构

```text
cron_scheduler_loop
  -> 每分钟匹配
  -> last_fired 去重
  -> pending 去重
  -> 放入一个 queue
  -> cron-worker 串行执行
```

### 执行

每次运行创建全新的 `ComprehensiveAgent`：

```python
agent = _create_cron_agent()
output = agent.run(job.prompt)
```

执行日志：

```text
DATA_DIR/.cron_logs/{job_id}__{fired_at}.json
```

### 单次任务

触发时先移除并持久化，再进入队列。

### 当前问题

- 多实例可能重复执行。
- 取消不会停止已排队或运行任务。
- 没有超时和主动取消。
- 单 worker 会被长任务阻塞。
- 没有错过后补跑。
- `_last_fired` 不持久化。
- 使用服务器本地时区。
- 日志过滤先截断再筛选，可能遗漏目标任务。

### 面试重点

- Cron 和后台任务的区别是什么？
- 为什么 scheduler 和 worker 要分离？
- 如何防止同一任务重复入队？
- 单次任务崩溃后可能发生什么？
- 如何实现分布式 Cron 和错过补跑？

---

## 12. 权限与安全

### 信任链

```text
用户
  -> API
  -> 模型
  -> tool_use
  -> 权限 hook
  -> Tool / MCP / Shell
  -> OS、Docker、网络
```

所有输入都不能默认可信：

- 用户消息。
- 模型生成参数。
- Skill 和记忆。
- MCP Server 内容。
- 工具输出。
- Cron Prompt。

### 当前权限层

- Bash Deny List。
- Bash Destructive List。
- `write_file` 和 `edit_file` 路径检查。
- MCP 破坏性工具名称和描述启发式判断。

问题：

- 字符串黑名单容易绕过。
- Shell 使用 `shell=True`。
- 没有统一 Capability 模型。
- API 原先没有认证。
- MCP stdio/SSE/Custom 是高权限入口。
- Docker Socket 等价于宿主机高权限。
- 多租户状态没有隔离。
- 记忆和技能存在 Prompt Injection。

### 真正安全的分层

```text
认证
  -> 授权
  -> 参数校验
  -> Sandbox
  -> 人工审批
  -> 审计、告警和回滚
```

### 面试重点

- 为什么黑名单不可靠？
- `safe_path()` 是否能完全防止路径逃逸？
- Docker Socket 的风险是什么？
- CORS 是否等于认证？
- Shell `cwd` 限制是否等于 Sandbox？
- 如何防止 Prompt Injection？

---

## 13. 第一阶段安全加固落地

### API Bearer Token

配置：

```env
API_AUTH_TOKEN=my-secret-token
```

受保护：

- `/api/*`
- `/tools`

公开：

- `/`
- `/health`
- `/docs`
- `/redoc`
- `/openapi.json`
- `/ui`

curl 示例：

```powershell
curl.exe `
  -H "Authorization: Bearer my-secret-token" `
  http://localhost:8000/tools
```

实现文件：

```text
api/auth.py
```

### 前端 Token

```env
VITE_API_TOKEN=my-secret-token
```

普通请求和 SSE 请求都会自动附加 Authorization。

重要限制：

```text
VITE_API_TOKEN 会进入浏览器 JavaScript
```

只适合本地、单用户或可信内网。

### MCP Shell 默认关闭

```env
ENABLE_UNSAFE_MCP_SHELL=0
```

效果：

- 新 Shell MCP 工具不能注册。
- 旧 Shell 工具调用时返回 disabled。
- `echo` 和 `http` 不受影响。

### Bash cwd 限制

权限 hook 和实际 handler 都会检查起始目录。

工作区外：

```text
Permission denied: cwd escapes workspace
```

注意：这只是限制初始工作目录，不是文件系统 Sandbox。

### Docker Compose

已传递：

```yaml
API_AUTH_TOKEN
ENABLE_UNSAFE_MCP_SHELL
ALLOWED_ORIGINS
```

提交：

```text
5d33318 feat(security): add first-phase hardening
```

---

## 14. DATA_DIR 与项目清理

### DATA_DIR

`.env`：

```env
DATA_DIR=D:\ai_agent\data\ai-devops-agent
```

含义：

```text
应用持久化运行数据放在指定目录
```

不是 Sandbox，不强制所有写入只能发生在这里。

### 当前放入 DATA_DIR 的内容

```text
.cron_logs/
.memory/
.tasks/
.transcripts/
.task_outputs/
.scheduled_tasks.json
logs/
```

### 仍留在项目目录的内容

```text
.venv313/
frontend/node_modules/
frontend/tsconfig.tsbuildinfo
static/
__pycache__/
.pytest_cache/
.mcp_servers.json
.git/
```

### 清理结果

旧 `.venv`、空缓存和空目录移动到：

```text
D:\ai_agent\_cleanup_backup_ai-devops-agent
```

新的启动脚本：

```text
scripts/start_admin.bat
scripts/restart_admin.bat
```

启动脚本使用：

```text
.venv313
```

日志写入：

```text
D:\ai_agent\data\ai-devops-agent\logs
```

提交：

```text
eb6a6eb chore(runtime): externalize local data directory
```

---

## 15. 面试速查

### Agent Loop

- `turn` 是一次模型调用。
- 继续调用工具由模型决定。
- 代码负责消息协议、执行边界和安全策略。
- 50 轮是保护性上限，不代表成功。

### 工具

- Schema 是模型接口，handler 是本地函数。
- Schema 不等于运行时校验。
- 工具结果必须有对应 `tool_use_id`。
- MCP 工具通过命名空间动态合并。

### 任务

- Todo 是临时清单。
- Task 是持久状态机。
- 依赖全部完成才能认领。
- 当前锁只覆盖单进程。

### 后台与 Cron

- 后台任务现在异步执行。
- Cron 未来按时间自动触发。
- Cron 单 worker 串行执行。
- 多实例部署需要分布式租约。

### 上下文

- 压缩不等于长期记忆。
- 自动压缩主要做预算和截断。
- 完整摘要主要来自显式 `compact` 和反应式压缩。
- `compact` 必须在工具结果配对完成后执行。

### 安全

- 未认证 API 是高危入口。
- 字符串黑名单不是安全边界。
- Shell `cwd` 限制不是 Sandbox。
- Docker Socket 通常是宿主机 root 等价权限。
- Prompt Injection 必须靠代码权限边界和隔离解决。

---

## 16. 后续学习记录

> 新内容从下面继续追加。建议使用统一模板，避免破坏前面的学习顺序。

### 模板

```markdown
## 第 N 节：主题

### 核心结论

### 调用链或执行流程

### 关键数据结构

### 当前实现

### 存在的问题

### 面试问题

### 一句话总结
```

<!-- 后续学习内容从这里开始追加。 -->

# AI DevOps Agent 软件说明书

## 文档控制

| 项目 | 内容 |
|---|---|
| 文档名称 | AI DevOps Agent 软件说明书 |
| 文档版本 | 1.0 |
| 适用系统 | AI DevOps Agent（`main` 分支当前实现） |
| 数据迁移基线 | `0006_session_contexts` |
| 文档状态 | 当前版本 |
| 最后更新 | 2026-11-13 |

本文档面向系统使用者、平台运维人员和后续开发人员，说明系统能力、界面操作、核心业务流程、模块划分、代码组织、部署配置、安全边界和常见故障处理方式。

## 1. 文档说明

### 1.1 编写目的

本文档用于建立以下共同认知：

- 系统解决的问题和不适用的场景。
- 各功能入口、输入项、执行结果和前置条件。
- 高风险操作如何进入审批，审批后如何继续执行。
- 一次对话如何从 HTTP/SSE 请求进入 Agent Loop，并最终落库。
- API、会话、运行时、工具、持久化和前端之间的职责边界及依赖方向。
- 系统部署、升级、排障和二次开发时应遵循的约束。

### 1.2 读者与阅读路径

| 读者 | 关注内容 | 建议阅读顺序 |
|---|---|---|
| 运维与值班人员 | 创建项目、发起巡检、处理审批、查看恢复记录 | 2 → 3 → 4 → 10 |
| 平台维护人员 | 部署、配置、权限、备份、故障处理 | 3 → 8 → 9 → 10 → 11 |
| 开发人员 | API、执行链路、模块职责、数据结构、扩展方式 | 4 → 5 → 6 → 7 → 12 |
| 评估与质量人员 | 用例组织、运行参数、报告解读、回归门禁 | 3.14 → 4.5 → 6.4 → 12 |

### 1.3 术语

| 术语 | 含义 |
|---|---|
| Session | 一次持续对话及其目标、消息、模型上下文和项目绑定关系 |
| Run | Session 内的一次 Agent 执行，从接收用户消息到完成、失败或中断 |
| Target | 服务器上的运维项目目录及其服务、日志、健康检查和部署配置 |
| Tool | Agent 可调用的结构化能力，包含 Schema、Handler 和 Policy |
| Tool Policy | 工具的风险等级、只读属性、审批要求和超时策略 |
| Pending Action | 高风险工具调用生成的待审批动作 |
| Sandbox | Run 期间创建的临时文件工作区，Run 结束后清理 |
| MCP | Model Context Protocol，用于连接外部工具服务器 |
| Skill | 按需加载的 Markdown 运维知识包 |
| Trial | 同一评估用例的一次独立执行 |
| Judge | 对开放式回答按 Rubric 评分的独立模型 |

### 1.4 文档约定

- “界面”指 `/ui` 下由 React 构建的单页应用。
- “API”指 FastAPI 提供的 `/api/*` 接口。
- “宿主机”指运行本系统 Python 进程的服务器。
- “当前项目”指当前 Session 已激活的 Target。
- 命令示例默认从仓库根目录执行。
- 配置值以 `.env.example`、`agent/platform/config.py` 和 `/docs` 中的 OpenAPI 文档为最终事实来源。

## 2. 系统概述

### 2.1 系统定位

AI DevOps Agent 是一个面向受信基础设施环境的单机运维 Agent 运行时。用户用自然语言描述巡检、日志分析、配置修改、服务重启或部署任务，Agent 根据上下文选择工具，系统负责：

- 工具注册、策略判断和执行隔离。
- 高风险命令审批。
- 会话历史与模型上下文管理。
- Run 状态、安全点和失败恢复。
- 审计事件、任务、Cron、Memory 和评估管理。

系统不是普通聊天应用，也不是对所有请求都直接执行命令的终端代理。其核心设计是“模型提出行动，平台决定是否允许执行”。

### 2.2 功能范围

| 能力域 | 已实现能力 |
|---|---|
| 对话与推理 | 多轮模型调用、多工具调用、工具结果回填、取消、SSE 状态输出 |
| 项目操作 | Target 创建、目录浏览、激活、只读检查、文件写入、重启、部署 |
| 工具治理 | 集中策略、Bash 重定向、重复调用拦截、未知工具默认拒绝 |
| 审批 | Pending Action 创建、批准、拒绝、超时、进程重启后的中断处理 |
| 会话管理 | 创建、切换、重命名、删除、重置、持久化恢复 |
| 上下文 | 软/硬阈值、工具结果降级、检查点摘要、完整历史与模型上下文分离 |
| 自动化 | 任务图、Cron、后台任务、子 Agent |
| 扩展 | Skill、MCP、动态工具 |
| 可观测性 | 审计事件、Run 使用量、恢复记录、Sandbox 列表 |
| 质量评估 | YAML 用例、隔离 fixture、多 Trial、并发、Judge、报告对比 |
| 前端 | 对话、任务、Cron、工具、技能、审批、审计、恢复、工作区、项目、评估 |

### 2.3 适用边界

当前版本适用于：

- 可信本地开发机。
- 单机部署的测试或内部运维环境。
- 私有网络中的受控服务器。
- 已有系统级账号隔离、网络隔离和人工值守的运维场景。

当前版本不提供：

- 多租户身份隔离。
- 跨实例 Session 调度。
- 分布式工具执行。
- 操作系统级命令沙箱。
- 面向公网的最终用户认证体系。
- 自动重放可能产生副作用的工具。

### 2.4 界面功能地图

| 页面 | 主要用途 | 当前入口 |
|---|---|---|
| 对话 | 分配任务、选择项目、查看执行轨迹、处理即时审批 | 新建对话或侧栏会话 |
| 任务 | 创建、认领、完成和追踪任务 | 侧栏“任务” |
| 定时任务 | 管理 Cron 任务和执行记录 | 侧栏“定时任务” |
| 工具库 | 浏览当前可用工具及必填参数 | 侧栏“工具库” |
| 技能 | 浏览 `skills/` 中的运维知识 | 侧栏“技能” |
| 审批 | 查看待审批及历史动作 | 侧栏“审批” |
| 审计 | 查询工具、策略、审批和恢复事件 | 侧栏“审计” |
| 恢复 | 检查中断 Run 并安全续跑 | 侧栏“恢复” |
| 工作区 | 查看当前活动 Sandbox | 侧栏“工作区” |
| 运维项目 | 创建、编辑和激活 Target | 侧栏“管理项目” |
| 评估 | 启动评估、查看报告和基线对比 | 侧栏“评估” |
| MCP | 连接 stdio/SSE MCP Server | `/ui/?view=mcp` |

当前侧栏没有单独的 MCP 菜单项，但页面和 API 已实现，可通过查询参数进入。

## 3. 功能与操作说明

### 3.1 登录与状态检查

系统使用静态 Bearer Token。后端设置 `API_AUTH_TOKEN` 后，前端构建时必须配置相同的 `VITE_API_TOKEN`。

操作步骤：

1. 打开 `/ui`。
2. 查看侧栏底部状态。绿色表示 `/health` 正常，红色表示服务或数据库不可用。
3. 页面返回 401 时，核对后端 `API_AUTH_TOKEN` 与前端 `VITE_API_TOKEN`。
4. 页面返回 503 或健康状态异常时，检查 PostgreSQL 连接和迁移状态。

注意：

- `API_AUTH_TOKEN` 为空时，系统不校验请求，并按管理员身份处理。
- 前端 Token 会被打包进浏览器资源，只适用于可信环境。
- 对外部署应在反向代理或网关层增加正式登录和访问控制。

### 3.2 对话与执行轨迹

#### 3.2.1 创建对话

1. 在侧栏选择“新建对话”。
2. 点击输入框左下角的项目按钮。
3. 选择一个 Target，或进入“管理项目”创建 Target。
4. 输入任务并点击发送。`Enter` 发送，`Shift+Enter` 换行。

未绑定 Target 时仍可进行一般问答，但 Target 文件、日志、服务和部署工具无法工作。

#### 3.2.2 执行过程

对话页面会展示以下状态：

- Agent 正在准备或调用模型。
- 当前轮次和工具调用。
- 正在执行的工具及展开后的结果。
- 上下文压缩开始和完成。
- 待审批动作。
- 最终回答或错误信息。

工具执行区域支持展开，查看每一步的输入、输出和耗时。最外层显示当前或最近一次工具活动，详细记录保留在展开区。

#### 3.2.3 停止、重置和会话管理

- 执行期间点击停止按钮，会设置取消标记并中断前端 SSE 请求。
- 顶部“重置”清空当前 Session 的消息和模型上下文。
- 侧栏支持切换、重命名和删除会话。
- Session 在前端按 Target 分组，未绑定 Target 的会话归入“其他对话”。

取消并立即终止同步系统调用的能力有限。取消标记会被检查，但已进入阻塞系统调用的工具可能先执行完成。

#### 3.2.4 典型任务示例

```text
只读检查当前项目最近的日志，定位错误码并说明是否自动恢复。
```

```text
读取 config/app.conf，列出监听端口、worker 数和连接池大小。
```

```text
将 config/app.conf 中 logging.level 从 INFO 改为 WARNING。
不要修改其他配置，不要重启服务。
```

```text
检查服务健康状态；如果需要重启，先说明影响范围和验证方式。
```

任务中包含“只读”“不要重启”“只修改哪个文件”等约束，有助于模型选择正确工具，也便于审计时判断执行是否符合要求。

### 3.3 运维项目（Target）

Target 是 Agent 的项目边界。文件类工具和 Bash 默认工作目录均围绕当前 Target 工作。

#### 3.3.1 创建项目

1. 进入“运维项目”。
2. 点击“添加项目”。
3. 点击“浏览服务器”，在 `TARGET_BROWSE_ROOTS` 允许的目录中选择项目根目录。
4. 填写项目名称和可选配置。
5. 点击“保存并设为当前项目”。

#### 3.3.2 字段说明

| 字段 | 必填 | 说明 |
|---|---|---|
| 项目目录 | 是 | 项目根目录，必须位于 `TARGET_BROWSE_ROOTS` 下 |
| 项目名称 | 否 | 界面显示名称，留空时可由目录名生成 |
| 服务名 | 否 | systemd 服务单元名，用于状态和默认重启 |
| 健康检查 URL | 否 | 服务 HTTP 健康检查地址 |
| 日志路径 | 否 | 相对项目根目录的日志路径 |
| 部署命令 | 否 | 审批通过后在项目根目录执行的命令 |
| 重启命令 | 否 | 自定义重启命令；为空时使用 `systemctl restart <service>` |
| 项目说明 | 否 | 运维范围和注意事项 |

#### 3.3.3 激活和删除

- 选择“设为当前项目”后，当前 Session 会绑定该 Target。
- 新保存的项目会自动成为当前项目。
- 删除 Target 只删除配置，不删除服务器项目目录。
- Target 必须位于允许浏览的根目录内。

#### 3.3.4 文件与敏感路径

Target 文件工具会将路径解析为绝对路径，并校验其仍位于 Target root 内。默认阻止读取或写入常见敏感文件，包括：

- `.env`、`.env.local`
- `credentials`
- `.pem`、`.key`、`.p12`、`.pfx`

该限制用于降低误操作和凭据泄露风险，但不能替代服务器文件权限、操作系统账号隔离或密钥管理系统。

### 3.4 审批

#### 3.4.1 触发条件

以下工具通常在执行前进入 Pending Action：

- 宿主机 Bash。
- Target 文件写入和编辑。
- Target 服务重启。
- Target 部署。
- 需要审批的动态 MCP 工具。
- 未登记或无法确定安全性的工具。

只读巡检、日志读取、健康检查、任务查询等工具可直接执行并写审计。

#### 3.4.2 处理审批

1. 进入“审批”页面。
2. 选择会话，切换到“待审批”。
3. 查看动作摘要、风险等级、执行步骤、影响范围、回滚方案和验证方式。
4. 选择“批准”或“拒绝”。
5. 批准后在“历史”中检查执行结果；同一会话的对话也可能继续更新。

审批状态包括：

| 状态 | 含义 |
|---|---|
| `pending` | 等待人工决定 |
| `confirmed` | 已批准，正在或等待执行 |
| `executed` | 工具已执行成功 |
| `failed` | 执行失败 |
| `canceled` | 已拒绝 |

默认审批等待时间为 1800 秒。进程重启时，未完成动作不会继续等待，会被标记为中断或失败。

#### 3.4.3 审批原则

- 先确认目标项目是否正确。
- 核对命令、文件路径和参数。
- 高风险部署应确认回滚方案和验证方式。
- 拒绝操作后检查原命令是否真的没有执行。
- 不要仅依据 Agent 的文字回答判断命令结果，应查看工具结果、审批详情和文件状态。

### 3.5 任务管理

任务用于跨会话保存运维计划和执行结果。

创建任务：

1. 进入“任务”。
2. 点击“新建任务”。
3. 填写任务标题、描述和优先级。
4. 创建后在详情面板中认领或完成。

任务状态：

| 状态 | 操作 |
|---|---|
| `pending` | 待处理，可认领 |
| `in_progress` | 进行中，可完成 |
| `completed` | 已完成，可查看完成结果 |
| `blocked` | 受依赖阻塞 |

完成任务时可填写结果或证据。任务详情同时显示 Owner、Run 和依赖关系。

任务工具允许 Agent 创建、查询、认领和完成任务。依赖关系由数据模型和 API 支持，当前界面主要展示依赖，复杂依赖图应通过 API 或 Agent 工具建立。

### 3.6 定时任务

Cron 任务按五字段表达式自动触发一次 Agent 执行。

创建步骤：

1. 进入“定时任务”。
2. 点击“新建”。
3. 输入任务名称、描述和 Cron 表达式。
4. 输入触发时发送给 Agent 的消息。
5. 点击创建。

字段说明：

| 字段 | 说明 |
|---|---|
| 名称 | 定时任务名称 |
| 描述 | 可选说明 |
| Cron 表达式 | 格式为“分 时 日 月 周” |
| 消息 | 到点后发送给 Agent 的自然语言任务 |

界面提供以下快捷表达式：

- 每分钟：`* * * * *`
- 每小时：`0 * * * *`
- 每天 9 点：`0 9 * * *`
- 每周一：`0 9 * * 1`

任务列表展示上次运行时间、运行状态和最近结果。日志按钮可查看历史输出或错误。当前界面支持创建和删除，不提供直接编辑；修改任务应删除后重建，或通过 API/数据管理流程处理。

Cron 触发的执行不依赖浏览器 SSE 连接，但调度状态和运行日志会持久化到数据库。

### 3.7 Memory

Memory 用于保存跨 Session 的长期事实，例如：

- 服务端点和健康检查位置。
- 部署和回滚流程。
- 主机特性。
- 用户明确要求长期保留的偏好。

当前没有独立 Memory 页面，使用方式为：

1. 在对话中要求 Agent 搜索、添加或更新长期记忆。
2. 使用 `search_memory`、`add_memory`、`update_memory` 等工具。
3. 候选记忆可通过 `/api/memory/{memory_id}/approve` 批准。

不应将一次性日志、临时指标、密码、Token 或私钥写入 Memory。当前检索使用词法、CJK bigram 和元数据评分，不提供向量检索。

### 3.8 工具库

“工具库”展示当前运行时可被 Agent 使用的工具。

操作方式：

- 按名称或描述搜索。
- 按基础工具、任务、技能、Cron、MCP、上下文、运维工具和 Target 分类查看。
- 查看工具描述和必填参数。

MCP 连接成功后，其工具以 `mcp__<server>__<tool>` 格式出现。工具是否实际执行还受 Policy、当前 Target、权限上下文和审批状态影响。

### 3.9 技能

Skill 是可按需加载的 Markdown 运维知识，位于 `skills/<name>/SKILL.md`。

使用方法：

1. 将技能目录放入 `skills/`。
2. 在“技能”页面刷新。
3. 选择技能查看完整内容。
4. 在对话中要求 Agent 加载相关技能。

技能内容不会默认全部注入模型上下文，而是在相关任务中通过 `list_skills`、`load_skill` 或系统提示按需加载。

### 3.10 MCP

MCP 用于扩展外部工具能力。

当前支持：

| 类型 | 说明 |
|---|---|
| `builtin` | 内置或 Mock MCP Server |
| `custom` | 通过自定义配置注册的 Server |
| `stdio` | 启动本地子进程，通过标准输入输出通信 |
| `sse` | 连接远程 SSE MCP Server |

连接本地 Stdio：

1. 打开 `/ui/?view=mcp`。
2. 点击“连接 Server”。
3. 选择“本地 Stdio”。
4. 填写名称、启动命令、参数和工作目录。
5. 点击连接。

连接远程 SSE：

1. 选择“远程 SSE”。
2. 填写服务器名称和 SSE URL。
3. 点击连接。

Stdio 连接会启动本地子进程，风险等同于执行本机命令，只允许连接受信 Server。MCP 工具名会根据只读特征和写入关键字动态判断风险，高风险调用仍需审批。

### 3.11 审计

审计页面记录结构化操作轨迹。

查询方式：

1. 选择会话，或留空查询全局事件。
2. 输入事件类型，例如 `tool.completed`。
3. 点击查询。
4. 在事件流中选择记录，查看 Run、工具、Actor、时间和 Payload。

当前页面最多读取最近 200 条事件。审计信息用于还原：

- 哪个 Session 和 Run 产生了动作。
- 调用了哪个工具。
- Policy 是否放行。
- 动作是否进入审批。
- 执行成功、失败还是被阻止。
- 进程恢复和 Sandbox 清理是否发生。

### 3.12 Run 恢复

恢复页面用于处理 `interrupted`、`failed` 或 `canceled` Run。

查看步骤：

1. 进入“恢复”。
2. 可按会话筛选，并可选择包含已完成 Run。
3. 选择一条 Run。
4. 查看中断阶段、中断原因、在途工具、消息数和恢复次数。
5. 仅当显示“可继续”时，才提供“从安全点继续”。

系统不会自动续跑工具。若中断发生时工具正在执行，`safe_to_resume` 为假，界面不会提供自动恢复，以避免重复执行部署、删除或重启。

### 3.13 Sandbox 工作区

Sandbox 是 Run 期间供文件类工具使用的临时工作区。

- 页面每 10 秒刷新活动工作区。
- 正常完成后自动清理。
- 进程启动时会清理孤儿工作区。
- Sandbox 不是持久项目目录，不能当作长期文件存储。
- Bash 和 Target 部署仍以宿主机权限执行，不应把 Sandbox 理解为完整安全容器。

### 3.14 评估

#### 3.14.1 运行评估

进入“评估”，点击“运行评估”：

1. 选择“正式评估”或“仅校验用例”。
2. 可填用例 ID、类别、Trial 次数、并发数、Judge、失败即停和标签。
3. 正式评估会调用模型 API 并产生费用。

参数说明：

| 参数 | 说明 |
|---|---|
| 用例 | 逗号或空格分隔；留空表示全部 |
| 类别 | `core`、`boundary`、`abnormal`、`faq` |
| 每用例采样次数 | 每个用例独立的 Trial 数量 |
| 并发数 | 同时运行的 Trial 数 |
| LLM Judge | 对 `judge_rubric` 用例调用独立 Judge |
| 失败即停 | 第一个失败后停止，强制串行 |
| 标签 | 用于区分 Prompt、模型或策略版本 |

#### 3.14.2 解读报告

报告页面提供：

- Trial 总数、完成数、通过数和失败数。
- 总体通过率及 Wilson 95% 置信区间。
- 成本和耗时。
- 分类别通过率。
- 用例下钻及每次 Trial 的工具轨迹。
- 基线/当前批次对比、回归项、改进项和噪声内下降。

当基线和当前两侧样本均不少于 5 个 Trial 时，通过率回归使用单侧双比例检验；样本不足时退回数值下降加容差判断。正式回归门禁应使用至少 5 个 Trial。

#### 3.14.3 命令行运行

```bash
# 零模型费用，仅校验 YAML、fixture 和断言结构
python scripts/run_eval.py --validate-only

# 运行核心用例
python scripts/run_eval.py --category core --trials 5 --label core-v2

# 运行开放式问题并启用 Judge
python scripts/run_eval.py --category faq --trials 5 --judge

# 与基线比较并在回归时返回非零状态
python scripts/run_eval.py \
  --category core \
  --trials 5 \
  --baseline eval/reports/baseline.json \
  --fail-on-regression
```

当前用例覆盖服务巡检、日志分析、配置读取和修改、敏感文件、路径越界、未绑定 Target、危险 Bash、重启审批、非法配置和开放式故障处理。

### 3.15 后台任务

慢操作或显式要求后台执行的命令可创建后台任务。

- 后台任务通过 Agent 工具创建和查询。
- 结果在后续 Agent 轮次注入。
- 进程中断时，运行中的后台任务会被标记为失败。
- 当前没有独立后台任务页面，可通过对话要求 Agent 使用 `list_background_tasks`。

### 3.16 API 访问

系统使用 `/api/*` 提供 REST 和 SSE 接口。完整请求模型、响应模型和错误码以 `/docs` 或 `/openapi.json` 为准。

设置 Token 后，请求头为：

```http
Authorization: Bearer <API_AUTH_TOKEN>
```

SSE 主对话接口：

```text
POST /api/chat/stream
```

状态事件包括：

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

`text_delta` 是模型完整响应后的分段发送，不是模型原生 Token Streaming；工具和状态事件在流程中实时产生。

## 4. 核心业务流程

### 4.1 一次对话的执行链路

```text
Client
  -> Bearer Auth
  -> SessionManager.get_or_create
  -> acquire session.run_lock
  -> ComprehensiveAgent.run_stream
  -> create Run and snapshot
  -> model/tool loop
       -> context compaction
       -> model call
       -> tool policy
       -> direct execution or Pending Action
       -> append tool result
  -> persist run status and usage
  -> SSE done
```

详细过程：

1. 校验 Bearer Token，解析调用身份。
2. 通过 SessionManager 获取或恢复 Session。
3. 从 `messages` 加载完整历史，从 `session_contexts` 加载模型上下文。
4. 获取 Session 运行锁，保证同一 Session 串行执行。
5. 创建 Run，并在模型调用前保存安全点。
6. 每轮检查上下文，组装 System Prompt 和工具目录。
7. 调用模型；有工具调用时进入 Policy 判断。
8. 只读工具直接执行；需要审批的工具创建 Pending Action 并等待决定。
9. 工具结果写回模型上下文和完整会话历史。
10. 最终文本通过 SSE 返回，Run 状态、Token 用量和审计事件落库。

### 4.2 工具策略判定

```text
Tool Call
  -> known tool?
       no  -> high risk / approval
       yes -> policy lookup
  -> allowed?
       no  -> return Policy denied
  -> bash redirect rule matched?
       yes -> return Redirected: use <dedicated tool>
  -> approval required?
       yes -> create Pending Action / wait
       no  -> execute
  -> validate path, timeout and MCP visibility
  -> write result and audit
```

常见 Bash 重定向：

| Bash 命令 | 专用工具 |
|---|---|
| `df -h` | `disk_usage` |
| `free -h` | `memory_usage` |
| `ps aux` / `pgrep` | `process_top` / `process_search` |
| `ss` / `netstat` | `port_listen` |
| `tail` / `cat` 日志 | `target_logs` |
| 只读 `curl` | `http_check` |

复合命令、文件写入或 `tail -f` 等场景不会被简单重定向。

### 4.3 审批状态流转

```text
Created
  -> pending
      -> confirmed -> executed
      -> confirmed -> failed
      -> canceled
      -> interrupted on process restart
```

正常界面只对 `pending` 动作提供批准或拒绝入口；底层执行逻辑只接受 `confirmed` 动作。进程恢复时，已确认但未完成执行的动作需要人工检查，不得直接假定其已执行。

### 4.4 上下文压缩

上下文大小按序列化 JSON 文本字符数估算，不按精确 Token 数。

| 范围 | 处理方式 |
|---|---|
| 不超过 30,000 字符 | 保持原样 |
| 30,000 至 50,000 字符 | 只降级大型工具结果 |
| 超过 50,000 字符 | 生成检查点交接摘要并替换模型上下文 |

压缩时：

- `messages` 中的完整可见历史保持不变。
- `session_contexts` 保存当前模型可用上下文。
- 压缩前 transcript 写入 `DATA_DIR/.transcripts/`。
- 摘要失败时开启新窗口，并保留本轮目标和近期用户原话。

### 4.5 评估执行流程

```text
YAML case
  -> validate schema
  -> copy fixture to isolated workspace
  -> create Target and Session
  -> run Agent
  -> apply configured approval policy
  -> collect tools, answer, files, cost and duration
  -> score deterministic assertions and optional Judge
  -> write trial/report
  -> aggregate and compare with baseline
```

## 5. 模块划分

### 5.1 分层架构

```text
Presentation
  React SPA, Zustand state, REST/SSE client

API
  FastAPI, Bearer middleware, route domains

Session
  SessionManager, run lock, cancellation, history restore

Runtime
  ComprehensiveAgent, ContextManager, ToolLoop, ErrorRecovery

Governance and Execution
  ToolRegistry, ToolPolicy, ToolExecutor, MCP, Sandbox

Domain Services
  Target, tasks, Cron, background jobs, Memory, skills, evaluation

Persistence
  SQLAlchemy models, repositories, RecoveryStore, Alembic
```

### 5.2 模块职责

| 模块 | 职责 | 不负责 |
|---|---|---|
| `frontend/` | 页面交互、状态展示、REST/SSE 调用 | 工具权限和执行决定 |
| `api/` | 路由、参数校验、身份提取、SSE 入口 | 模型循环和工具策略细节 |
| `agent/sessions/` | Session 生命周期、锁、取消、恢复 | 工具实现 |
| `agent/core/` | 模型循环、上下文、错误恢复、工具分发 | HTTP 路由和页面渲染 |
| `agent/tools/` | Schema、Handler、Policy、执行器、Bash 重定向 | 业务页面 |
| `agent/targets/` | 项目边界、目录浏览、文件和服务操作 | Session 调度 |
| `agent/orchestration/` | 审批、任务、Cron、后台任务 | 模型 API 客户端 |
| `agent/persistence/` | 数据模型和仓储 | 业务决策 |
| `agent/mcp/` | MCP 连接、工具发现和调用 | 通用审批 UI |
| `agent/memory/` | 长期记忆存储和检索 | 会话短期上下文 |
| `agent/evaluation/` | 用例运行、评分、Judge、基线比较 | 生产对话执行 |
| `agent/sandbox/` | 临时工作区创建和清理 | 宿主命令安全隔离 |

### 5.3 依赖方向

- 前端只依赖 API 契约，不直接访问数据库。
- API 依赖 Session 和领域服务，不直接实现工具策略。
- Runtime 依赖工具 Registry、Policy、Executor 和持久化接口。
- 工具实现依赖平台能力，不反向依赖前端。
- Repository 负责数据库访问，业务层不直接拼接 SQL。
- 配置从 `agent/platform/config.py` 和环境变量统一读取。

## 6. 代码结构

```text
run.py                         Uvicorn 启动入口
api/
  main.py                      应用装配、健康检查、主对话接口
  auth.py                      Bearer Token 中间件
  routes/                      tasks、cron、mcp、actions、audit、recovery 等
agent/
  core/
    comprehensive.py           综合 Agent 与依赖注入
    pipeline.py                Run 主循环、SSE 事件、收尾
    tool_loop.py               模型调用、工具分发、审批
    context_manager.py         系统提示、工具目录、上下文预算
    context_compact.py         检查点、摘要、工具结果裁剪
    error_recovery.py          429/529、超长上下文、输出扩容
  sessions/
    manager.py                 活跃 Session、TTL、锁、恢复
    state_store.py             Session/Run/安全点持久化
  tools/
    registry.py                Schema 与 Handler 注册
    policy.py                  风险、审批和能力边界
    executor.py                工具统一执行入口
    shell.py                   Bash 执行与重定向规则
    business/                  任务、Memory、Cron、Skill、子 Agent
  targets/
    service.py                 Target 校验、目录浏览、敏感路径
    tools.py                   Target 文件、服务、日志和部署工具
  orchestration/
    pending_actions.py         Pending Action 状态机
    approval_coordinator.py    进程内审批等待
    tasks.py / cron.py         任务图和定时调度
    background.py              后台任务
  persistence/
    models.py                  SQLAlchemy 数据模型
    repositories/              各领域仓储
  mcp/                         MCP 客户端和连接管理
  memory/                      Memory 服务和检索
  evaluation/                  用例运行、评分和比较
  sandbox/                     临时工作区管理
frontend/
  src/pages/                   12 个业务页面
  src/components/              布局、Workspace、Markdown 等
  src/store/useAppStore.ts     前端全局状态和业务动作
  src/api/index.ts             REST/SSE 客户端
alembic/versions/              数据库迁移
eval/cases/                    版本化评估用例
eval/fixtures/                 隔离测试项目
scripts/run_eval.py            评估命令行入口
tests/                         单元与集成测试
skills/                        按需加载的运维知识
```

### 6.1 关键入口

| 场景 | 入口 |
|---|---|
| 服务启动 | `run.py` |
| FastAPI 应用 | `api/main.py` |
| 主对话 SSE | `api/main.py` 的 `chat_stream` |
| Session 恢复 | `agent/sessions/manager.py` |
| Agent 主循环 | `agent/core/pipeline.py` |
| 模型和工具循环 | `agent/core/comprehensive.py`、`agent/core/tool_loop.py` |
| 上下文压缩 | `agent/core/context_manager.py` |
| 工具注册 | `agent/tools/registry.py` |
| 工具策略 | `agent/tools/policy.py` |
| 统一执行 | `agent/tools/executor.py` |
| 审批状态 | `agent/orchestration/pending_actions.py` |
| 数据库模型 | `agent/persistence/models.py` |
| 前端页面选择 | `frontend/src/App.tsx` |
| 前端状态 | `frontend/src/store/useAppStore.ts` |

### 6.2 新增工具

新增内建工具时，至少完成以下工作：

1. 在对应 Tool Mixin 或工具模块中定义 JSON Schema 和 Handler。
2. 在 `ToolRegistry` 中注册，确保 `/tools` 和 Agent 工具目录可见。
3. 在 `agent/tools/policy.py` 中登记风险、只读属性、审批、超时和幂等性。
4. 在 `ToolExecutor` 中确认参数、路径、Target 和 Sandbox 语义。
5. 增加单元测试，覆盖策略、成功、失败和越权场景。
6. 在 `eval/cases/` 中增加真实任务用例。
7. 更新工具参考和本说明书。

未知工具默认按高风险处理，因此只增加 Handler 而不登记 Policy 会导致工具无法按预期直接执行。

### 6.3 修改数据模型

涉及持久化字段或表时：

1. 修改 `agent/persistence/models.py`。
2. 新建 Alembic 迁移，不直接修改已发布迁移。
3. 更新对应 Repository 的读写、序列化和兼容逻辑。
4. 更新 Session 恢复和前端数据结构。
5. 增加 PostgreSQL 集成测试。
6. 执行 `alembic upgrade head` 并验证现有数据迁移。

### 6.4 新增评估用例

1. 在 `eval/cases/*.yaml` 添加用例。
2. 在 `eval/fixtures/` 创建隔离项目，或引用已有 fixture。
3. 配置 Prompt、超时、最大轮次、审批策略和断言。
4. 补充安全断言，例如禁止调用部署、重启或写入工具。
5. 运行 `python scripts/run_eval.py --validate-only`。
6. 运行正式评估并确认失败代表真实行为变化，而非用例自身不稳定。

## 7. 数据与状态

### 7.1 核心数据表

| 表 | 用途 |
|---|---|
| `sessions` | Session 元数据、Owner、Target、TTL 和更新时间 |
| `messages` | 追加式完整会话历史 |
| `session_contexts` | 当前模型上下文 |
| `targets` | 运维项目配置 |
| `runs` | Run 状态、阶段、安全点和中断原因 |
| `run_snapshots` | Run 安全点消息快照 |
| `run_usage` | Token 用量和成本估算 |
| `pending_actions` | 审批动作及执行结果 |
| `audit_events` | 结构化审计事件 |
| `tasks` / `task_dependencies` | 任务和依赖关系 |
| `memories` | 长期记忆 |
| `cron_jobs` / `cron_logs` | 定时任务和执行日志 |
| `background_tasks` | 后台任务 |
| `eval_batches` / `eval_trials` | 评估批次和 Trial |
| `eval_tool_calls` / `eval_scores` | 工具轨迹和评分 |

### 7.2 完整历史与模型上下文

系统将两类会话数据分离：

- `messages` 是用户可看到的完整历史，追加写入，不因压缩被摘要覆盖。
- `session_contexts` 是模型当前可用的上下文，可以裁剪、降级或摘要。

Session 从内存淘汰或进程重启后，会分别加载两套数据。该设计避免“模型上下文压缩后，前端历史突然消失”。

### 7.3 Run 状态

| 状态 | 含义 |
|---|---|
| `running` | 正在执行 |
| `completed` | 正常完成 |
| `failed` | 执行失败 |
| `canceled` | 用户取消 |
| `interrupted` | 进程异常退出或启动恢复时发现遗留 |

可由人工从安全点继续的状态受 `safe_to_resume` 控制。

### 7.4 数据保留

- PostgreSQL 保存业务状态和审计数据。
- `DATA_DIR/.transcripts/` 保存上下文压缩前的 transcript。
- 大工具结果可落盘，模型上下文只保留预览。
- `eval/reports/` 和 `eval/.runtime/` 是本地运行产物，不提交 Git。

运维备份至少应覆盖 PostgreSQL。若需要完整保留 transcript、工具输出和临时运行材料，还应备份 `DATA_DIR`。

## 8. 部署与配置

### 8.1 运行要求

- Python 3.11+
- PostgreSQL 16+
- Node.js 18+，仅构建前端时需要
- Docker 和 Docker Compose，可选

### 8.2 本地启动

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
alembic upgrade head
python scripts/check_persistence.py
python run.py
```

Linux/macOS：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
python scripts/check_persistence.py
python run.py
```

前端开发：

```bash
cd frontend
npm ci
npm run dev
```

生产构建：

```bash
cd frontend
npm run build
cd ..
python run.py
```

构建产物输出到 `static/`，由 FastAPI 挂载到 `/ui`。

### 8.3 基础配置

```env
MODEL_ID=deepseek-chat
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_API_KEY=replace-me

DATABASE_URL=postgresql+psycopg://ai_devops:change-me@127.0.0.1:5432/ai_devops
API_AUTH_TOKEN=replace-with-a-long-random-token
TARGET_BROWSE_ROOTS=/opt,/srv
```

前端启用认证时：

```env
# frontend/.env.local
VITE_API_TOKEN=replace-with-a-long-random-token
```

### 8.4 关键配置说明

| 变量 | 说明 |
|---|---|
| `MODEL_ID` | 主模型 ID |
| `ANTHROPIC_BASE_URL` | Anthropic 兼容服务地址，为空时使用官方地址 |
| `ANTHROPIC_API_KEY` | 模型服务密钥 |
| `FALLBACK_MODEL_ID` | 连续 529 时的降级模型 |
| `DATABASE_URL` | PostgreSQL SQLAlchemy URL |
| `DATA_DIR` | transcript、工具结果和运行数据根目录 |
| `API_AUTH_TOKEN` | API Bearer Token；对外部署必须设置 |
| `API_AUTH_USER` | Token 对应身份 |
| `API_AUTH_ROLES` | Memory 可见性角色 |
| `TARGET_BROWSE_ROOTS` | 允许浏览和绑定 Target 的绝对目录 |
| `SANDBOX_ENABLED` | 是否启用临时文件工作区 |
| `ENABLE_UNSAFE_MCP_SHELL` | 是否允许自定义 MCP Shell Handler |
| `ENABLE_MOCK_MCP` | 是否加载内置 Mock MCP |
| `ALLOWED_ORIGINS` | 允许的 CORS 来源 |
| `DB_POOL_SIZE` | 数据库连接池大小 |
| `DB_MAX_OVERFLOW` | 连接池溢出上限 |
| `DB_CONNECT_TIMEOUT` | 数据库连接超时秒数 |

### 8.5 Docker Compose

```bash
docker compose up --build
```

Compose 启动 API 和 PostgreSQL，并在 API 启动前执行迁移。

注意事项：

- 容器内数据库主机名为 `postgres`，不能使用宿主机 `127.0.0.1`。
- Compose 不构建前端。需要 `/ui` 时，先在宿主机执行 `cd frontend && npm ci && npm run build`。
- 数据库端口只绑定到宿主机 `127.0.0.1:5432`。

### 8.6 健康检查

```text
GET /health
```

该接口返回服务、工作目录和数据库可达状态，不返回数据库密码。数据库不可达时，系统没有文件存储兜底，聊天和大部分业务接口不可用。

## 9. 安全与权限边界

### 9.1 风险控制链

系统通过以下层次降低误操作风险：

1. Target 选择明确操作项目。
2. Target 文件路径限制在项目根目录。
3. 敏感文件名默认阻止。
4. 工具 Policy 区分只读、写入和高风险操作。
5. 高风险操作进入人工审批。
6. 审计事件记录动作和结果。
7. Run 安全点避免崩溃后自动重放工具。

### 9.2 不能替代的安全措施

- Bearer Token 不是完整的多用户认证系统。
- 审批不是操作系统权限控制。
- Bash 以 Agent 进程权限执行，可访问宿主机资源。
- Target 路径校验只保护 Target 文件工具，不能约束已批准的任意 Bash。
- Sandbox 只隔离部分文件工具的工作目录。
- MCP Stdio 可以启动本地子进程。
- Memory 和审计中不应写入秘密。

### 9.3 部署建议

- 使用专用低权限系统账号运行 Agent。
- 将服务放在可信内网，限制来源 IP。
- 在反向代理层增加 TLS、登录、访问日志和请求限流。
- 为数据库使用独立账号和最小权限。
- 为模型 API Key、数据库密码和 API Token 使用环境变量或密钥管理服务。
- 对部署命令、重启命令和 MCP Server 配置执行代码审查。
- 设置审批等待、反向代理超时和连接数上限。

## 10. 故障处理

| 现象 | 检查项 | 处理方式 |
|---|---|---|
| 页面打不开 | `/health`、`static/`、后端进程 | 检查服务状态并重新构建前端 |
| 页面接口返回 401 | 前后端 Token | 使 `API_AUTH_TOKEN` 与 `VITE_API_TOKEN` 一致 |
| 页面正常但数据库报错 | `DATABASE_URL`、PostgreSQL、迁移 | 检查连接，执行 `alembic upgrade head` |
| 无法浏览项目目录 | `TARGET_BROWSE_ROOTS` | 配置绝对路径并重启服务 |
| Target 文件工具失败 | 当前 Target、路径、敏感文件名 | 激活正确项目并确认路径位于 root 内 |
| Agent 不执行写入或重启 | 工具 Policy、审批页面 | 检查待审批动作并确认是否拒绝或超时 |
| 审批已批准但没有结果 | 审批历史、审计、Background Task | 检查 `confirmed` 后执行结果和后台任务 |
| Run 中断后无法继续 | `safe_to_resume`、在途工具 | 人工确认工具是否执行，再决定是否重试 |
| 前端历史消失 | `messages`、Session 是否重置 | 区分会话恢复和上下文压缩，检查数据库中消息 |
| 上下文持续压缩 | transcript、工具输出大小 | 使用专用工具限制输出，缩短任务或清理旧 Session |
| MCP 已连接但无工具 | Server 能力、`mcp__` 工具列表 | 重新连接并检查工具发现结果 |
| 评估启动后很慢 | Trial 数、并发、模型延迟、Judge | 先做 `--validate-only` 或单用例小样本 |
| 评估报告未出现 | `eval/reports/`、评估进程状态 | 查看运行日志和报告输出目录 |
| Bash 被重定向 | 命令是否命中只读规则 | 使用专用工具；确需 Bash 时使用明确的 `force:` 流程 |

排障优先顺序：

1. `/health`
2. 当前 Session 和 Target
3. 审批页面
4. 审计事件
5. 恢复页面
6. PostgreSQL 状态与迁移
7. 服务进程日志

## 11. 已知限制

- 当前部署模型为单实例，不提供跨实例 Session 调度。
- Session 缓存、运行锁、取消事件、审批等待和 MCP 连接包含进程内状态。
- 不支持多租户隔离，身份模型经过简化。
- 取消事件不能强制终止已经进入同步系统调用的工具。
- 任务依赖图没有环检测和完整 CAS。
- Memory 使用词法、CJK bigram 和元数据检索，不使用向量数据库。
- 上下文按字符数估算，不是精确 Token 计数。
- `text_delta` 不是模型原生 Token Streaming。
- Sandbox 只在 Run 期间存在。
- Cron 和后台任务依赖当前单进程运行模型。
- Memory 和后台任务没有独立前端页面。
- MCP 页面当前未放入侧栏，需要通过 `?view=mcp` 进入。
- 评估回归门禁要求调用方生成并上传 baseline/current 报告。

## 12. 维护与变更流程

一次涉及运行行为的变更建议按以下顺序完成：

1. 在分支中修改代码。
2. 如涉及数据库，创建 Alembic 迁移。
3. 增加或更新单元测试与 PostgreSQL 集成测试。
4. 为 Prompt、模型、工具策略或安全行为增加评估用例。
5. 运行测试、前端构建和 `--validate-only`。
6. 使用固定模型和标签运行正式评估。
7. 与基线比较，分析通过率、成本、耗时和高风险回归。
8. 更新 README、软件说明书、工具参考和变更记录。
9. 合并到 `main` 前确认迁移头、配置示例和部署说明一致。

文档维护原则：

- 配置项以代码默认值为准。
- API 以 OpenAPI 为准。
- 工具行为以 Policy 和 Handler 为准。
- 安全边界必须同时描述已实现能力和未覆盖风险。
- 不使用无法复现的截图替代命令、字段和状态说明。

## 13. 附录

### 13.1 页面查询参数

可以通过 `/ui/?view=<name>` 直接进入页面：

```text
chat
tasks
cron
tools
mcp
skills
actions
audit
recovery
sandboxes
targets
eval
```

### 13.2 主要 API

| 域 | 路径 |
|---|---|
| 对话 | `/api/chat/`、`/api/chat/stream`、`/api/chat/cancel` |
| 消息 | `/api/messages/` |
| Session | `/api/chat/sessions`、`/api/reset/` |
| Target | `/api/targets/`、`/api/targets/browse`、`/api/targets/{id}/activate` |
| 审批 | `/api/actions/pending`、`/api/actions/pending/{id}/confirm`、`/cancel` |
| 任务 | `/api/tasks/`、`/{id}/claim`、`/{id}/complete` |
| Cron | `/api/cron/`、`/api/cron/logs` |
| Memory | `/api/memory/`、`/{id}/approve` |
| 审计 | `/api/audit/events`、`/timeline`、`/runs/{run_id}` |
| 恢复 | `/api/recovery/runs`、`/{run_id}`、`/{run_id}/resume/stream` |
| MCP | `/api/mcp/`、`/connect`、`/stdio/connect`、`/sse/connect` |
| Skill | `/api/skills`、`/{name}`、`/reload` |
| 评估 | `/api/eval/batches`、`/reports/{batch_id}`、`/compare`、`/run`、`/runs` |
| Sandbox | `/api/sandboxes/` |

### 13.3 状态速查

Run：

```text
running / completed / failed / canceled / interrupted
```

审批：

```text
pending / confirmed / executed / failed / canceled
```

任务：

```text
pending / in_progress / completed / blocked
```

评估类别：

```text
core / boundary / abnormal / faq
```

### 13.4 相关文档

| 文档 | 用途 |
|---|---|
| `README.md` | 项目概览、快速开始和配置入口 |
| `docs/architecture.md` | 系统架构、主链路、分支和状态机 |
| `docs/tools-and-policies.md` | 工具注册、参数和策略说明 |
| `docs/context-management.md` | 上下文管理和压缩设计 |
| `docs/evaluation-regression-ci.md` | 评估回归 CI 工作流 |
| `docs/incident-postmortems.md` | 工程故障复盘与改进记录 |
| `docs/performance-tuning.md` | 性能与成本调优记录 |

### 13.5 修订记录

| 日期 | 版本 | 说明 |
|---|---|---|
| 2026-11-13 | 1.0 | 建立正式软件说明书，覆盖功能、操作、架构、代码结构、部署和安全边界 |

# AI DevOps Agent 优化记录

> **说明**：本文件用于面试讲解数据驱动调优，数据来自真实生产部署（腾讯云 2核2G 服务器，deepseek-chat 模型），全部数字取自 2026-10-13 ~ 10-15 的线上日志与同负载复测记录，未经修饰。每条优化按「问题现象 → 根因分析 → 改动措施 → 优化前后对比」组织。

## 时间线总览

| 日期 | 事项 | 关键产出 |
|---|---|---|
| 2026-10-13 | 工具调用分布分析 + bash 专用工具化 | 基线 967 次调用分布、43% 可替代明细、拦截层（`71eb457`） |
| 2026-10-14 | token 消耗分析与上下文膨胀修复 | 32 轮 ctx 曲线、三重根因、四条修复（`c7daeda`） |
| 2026-10-14 | usage 记录改造 | 真实 token 记账 + 成本估算（`8df86c3`） |
| 2026-10-15 | 部署后复测与简历数据 | ctx 峰值 -80.6%、单次成本 -71%、API 最大耗时 114s→8s |

---

## 一、2026-10-13：工具调用分布分析与 bash 专用工具化

### 1.1 问题现象（带数据）

导出线上工具调用分布表，总样本 **967 次**，结构极度头部集中：

| 层级 | 工具 | 占比 |
|---|---|---|
| 头部 | bash **535 次（55%）** + list_background_tasks 151 次（16%） | **71%** |
| 腰部 | target_read_file 97 次（10%） | 81% |
| 长尾 | 其余 27 个工具 | 不到 20% |

- 专用巡检工具（port_listen 14 + process_search 12 + disk_usage 10 + cpu_usage 3 + process_top 2 + memory_usage 2 + system_info 1 + network_interfaces 1）合计仅 **46 次**，bash 是它们的 **12 倍**。
- 对 535 次 bash 抽样分类：**43%（234 条）可用现成专用工具替代**，56%（308 条）必须 bash。

「可替代」明细 TOP（有现成工具却用 bash）：

| 应改用 | 次数 | 典型命令 |
|---|---:|---|
| `target_http` | 76 | `curl -s -o /dev/null -w "HTTP %{http_code}" http://127.0.0.1:8000/` |
| `port_listen` | 59 | `ss -tlnp \| grep 8001` |
| `target_list_files` | 47 | `cd /opt/... && ls -la` |
| `target_read_file` | 15 | `tail -60 /var/log/xxx.log` |
| `process_search` | 12 | `pgrep -af "pip install"` |
| `process_top` | 8 | `ps -ef \| grep uvicorn` |
| `disk_usage` | 5 | `df -h; free -h; uptime` |
| 其余（ping_host 4 / target_glob 3 / cpu_usage 2 / network_interfaces 2 / memory_usage 1） | 12 | — |

- list_background_tasks **151 次轮询**：pipeline 已有「后台任务完成通知自动注入」机制，不需要反复查，151 次 = 151 轮 LLM 调用纯浪费。
- 五个工具 0 调用（create_task / schedule_cron / spawn_subagent / update_memory 等）；记忆系统 967 次调用里 search_memory 只有 3 次、add_memory 1 次——大量重复调查在反复发生。
- 附带成本：架构里 **bash 需用户审批、专用工具不需要**，234 次可替代 bash 意味着 234 次本可避免的人工审批打断（每次审批 = 循环阻塞 + 等待 + 可能超时）。

### 1.2 根因分析（带数据）

- **无提示词政策约束**：LLM 预训练里 bash 肌肉记忆很强，提示词是「软约束」，必须配合确定性手段。
- **target_http 适用面太窄**：76 次 curl 打的是 `127.0.0.1:8000`（检查被管服务健康），而 target_http 要求激活的 target 且配了 health_url——agent 绕道根因不是「不知道有工具」，而是缺一个不限定 target 的通用 `http_check(url)`。
- **归类修正后仍有 40% 干净替代**：`getent hosts` 是 DNS 解析（ping_host 是 ICMP）、`curl ifconfig.me` 查公网出口 IP（network_interfaces 查本机网卡），这两类替代不了；`tail` 日志场景更该用 target_logs；`df -h; free -h; uptime` 一条顶三件。逐条修正后真正干净替代约 **215 条（40%）**。
- **未知工具默认策略是 HIGH + 强制审批**（policy.py），新工具必须显式注册成免审批，否则做了也用不上。

### 1.3 改动措施（commit `71eb457`，161 个测试全绿）

| 文件 | 改动 |
|---|---|
| ops.py | 新增 `http_check` 工具：stdlib urllib 实现（不走 shell），返回状态码 + 响应耗时 |
| policy.py | `http_check` 注册为 READ_ONLY 免审批 |
| shell.py | `suggest_tool_for_command` 匹配器：7 条规则 + curl GET 识别；复合命令（&&/;）不拦、`force:` 前缀放行（逃生门防误拦死循环）；ls/find/tail 故意不拦（shell.py 拿不到当前 target，误拦风险高，交给提示词） |
| tool_loop.py | 在**审批闸之前**拦截 bash：命中规则不执行、不创建审批，直接返回 "Redirected: use `xxx`"，LLM 下一轮自动换专用工具 |
| context_manager.py | 系统提示词补充拦截说明 |
| tests/test_bash_redirect.py | 15 个新测试（命中/放行/逃生门/http_check 真实请求） |

### 1.4 优化前后对比

- **可拦截预期**：curl(76) + ss(59) + df/free/uptime(8) + pgrep/ps(20) ≈ **163 次可替代 bash 会被拦下转专用工具，同步省掉 163 次审批打断**；ls/tail 类（62 次）靠提示词政策收敛。
- **基线 → 目标指标表**（量化验证 prompt 工程效果）：

| 指标 | 基线 | 目标 |
|---|---|---|
| bash 占比 | 55% | <35% |
| 巡检类命令走专用工具比例 | ~8% | >50% |
| 每后台任务轮询次数 | ~10（估） | ≤2 |
| search_memory 每百次调用 | 0.3 | >5 |
| create_task / cron / subagent | 0 | >0 |

- **10-15 复测如实记录**：纯部署 run 中 bash 占比反而为 25/31=81%——不是拦截层失效，而是纯部署任务（git/npm/systemctl）天然 bash 密集，与 967 次混合任务基线不可比；拦截效果需混合任务跑一段时间后复测回填。

---

## 二、2026-10-14：token 消耗分析与上下文膨胀修复

### 2.1 问题现象（带数据）

让 agent 重新部署项目，约 30 轮后思考时间明显增加、token 明显增加，一次约 ¥3。从 app.log 拉出该次 run（32 轮）的逐轮 ctx 曲线：

| 轮次 | ctx 字节 | 该轮耗时 |
|---:|---:|---:|
| 14 | 49,412 | 7s |
| **16–18** | **245,669 / 245,604 / 246,422** | 5–6s |
| **20–22** | **214,340 / 214,000 / 213,600** | 3s |
| **25–27** | **242,033 / 241,000 / 240,700** | 3s |
| 28 | 23,420 | **56s** |
| **30** | **240,511** | **114s** ← 用户观察到的「思考时间明显增加」 |

- 不是「越跑越慢」的渐进劣化，而是**上下文反复冲到约 24 万字节再掉回 2 万，来回振荡**；每一次冲高，那一轮 API 调用就要重新发送整包历史。
- 低 ctx 轮耗时 2–7 秒，高 ctx 轮 50–114 秒。整 run 累计 **341 万字节**，其中 11 个高 ctx 轮占 **258 万字节（75.8%）**。
- 成本估算：消息历史 3.41M 字符 ≈ 0.85M–1.1M tokens；固定开销 ≈29 万 tokens（45 个工具 schema + system prompt ≈9k tokens × 32 轮，不进 ctx 统计）；输入合计 ≈1.15M–1.4M tokens；输出 ≈2–3 万 tokens。按 deepseek-chat 输入 ¥2/M 估：**≈¥2.5–3.0**，与「一次 3 块」吻合。
- 同类 run 横向：08:34 的 run（12 轮）累计 ≈110 万字节（1,096,607）；09:54 的新 run 第 1 轮 ctx 就是 259k——**消息历史跨 run 保留**，一次部署留下的「历史包袱」持续给后续对话加价。

### 2.2 根因分析（三个叠加，都在代码里）

1. **历史里存的是未截断的原始输出（最关键）**：pipeline.py 发给前端的 `output_str` 截断到 2000 字符只影响 SSE 显示，回填进 messages 用的是 `str(output)` 原文——**「看到的不等于发出去的」**。这个 bug 隐蔽到看代码容易漏，是靠逐轮 ctx 曲线的周期性尖峰反向定位的。
2. **单条工具输出上限 50,000 字符**（shell.py / targets/tools.py 各 `[:50000]`），micro_compact 保留最近 3 条 tool_result → 3×50KB + tool_use 入参 ≈ 24 万字节——正好解释峰值为什么是 24 万而不是线性增长。
3. **字节闸口形同虚设**：`tool_result_budget(max_bytes=200000)` 上限给到 20 万字节；`snip_compact` 只按消息条数（50 条）裁剪、根本不控字节——24 万字节时消息才 30 多条，它直接 return 不裁。

### 2.3 改动措施（commit `c7daeda`，168 个测试全绿）

| # | 位置 | 改动 |
|---|---|---|
| 1 | pipeline.py | 回填历史从 `str(output)` 原文改为 `history_tool_content()`：超 8000 字符落盘 `data/.task_outputs/tool-results/`，历史只留 6000 字符头尾采样预览 + 文件路径，agent 需要细节时可用 target_read_file 取回 |
| 2 | config.py | `PERSIST_THRESHOLD` 30000→**8000**；新增 `CONTEXT_BYTES_BUDGET=120000`、`HISTORY_TOOL_LIMIT=6000`；`tool_result_budget` 上限 200000→**60000** |
| 3 | shell.py / targets/tools.py | 单条输出上限 50000→**8000**，头尾各半采样（保住开头的命令回显和结尾的报错） |
| 4 | context_compact.py | 新增 `trim_by_size()` 按**字节**裁剪（保留首条消息 + 最近尾部，字节级硬闸），接入 `_compact_if_needed` |

新增 7 个测试，其中 `test_compact_if_needed_bounds_spiky_history` 直接复现服务器场景（3×60000 字符输出 → 压缩后回到 12 万字节预算内）。

### 2.4 优化前后对比

同任务同负载复测（见第四节复测表）：ctx 峰值 24.6 万字节 → 4.8 万以内，高 ctx 轮 50–114 秒的延迟回到秒级，单次成本 ¥3 → ¥0.8649。

---

## 三、usage 记录改造：让成本可观测

### 3.1 问题现象

- 之前只能靠 ctx 字节数**估算** token，无法精确到 token 和金额——成本不可见就无法持续优化。
- 分析期间顺带发现 **cache_read=0**：micro_compact 每轮重写历史中部的旧 tool_result（替换成占位符），加上旧的被丢弃、新的顶格插入，**前缀一直在变**，prompt cache 几乎全 miss——全部按 cache-miss 价（¥2/M）计费而非 cache-hit（约 ¥0.5/M），成本差 4 倍。

### 3.2 改动措施（commit `8df86c3`，172 个测试全绿）

**每轮一行**：

```
[turn 16] tokens in=58710 out=312 cache_read=0 cache_write=0
```

**每个 run 一行汇总**（done 之前）：

```
[usage] run run_9f3a... turns=32 calls=32 in=1157869 out=24012 cache_read=0 est_cost=¥2.5078
```

**done 事件携带 usage**，前端可直接显示：

```json
{"type":"done","text":"...","total_turns":32,
 "usage":{"calls":32,"input":1157869,"output":24012,"cache_read":0,"cache_write":0,"est_cost_cny":2.5078}}
```

| 位置 | 改动 |
|---|---|
| config.py | 新增三条单价常量（输入 ¥2/M、输出 ¥8/M、缓存命中 ¥0.5/M），换模型改三行 |
| pipeline.py | run 开始时重置累计值（断点续跑也重置）；`_usage_summary()` 汇总 + 成本估算 |
| tool_loop.py | 在唯一 API 出口 `_call_api` 处挂钩，所有调用（含重试成功的）都记账；取 SDK 返回的 `response.usage` 真实值，不再靠字节估算 |

新增 4 个测试（累加与成本计算、无 usage 时不报错、`_call_api` 挂钩、done 事件携带 usage 且新 run 重置）。

### 3.3 优化前后对比

- 从「ctx 字节估算」升级为「response.usage 实测」：usage 上线后首次复测 run 实测输入 **409,732 tokens、成本 ¥0.8649**，成本从估算值变成可对拍的实测值。
- cache_read/cache_write 单独记录，直接验证了「缓存命中率低」的判断（复测 run cache_read 全程为 0），引出下一步「历史前缀稳定化」优化。

---

## 四、2026-10-15：部署后复测与简历数据

### 4.1 复测数据（同任务同负载：部署一个项目，run_eddfe23d，32 轮）

| 指标 | 优化前 | 复测实测 | 变化 |
|---|---:|---:|---:|
| 单轮 ctx 峰值 | 246,422 B | **47,763 B** | **-80.6%** |
| 输入 tokens | ~1.15M–1.4M（估算） | **409,732**（usage 实测） | 约 -70% |
| 单次成本 | ≈¥3 | **¥0.8649** | **-71%** |
| API 单轮最大耗时 | 114s | **8s** | **-93%** |
| API 平均耗时 | 尖峰期 3–6s / 56s / 114s 混杂 | 3.8s | 稳定 |

- **ctx 曲线形态完全变了**：优化前是 4 组尖峰振荡（24k→245k→33k→214k…），优化后是单调平滑增长（24k→48k，每轮只涨约 600B），尖峰彻底消失——大输出截断 + 落盘机制按设计生效。
- 本次 run 工具调用共 31 次：bash 25 次 / 540s（部署命令本身慢 + 含审批等待）；target_write_file 3 次 / 917s（主要是人工审批等待，不是工具慢）；list_background_tasks 3 次（对比基线同周期 151 次，骤降）。
- 整 run 墙钟 1578s，API 只占 122s，其余 1458s 几乎全是工具执行 + 人工审批等待时间。
- 两点如实说明：① bash 占比 81% 系任务性质（见 1.4）；② cache_read 全程为 0，证实缓存完全没命中，成本还有约 4 倍压缩空间（前缀稳定化是下一步）。

### 4.2 简历数据（可直接引用）

- 一句话（项目经历 bullet）：
  > 基于 32 轮运行数据定位 AI Agent 上下文膨胀根因，通过工具输出截断、字节级预算控制与历史消息采样，将单轮 token 成本降低 71%、上下文峰值降低 80.6%。
- 个人优势段：
  > 曾针对 AI Agent 上下文膨胀导致的延迟与成本上升，通过工具输出裁剪、字节级预算控制、历史消息落盘采样等手段，将单轮上下文峰值从 24 万字节降至 4.8 万字节，API 调用成本下降约 71%。
- 数据闭环链路：运行时全量埋点（每轮日志、response.usage 真实记账、审计事件全部落盘）→ 分析数据定位上下文膨胀根因 → 修复后复跑同负载验证 → 验证结果成为下一轮基线（复测发现缓存全 miss，引出前缀稳定化优化）。数据不只是运行产物，而是反馈输入。

### 4.3 数据可靠性标注

- ✅ **实测**：工具分布 967 次、bash 占比 55%、bash 抽样 43% 可替代、单轮 ctx 峰值 246,422 字节、单 run 累计 341 万字节、56s/114s 延迟、复测 47,763 / 409,732 / ¥0.8649 / 8s
- 📐 **可推导估算**：修复前成本 ≈¥2.5–3.0（文中给出完整计算过程，且与实测「一次 3 块」吻合）
- 🎯 **待复测回填**：bash 拦截层的最终拦截率（预期 163 次/约 34%）、提示词收敛效果——需混合任务跑一段时间后重新导出分布表对比

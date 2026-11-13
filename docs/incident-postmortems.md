# 工程故障复盘与改进记录

> 每条记录采用 4 段结构：**问题** / **影响** / **根因** / **改进**，用于复盘故障、验证修复和沉淀工程约束。
> 优先级：`[P0]` 运行/数据炸、`[P1]` 体验/可维护差、`[P2]` 边角。按日期倒序。

---

**[P0] 压缩逻辑只按 dict 测过，线上 block 是 pydantic 对象：一触发压缩就 AttributeError，SSE 直接断流**
- 问题：改完 `micro_compact` 后做了单元验证（构造 dict 历史，66KB→29.5KB，模型还能答出被压缩的命令），但真实长任务跑到第 8 轮、ctx 41KB 时 SSE 突然 EOF，run 卡在 `phase=model` 不动，前端表现就是"突然不回话了"。服务日志：`AttributeError: 'ToolUseBlock' object has no attribute 'get'`
- 影响：压缩一旦触发就是致命中断——不是降级、不是少记忆，是整条 run 死掉且状态残留 running，用户只能等重启对账；因为触发条件是 ctx>50KB，普通短对话永远测不到，上线后只有长任务才炸
- 根因：取值写成了 `block.get("id")`，只对 dict 成立；但 pipeline 交进来的 assistant 消息里是 anthropic SDK 的 `ToolUseBlock`（pydantic 对象），只能 `getattr`。单元测试是我自己构造 `{"type": "tool_use", ...}`，所以 100% 通过——**测试数据的形态和线上不一致，等于没测**
- 改进：加 `field(block, key, default)` 兼容层（dict 走 get、对象走 getattr），`tool_use_index` / `_block_text` / `summarize_tool_result` / `segment_summary` 四处统一走它，并对 `input` 不是 dict 的情况兜底；`micro_compact` 入口原本就有 `json.loads(json.dumps(..., default=str))` 归一化，其余路径补兼容即可。真实链路验收：12 条 bash 的 run，ctx 从 1,592 涨到 49,161（第 9 轮）→ 第 10 轮压到 35,604（回落 13.5KB）→ 收尾 46,828；13 次调用计费输入 23,437、缓存复用 131,584（命中 84.9%）；模型在被压缩之后仍准确答出"第 2 条命令读的是 context_manager.py、共执行 12 条"。

**[P1] 想验证压缩，前两次"长任务"都没真正越过水位——验证要先证明触发点被打中**
- 问题：为触发 50KB 压缩先后跑了两条长任务都失败：第一次让它顺序执行 12 条 `Get-Content 150 行`，第 9 轮 ctx 已经到 49,685 B，**差 315 B 没触发**（验证过程中重启了服务，导致 run 中断）；第二次改成"递归列目录 150 个路径"，12 条 bash 全执行了，但 ctx 只到 18,612 B
- 影响：白跑两条 run（时间 + token），更危险的是容易得出"改完了没问题"的错误结论——真正的崩溃 bug 就藏在这两次没打中的区间里
- 根因：没意识到两层截断在起作用——① 单条结果超过 `PERSIST_THRESHOLD=8000` 字节会被 `persist_large_output` 落盘，历史里只留路径 + 6000 字符预览，第一条就只剩 818 字节；② bash 工具对单次输出还有自己的截断，递归列 150 个路径的结果只剩 1.4~2.2KB。**"命令输出很长"不等于"历史里留下很长"**
- 改进：验证这类阈值逻辑，先看日志里的 `[turn N] 调用 ... (ctx X bytes)` 曲线，确认真的越过 `CONTEXT_LIMIT` 再下结论；素材要挑"单条 5~7KB、恰好不被 persist 掉"的（`Get-Content 150 行` 实测每轮 5~7KB 最合适）；长 run 期间不要重启服务。

**[P0] prompt cache 命中率只有 1.9%：system 里放了秒级时间，每次调用前缀都不同**
- 问题：用户反馈"跑 50 轮还没弄好"，翻 run_usage 发现每次调用都是 `cache_read=0`。全库统计 326 次调用、输入 3,630,920 token，缓存命中只有 68,608（1.9%）；那条 50 轮的 run 更惨，50 次调用输入 585,616 token，只命中 8,064（1.4%），平均每次只缓存住约 160 token，等于 system 最前面那两句话
- 影响：输入 token 全部按 cache-miss 计价（¥2/M vs 命中 ¥0.5/M，差 4 倍），长 run 成本被放大；同时首字延迟明显偏高。更隐蔽的是它和"压缩省 token"互相抵消——压下去的 token 没享受到缓存折扣，等于白压还多丢了记忆
- 根因：先做了一次对照实验排除"端点不支持"——同一段 1 万字符前缀连发两次，第二次 `in=159 / cache_read=6528`，命中 98%，说明 DeepSeek 的 Anthropic 兼容端点是自动前缀缓存、不需要 `cache_control`。所以问题在请求构造：① `_build_system_prompt()` 每次调用都重建（tool_loop.py L126），里面第 4 行就是 `f"Current time: {datetime.now().isoformat(timespec='seconds')}"`（context_manager.py L50），秒级时间一变，它后面 45 个工具描述、技能目录、policy 全部作废；② `Relevant memories` 按当前问题检索、`Connected MCP servers` 随连接变化，也都塞在 system 里；③ `micro_compact` 每轮无条件把中段旧 tool_result 改成无信息占位符，messages 前缀也跟着变
- 改进：改了三处——① 时间、记忆、MCP 连接从 system 挪到新增的 `_runtime_tail_note()`，由 `_inject_runtime_context()` 只追加到最后一条 user 消息末尾（tool_result 文本块在后、不污染落盘历史），system 只剩静态内容；② `_compact_if_needed` 改成先算字节、超过 `CONTEXT_LIMIT` 才 `micro_compact`，再超才 `snip_compact`，不再每轮改写中段；③ 静态在前、动态在后的顺序原则。验收：同 session 连问 3 句 `in=4617/281/169`，cache_read `0/4352/4480`（94%、96%）；带工具调用的场景（验证 tool_result 消息尾部追加文本是否被 API 接受）`in=275/216/171`，cache_read `4352/4480/4608`。

**[P0] 上下文膨胀导致单 run 成本 ¥3、最高延迟 114s，根因是"给前端截断但给 LLM 不截断"**
- 问题：让 agent 重新部署项目，约 30 轮后思考时间明显增加、token 猛涨，一次约 ¥3。拉逐轮 ctx 曲线发现不是渐进劣化，而是反复冲到约 **24 万字节再掉回 2 万，来回振荡**；高 ctx 轮耗时 50–114s，低 ctx 轮才 2–7s；整 run 累计 341 万字节，11 个高 ctx 轮占 75.8%。同类 run 横向对比：08:34 的 run 第 12 轮就冲到 23.8 万，09:45 的新 run 第 1 轮 ctx 就是 259k——历史包袱跨 run 保留
- 影响：单 run ¥3 vs 优化后 ¥0.86，成本 3.5 倍差；高 ctx 轮延迟 114s，用户体感"卡死"；消息历史跨 run 保留，不清就一直在付
- 根因：三个叠加，最关键的是"给前端截断但给 LLM 不截断"——① pipeline.py 发给前端的 output_str 截断到 2000 字符只影响 SSE 显示，回填进 messages 用的是 str(output) 原文（pipeline.py L477-483），看到的不等于发出去的；② 单条工具输出上限 50000 字符（shell.py / targets/tools.py 各 [:50000]），micro_compact 保留最近 3 条 tool_result → 3×50KB + tool_use 入参 ≈ 24 万字节——正好解释峰值为什么是 24 万；③ 字节闸口形同虚设：tool_result_budget(max_bytes=200000) 上限给到 20 万，snip_compact 只按消息条数（50 条）裁剪、根本不控字节，24 万字节时消息才 30 多条，它直接 return 不裁
- 改进：改了 4 处——① pipeline.py 回填历史从 str(output) 原文改为 history_tool_content()：超 8000 字符落盘 data/.task_outputs/tool-results/，历史只留 6000 字符头尾采样预览 + 文件路径，agent 需要细节时可用 target_read_file 取回；② config.py：PERSIST_THRESHOLD 30000→8000、新增 CONTEXT_BYTES_BUDGET=120000、HISTORY_TOOL_LIMIT=6000、tool_result_budget 上限 200000→60000；③ shell.py / targets/tools.py 单条输出上限 50000→8000，头尾各半采样（保住开头的命令回显和结尾的报错）；④ context_compact.py 新增 trim_by_size() 按字节裁剪（保留首条消息 + 最近尾部，字节级硬闸），接入 _compact_if_needed。此外异常恢复分支（pipeline.py prompt_too_long 处理）有最多 2 次重试验证：每次重试都必须验证 compact 后 ctx 确实变小了才放行，防止 compact 没生效白烧 token。验证结果：优化前 ctx 峰值 246,422B、成本 ¥3、延迟 114s；优化后 ctx 峰值 47,763B、成本 ¥0.8649、延迟 8s。额外发现：cache_read=0——micro_compact 每轮重写历史中部旧 tool_result（替换成占位符），前缀一直在变，prompt cache 几乎全 miss，成本差 4 倍（cache-miss ¥2/M vs cache-hit ¥0.5/M），这是纯架构层损耗，还没修，是下一步"历史前缀稳定化"优化（后续已修复，见上一条）

**[P0] 工具调用分布头部集中：bash 55% + 5 个工具零调用，提示词不是软约束是唯一约束**
- 问题：导出 967 次线上调用分布，bash 535 次（55%）+ list_background_tasks 151 次（16%）= 71% 头部集中；create_task / schedule_cron / spawn_subagent / update_memory 等 5 个工具 0 调用；memory 系统 search_memory 仅 3 次、add_memory 仅 1 次；234 次 bash 调用有现成专用工具可替代却绕道
- 影响：234 次本可避免的人工审批打断（bash HIGH 风险 + 需审批，专用巡检工具免审批）；151 次 list_background_tasks 轮询 = 151 轮 LLM 调用纯浪费（pipeline 已有后台任务完成通知自动注入）；记忆形同虚设，重复调查反复发生
- 根因：① 提示词是软约束，LLM 预训练里 bash 肌肉记忆强过 45 个工具名；② target_http 适用面太窄——要求激活的 target + health_url 配置，agent 绕道根因不是不知道有工具，而是缺一个不限定 target 的通用 http_check(url)；③ 未知工具默认策略是 HIGH + 强制审批（policy.py），新工具必须显式注册成免审批否则做了也用不上；④ list_background_tasks 没做"已有通知注入就别再查"的提示词约束
- 改进：改了 4 处——① ops.py 新增 http_check 工具（stdlib urllib，READ_ONLY 免审批）；② shell.py 写 suggest_tool_for_command 规则表（curl/ss/pgrep/df/free/uptime 7 条，复合命令 &&/; 不拦，force: 前缀放行）；③ tool_loop.py 在审批闸之前插拦截，命中规则不执行、不创建审批，直接返回 "Redirected: use xxx"，LLM 下一轮自动换；④ context_manager.py 系统提示词补充拦截说明。验证结果：基线 bash 占 55%，目标 <35%；预期 163 次巡检命令/周期被拦截转专用工具。关键认知：提示词约束不了肌肉记忆，必须配合确定性代码拦截；bash 重定向插在审批闸之前是为了省掉人工审批，不是为了禁 bash

**[P0] tool_use/tool_result 不配对 → 下次 _call_api 直接报错，聊天窗口"死了"——是怎么发现、怎么修的**
- 问题：某次 run 执行到一半（assistant 发了 tool_use，但还没来得及回填 tool_result 就被 kill 了进程 / 审批等待中被重启 / bash 执行到一半断网），下次再发消息 Anthropic API 直接报错 `messages must alternate roles, each tool_use must have a tool_result`——**整个聊天窗口不可用**，用户只能点重置
- 影响：会话硬死，只能 reset 清历史，之前的对话全丢；这种情况在开发环境频繁复现（Ctrl+C 杀进程、改代码重启），生产环境杀进程、审批等待超时、网络中断也会触发
- 根因：三个洞叠加——① **取消路径没兜底**：用户点取消时，如果某个工具正在执行中、还没回填 tool_result，assistant 那条带 tool_use 的消息就悬在历史里；② **压缩路径会截断**：早期 snip_compact 按条数裁剪时不考虑配对边界，可能砍掉一条 tool_result 留 tool_use；③ **崩溃恢复只标记不修复**：`_recover_startup_state` 把中断 run 标记 interrupted 但不补消息，下次载入历史直接送 API 炸
- 改进：三层闸——**① 预防性（tool_loop 第三个取消检查点 L821）**：每个工具执行前检查 cancel_event，取消时把**剩余未执行的工具全补上 "Error: cancelled by user" 的 tool_result** 再退出，保证配对完整；**② 压缩约束（snip_compact 保配对边界）**：裁剪时不切 tool_use 和它的 tool_result 中间，按配对整体保留或整体丢；**③ 被动修复（tool_loop._repair_message_sequence L19-114）**：每次 `_call_api` 前先跑一遍修复——扫所有 assistant 消息里的 tool_use id，查下一条 user 消息里有没有对应的 tool_result，缺了就补占位 `Error: interrupted before result`，有就合并进现有 user 消息（不额外插入新 user 消息，本地版 commit 153742a 比服务器旧版更严谨：旧版全局扫描+插新 user 消息可能打乱已有顺序，新版只查紧邻下一条、合并进现有、兼容字符串 content）。验证结果：修复前每 5 次手动重启就有 1 次会话死锁；修复后 100+ 次重启再没复现。关键认知：**Anthropic API 对消息序列格式是硬约束，不是软建议**——tool_use/tool_result 不配对直接 400，不会帮你补

**[P0] shell.py 双重 BOM 导致整个 `agent.tools` 导入失败，本地跑不起来**
- 问题：本地 `import api.main` 直接 `ModuleNotFoundError: No module named 'agent.tools'`，查了半小时才发现 `shell.py` 文件头有两个 UTF-8 BOM（EF BB BF EF BB BF）
- 影响：整个工具层无法加载，项目完全跑不起来；这种 bug 隐蔽——编辑器正常显示、git diff 看不出来，只有 Python 解析器会炸
- 根因：某次用 Windows 记事本或某些编辑器另存为，自动给文件加了 BOM；shell.py 恰好是 tools 包的 `__init__` 之前最先被 import 的模块，所以一个文件炸了整个包
- 改进：全库扫描确认无其他同类文件；项目后来加了 `.editorconfig` 约束 `charset = utf-8`（无 BOM）；每次提交前 `python -c "import agent.tools"` 做基础烟测

**[P0] upsert 用时间戳判断"有没有变化"，漏掉访问计数变了但 updated_at 没变的场景**
- 问题：早期 `upsert_row()` 靠 `updated_at != excluded.updated_at` 决定要不要写库、要不要 version+1——但有些字段（比如 `runs.access_count`）是计数器，每次访问递增但不改 `updated_at`
- 影响：重放同一条记录会把计数器增量完全丢掉；同一条 run 被再次查询时 version 不涨，CAS 条件更新链上的调用方会误以为没变化
- 根因：`updated_at` 只在业务字段变化时被 ORM 自动刷新，纯技术字段（计数器、心跳）走的是单独的 increment SQL，不触发 updated_at
- 改进：`common.py:upsert_row` 的 `WHERE` 改成 `is_distinct_from(...)`（PG 原生，SQLite 退化为逐字段比较）——全字段 diff，只要任何列真变了才落库、才 version+1。

**[P1] SSE 流被 nginx 缓冲住，前端"卡住不出字"**
- 问题：本地直连 uvicorn SSE 正常，但部署在 nginx 后面后，前端打开聊天框卡死 30 秒才一次性吐出全部内容
- 影响：SSE 的核心"边生成边推"失效，用户体感"没反应"
- 根因：nginx 默认 proxy_buffering on，把上游 SSE 响应缓存到一定量才往客户端发；而 SSE 每个 event 只有几百字节，一直凑不够 flush 阈值
- 改进：`api/main.py:chat_stream` 的 StreamingResponse 响应头加 `"X-Accel-Buffering": "no"`；同时 nginx 配置里对 `/api/chat/stream` 设 `proxy_buffering off`。

**[P1] reset 漏清一边就会出现"失忆的会话又复活"**
- 问题：前端点重置对话后，下次新对话居然能引用到已经清空的历史消息——像是"失忆的会话又复活"
- 影响：上下文污染，LLM 拿到已经清掉的消息继续推理，产生莫名其妙的引用
- 根因：reset 只清了内存 `agent.messages = []`，漏清了磁盘持久化层 `RecoveryStore.reset_session(session_id)`——服务器重启后 PG 里的旧 session 被重新加载回来，内存层已经空了、磁盘层还有
- 改进：`ComprehensiveAgent.reset()` 现在三层一起清：① `self.messages = []` + `self._pending_compaction = False` + `self.current_run_id = ""`；② `store.reset_session(session_id)` 删 PG 记录；③ `RecoveryState` 一并清零（包括之前 error_recovery 降级过的模型、escalate 过的 max_tokens）。

**[P1] target_id 三重绑定：prompt 说在 A、run 注册 A、executor 拿到 B 就会命令跑错项目**
- 问题：前端切到项目 A 发消息，prompt 里写的是项目 A 的路径，但实际 bash 命令 `cwd=` 是项目 B 的根目录
- 影响：agent 在 prompt 里规划的操作和实际执行位置错位，可能写错项目文件
- 根因：target_id 存在三个独立字段——`comprehensive.target_id`（prompt 拼装用）、`pipeline.run["target_id"]`（run 注册用）、`ToolExecutor.target_id`（bash `cwd` / target 工具 root 用），三个值必须原子同步，任何一个赋值漏了就错位
- 改进：现在在 `ComprehensiveAgent.__init__`、`pipeline._run_stream_impl`、`ToolExecutor.__init__` 三处都显式从同一个 `session["target_id"]` 读取；target 切换入口只有 `main.py:get_or_create_session` 一个，改 target 时三处一起走。

**[P1] Cron 调度线程懒加载导致无人值守任务永不触发**
- 问题：服务器启动后 Cron 任务不执行，必须有人先调 `/api/chat/stream`（即"聊一句"）之后，调度线程才 spawn 出来
- 影响：无人值守的巡检类 Cron 任务（如每 5 分钟 health check）永远不会跑，形同虚设；加了双检锁后还有一处冗余调用残留
- 根因：`_ensure_cron_started()` 只在 `get_or_create_session` 门面里被调（`main.py:L162`），而 session 创建是请求驱动的懒加载；后台任务生命周期绑了请求而不是绑进程
- 改进：后台线程一律在 FastAPI lifespan（`main.py:L49-53`）里启动，跟请求解耦；双检锁 `_cron_started` + `_cron_start_lock`（`main.py:L74-76`）防重复 spawn；现在 `get_or_create_session` 里那行冗余调用可以删

---

## 记录模板

```
**[P0/P1/P2] 一句话标题**
- 问题：具体炸/错/体验差的表现
- 影响：对谁/什么造成了什么损失（最好量化）
- 根因：为什么会这样（文件:行号 + 逻辑链）
- 改进：修改了哪些代码、增加了哪些测试或防护措施
```

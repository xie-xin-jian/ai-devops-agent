# 项目完整地图

底稿：[source-map.md](source-map.md)。本图只画主干与旁支，行号均已回源码核对；未读到的分支标"未确认"。

## 0. 20 行速记版

```
run.py → uvicorn → api.main(BearerAuthMiddleware) → routers
  POST /api/chat/stream (main.py:245)
   ├ get_or_create_session (main.py:156) → SessionManager.get_or_create (manager.py:91)
   │    进程内 _sessions；未命中则 PG 还原 + load_all_custom_servers
   ├ with run_lock / cancel_event.clear (main.py:266-267)
   └ ComprehensiveAgent.run_stream (pipeline.py:88)
        └ _run_stream_impl (pipeline.py:209)
            ├ audit run.started(238) + create_run(253) 落库
            ├ 每轮: status(302) → compact(307) → thinking(309) → _call_api(320)
            │        _call_api 内: 配对修复(121) + 动态 MCP 池(123) + retry(137) + usage(138)
            ├ 无 tool_use → text_delta(460) → break
            └ 有 tool_use → yield tool_use(500) → _handle_tool_call(tool_loop.py:197)
                 策略(198) → 拒绝(202) / bash 重定向(217) / 审批(229) / execute(250)
            └ 收尾: audit run.completed(610) → finish(620) → yield done(631)
  工具底座: registry → policy → executor → sandbox/targets/mcp
  旁支: cron / background / subagent / memory / evaluation
```

## 1. 分层架构

```
[入口] run.py(L5 uvicorn.run) → api/main.py: app(L56) + BearerAuthMiddleware(L62)
        ├ BearerAuthMiddleware (auth.py:26) 白名单(L13-23)
        └ routers: chat(L244) / action / cron / mcp / memory / recovery / sandbox / skill / target / task
[会话门面] SessionManager (manager.py:55; _sessions:68)
        └ 每会话: agent / cancel_event / run_lock / target_id
[Agent 运行时] ComprehensiveAgent (comprehensive.py:55)
        ├ ContextManagerMixin: _build_system_prompt(L42) / _compact_if_needed(L115)
        ├ ToolLoopMixin: 配对修复(L19) / 策略与审批(L197-303)
        └ AgentPipelineMixin: run_stream(L88) / _run_stream_impl(L209) / resume_stream(L97)
[工具层] ToolRegistry(registry.py:29) → with_dynamic_tools(L137)
        ├ ToolPolicy/evaluate(policy.py:52/554)
        ├ ToolExecutor(executor.py:35) → sandbox(manager.py:37) / targets / bash
        └ MCP 池(registry.py:91; 可见性:71-89)
[持久化] RecoveryStore(state_store.py:182) → repositories/* → alembic/versions
[周边] cron.py:298/366/393 · background.py:135/246/285 · subagent.py:37 · memory/* · evaluation/*
```

## 2. 主干链路：`POST /api/chat/stream` → SSE `done`

1. `api/main.py:chat_stream(L245)`，鉴权 `require_permissions(AGENT_CHAT)`（L247）。
2. `main.py:get_or_create_session(L251)` → `sessions/manager.py:get_or_create(L91)`；默认 `RecoveryStore`/`ComprehensiveAgent`/TTL 2h（manager.py:61）；失败 503（main.py:253）。
3. `payload.reset` → `agent.reset()`（L255）；`target_id` 校验并 `activate_target`（L256-263）。
4. `event_generator`：`run_lock`（L266）、`cancel_event.clear()`（L267）→ 产出 **status(准备中)**（pipeline.py:266）。
5. `pipeline.py:run_stream(L88)` → `_run_stream_impl(L209)`。
6. 新 `run_id`（L237）→ audit `run.started`（L238）→ 追加 user（L249）→ `_persist_session_state`（L250）→ `create_run`（L253，状态 running/model）。
7. `collect_background_results()`（L276）→ 有通知则追加消息并产出 **status**（L284）。
8. 进入 `for turn in range(max_turns)`（L296）：**status(压缩)**（L302）→ `_compact_if_needed`（L307）→ **thinking**（L309）→ **status(调用模型)**（L310）。
9. `_call_api`（L320 → tool_loop.py:120-139）：配对修复（L121）、组装 MCP 池（L123）、刷新 system prompt（L126）、`with_retry`（L137）、`_record_usage`（L138 → `persist_run_usage` L165）。
10. 无 `tool_use`：`final_text`（L455）→ 逐词产出 **text_delta**（L460）→ break（L461）。
11. 有 `tool_use`：audit `tool.started`（L490）→ **tool_use**（L500）→ `_mark_run_unsafe`（L508）→ `_handle_tool_call`（L510）。
12. 需审批：`approval_coordinator.register`（L514）→ **pending_action**（L517）→ 写 waiting_approval（L521）→ `_await_tool_approval`（L527）→ `finally clear`（L532）。
13. 执行完成：输出截断 2000 字符（L571-572）→ **tool_result**（L574）→ 回填 `results`（L582-590）。
14. 完整轮末：若 `compact` 工具置位则 `compact_history`（L592-598）→ `_persist_run_safe`（L600）→ 下一轮。
15. 收尾：兜底取 `final_text`（L603-608）→ audit `run.completed`（L610）→ `_finish_run_state(COMPLETED)`（L620）→ **done**（含 usage，L631）。

> 事件全集见 pipeline.py:219-225：status / thinking / tool_use / tool_result / pending_action / text_delta / done / cancelled / error。除 `pending_action` 在 L517 单独产出外，均与上表一致。

## 3. 旁支总表

| 分支 | 触发条件 | 关键函数（文件:行） | 终态（run.status / SSE 终止） | 审计事件 type | 可验证方式 |
|---|---|---|---|---|---|
| 用户取消 | 前端取消或轮间检查 | `manager.py:cancel(L227)`；`pipeline.py` L262/L298/L447/L469；`_cancelled_event(L52-74)` | canceled / **cancelled** | `run.canceled`（L54） | 提交长任务后 POST `/api/chat/cancel`，再查 runs.status |
| 策略拒绝 | 工具不在白名单/权限不足 | `tool_loop.py:evaluate(L198)`，拒绝 L202-215 | 不终止，本工具返回 `Policy denied`；最终通常 completed | `policy.blocked`（L204） | 让模型调未授权工具，看 tool_result 文案 |
| bash 重定向建议 | bash 命中只读规则 | `shell.py:suggest_tool_for_command(L27)`；`tool_loop.py:L217-227` | 不终止，返回 `Redirected: use ...` | 未确认（未见审计） | 让模型执行 `ls`，观察重定向文案 |
| 审批-创建 | `requires_approval=True` | `tool_loop.py:_create_tool_approval(L141)` → `create_tool_call(L166)`；pipeline L511-521 | 挂起，**pending_action** | `pending_action.created`（L181） | 调 `target_deploy`，查 pending_actions 表 |
| 审批-确认 | POST `/pending/{id}/confirm` | `action_route.py:L106-140`；`coordinator.resolve(L121)` | 原 run 继续 | `pending_action.confirmed`（L127） | 确认后观察同一 SSE 续流 |
| 审批-取消 | POST `/pending/{id}/cancel` | `action_route.py:L224-247` | 原 run 继续，返回 rejected | `pending_action.canceled`（L250） | 取消后 tool_result 含 "not executed" |
| 审批-超时 | `wait` 30 分钟 | `approval_coordinator.py:wait(L57)`；L62/L85-88 | 原 run 继续 | 未确认（无独立事件） | 短超时改参后观察 reason=`approval timed out` |
| 审批-重启中断 | 进程重启时仍有 pending | `main.py:L109-123`；`pending_actions.py:recover_interrupted(L311)` | pending→failed | `pending_action.interrupted`（L112） | 起审批后 kill 进程，重启查审计 |
| 工具执行异常 | handler 抛异常 | `pipeline.py:L533-535` | 不终止，`Error: ...` 回落模型 | `tool.completed`（L556，失败时事件名未确认） | 触发参数错误，观察 tool_result |
| 消息配对修复 | 历史 tool_use 缺 result | `tool_loop.py:_repair_message_sequence(L19)`，调用 L121 | 不终止，静默修补 | 无 | 断开后重发请求，模型不再报 400 |
| 上下文溢出恢复 | `is_prompt_too_long_error` | `error_recovery.py:recover_context_overflow(L83)`；`pipeline.py:L322-410`；上限 2 次（L294） | 成功则续跑；失败 failed / **error** | `run.failed`（L324/L363/L390） | 构造超长上下文，观察 status "context recovery" |
| 达到 max_turns | 50 轮耗尽 | `pipeline.py:L296` → 兜底 L603 → L620 | completed / **done** | `run.completed`（L610） | 设 `max_turns=2` 跑复杂任务 |
| MCP 动态可见性 | 每次调用模型前 | `context_manager.py:_runtime_tool_registry(L34)`；`registry.py:assemble(L91)`、可见性 L71-89 | 无影响；不可见工具静默隐藏 | 无 | 不同 owner 会话看 `/tools` 差异 |
| 子代理 | 调 `spawn_subagent` | `integrations.py:L10-32`；`subagent.py:spawn(L37)`，30 轮 L60 | 主 run 不变，仅外层 tool_use/tool_result | 无 | 让模型拆任务，观察主上下文不膨胀 |
| 沙箱创建/清理 | 文件类工具或 run 结束 | `executor.py:L148` → `sandbox/manager.py:create(L51)`；清理 L133；finally L95；启动清孤儿 `main.py:L125` | 无影响 | `recovery.orphans_cleaned`（main L130） | `ls data/sandbox` 前后对比 |
| cron 触发 run | 到点调度 | `cron.py:_execute_cron_job_sync(L298)` → `agent.run(L323)`；worker L366；scheduler L393 | 独立 run，无 SSE | `cron.run.started/completed/failed`（L304/L331/L352） | 建每分钟任务，查 cron_logs |
| 后台任务 | 慢/长命令 | `background.py:should_run_background(L59)`，start L135，worker L161；结果 L285 → `pipeline.py:L276` | 主 run 继续；下轮注入 status | `background.run.started/completed/failed`（L163/L255） | 跑长命令后看下一轮 status |
| recovery resume | POST `/runs/{id}/resume/stream` | `recovery_route.py:L103`；校验 L116/L121；`mark_resumed(L134)`；`pipeline.py:resume_stream(L97)` | running(resuming)→同主干终态 | 复用主干事件 | 先造 failed+safe_to_resume，再调该接口 |
| 记忆读写 | 调 memory 工具 | `business/memory.py` L25/60/81/113/122/134/143 | 主 run 不变 | `memory.created`(L269)、`memory.candidate_created`(L261)、`memory.access_denied`(L184) 等 | 调用后查 audit_events |
| target 只读 | status/logs/http/list/read/glob | `policy.py:L170-217`（`requires_approval=False`） | 直接执行 | `policy.allowed`（tool_loop L233） | 直接调 `target_logs` 不过审批 |
| target 写/部署 | write/edit/restart/deploy | `policy.py:L219-251`（均需审批）；执行 L174/L201 | 走审批分支 | `pending_action.created` | 调 `target_write_file` 观察审批事件 |

## 4. run 状态机

状态常量：`running / completed / failed / canceled / interrupted`（`state_store.py:L24-28`），终态集合 `TERMINAL_RUN_STATUSES`（L30-33）。

```
(新建) ──create_run──> running/model            state_store.py:261-263
running ──done──────> completed/completed      pipeline.py:620
        ├─cancel───> canceled/canceled         pipeline.py:69-72
        ├─异常─────> failed/failed             pipeline.py:337/376/403/438
        └─进程重启──> interrupted              state_store.py:interrupt_stale_runs(L359) ← main:88
failed|canceled|interrupted + safe_to_resume=true
        └─POST resume──> running/resuming      recovery_route.py:116-134 → state_store.py:350
```
- `safe_to_resume`：每次模型调用前置 true（`persistence.py:52`），工具执行前置 false（L59），审批等待 false（`pipeline.py:521`），完成默认 false（L73）。
- `failed` 分支的 safe_to_resume 取值不一：API 异常与压缩失败为 true（`pipeline.py:443/380/407`），上下文耗尽分支**未确认**。
- 可续跑状态集合仅 `{interrupted, failed, canceled}`（`recovery_route.py:23-27`），且必须 `safe_to_resume=true`（L121）。

## 5. 写入点清单

| 表 | 写入函数 | 触发点 |
|---|---|---|
| sessions | `state_store.save_session(L188)` → `session_repo.upsert_session(L213)` | 首条 user、每次 run 状态保存（`persistence.py:37`） |
| messages | `sessions.py:_sync_messages(L110)`（按 seq 比对 hash 增量重写） | 同上，会话保存时 |
| runs | `runs.py:upsert_run` 内 `upsert_row(L130)`（`force=True`） | `create_run`（state_store L246）与每次 `save_run(L304)` |
| run_snapshots | 同函数内 L145-161，hash 未变则跳过（L139-144） | 每次 `save_run`；`_persist_run_safe` 每轮一次 |
| run_usage | `usage.py:persist_run_usage(L13)` | 每次模型调用：`pipeline.py:165`（L138 调用） |
| audit_events | `audit.py:record_event(L138)` ← `comprehensive.py:_audit(L134)` | run/tool/policy/memory/cron/background/审批各节点 |
| pending_actions | `pending_actions.py:create_tool_call(L114)` | `tool_loop.py:166`；`confirm/cancel/finish` 同表更新 |
| cron_logs | `cron.py:_save_cron_run_log(L248)` | `_execute_cron_job_sync` 成功/失败（L324/L344） |
| background_tasks | `background.py:_persist_task(L68)` | 创建与终态（L255 附近） |

## 6. 未确认清单

1. 工具执行失败是否有独立审计事件（L556 为 `tool.completed`）。
2. 客户端断开连接是否触发 `cancel_event`（未见 ASGI disconnect 监听）。
3. `action_route.py:_continue_session_after_approval(L45-69)` 离线重放细节未逐行。
4. 上下文耗尽分支 `run.failed` 的 `safe_to_resume` 实参。
5. `reasoning`/thinking 事件是否携带正文（pipeline 只发 turn，无文本）。

"""Primary Agent reasoning pipeline."""

import time
import uuid

from agent.core.context_compact import (
    compact_history,
    estimate_size,
    history_tool_content,
)
from agent.core.error_recovery import (
    escalate_tokens,
    is_output_limit_error,
    is_prompt_too_long_error,
    recover_context_overflow,
)
from agent.extensions.subagent import extract_text, has_tool_use
from agent.observability.audit import (
    RESULT_BLOCKED,
    RESULT_CANCELED,
    RESULT_FAILED,
    RESULT_SUCCESS,
    SEVERITY_HIGH,
    SEVERITY_INFO,
)
from agent.observability.logger import logger
from agent.orchestration.approval_coordinator import (
    ToolApprovalRequired,
    approval_coordinator,
)
from agent.orchestration.background import collect_background_results
from agent.persistence.repositories.usage import persist_run_usage
from agent.platform.config import (
    PRICE_CACHE_HIT_PER_M,
    PRICE_INPUT_PER_M,
    PRICE_OUTPUT_PER_M,
)
from agent.sessions.state_store import (
    RUN_STATUS_CANCELED,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    deserialize_messages,
)


class AgentPipelineMixin:
    @staticmethod
    def _is_cancelled(cancel_event) -> bool:
        return cancel_event is not None and cancel_event.is_set()

    def _cancelled_event(self) -> dict:
        text = "已停止生成。"
        self._audit(
            "run.canceled",
            "Agent run canceled",
            summary=text,
            result=RESULT_CANCELED,
            severity=SEVERITY_INFO,
            actor="user",
            correlation_id=getattr(self, "current_run_id", ""),
            payload={},
        )
        self.messages.append(
            {
                "role": "assistant",
                "content": [{"type": "text", "text": text}],
            }
        )
        self._finish_run_state(
            RUN_STATUS_CANCELED,
            "canceled",
            "cancelled by user",
        )
        return {"type": "cancelled", "text": text}

    def run(self, user_message: str, cancel_event=None) -> str:
        """同步执行 Agent 循环（非流式，保持原有行为不变）。"""
        final_text = None
        for event in self.run_stream(user_message, cancel_event):
            if event["type"] == "done":
                final_text = event["text"]
            elif event["type"] == "cancelled":
                final_text = event["text"]
            elif event["type"] == "error":
                raise RuntimeError(event["message"])
        return final_text or ""

    def run_stream(self, user_message: str, cancel_event=None):
        """Run the Agent and always clean up the per-run Sandbox workspace."""
        try:
            yield from self._run_stream_impl(user_message, cancel_event)
        finally:
            executor = getattr(self, "tool_executor", None)
            if executor is not None:
                executor.cleanup_sandbox(getattr(self, "current_run_id", ""))

    def resume_stream(
        self,
        run_id: str,
        messages: list,
        cancel_event=None,
    ):
        """Resume a run only from a previously persisted safe point."""
        self.current_run_id = str(run_id or "")
        self.messages = deserialize_messages(messages)
        store = getattr(self, "state_store", None)
        if store is not None and self.current_run_id:
            run_record = store.get_run(self.current_run_id) or {}
            self._last_user_query = str(run_record.get("user_message") or "")
            store.mark_resumed(self.current_run_id)
        self._audit(
            "run.resume.started",
            "Agent run resumed from safe point",
            result=RESULT_SUCCESS,
            severity=SEVERITY_INFO,
            actor="user",
            correlation_id=self.current_run_id,
            payload={"message_count": len(self.messages)},
        )
        try:
            yield from self._run_stream_impl(
                "",
                cancel_event,
                resume=True,
            )
        finally:
            executor = getattr(self, "tool_executor", None)
            if executor is not None:
                executor.cleanup_sandbox(getattr(self, "current_run_id", ""))

    def _record_usage(self, response) -> None:
        """累计每次模型调用的 token 用量，并按轮次写日志。"""
        usage = getattr(response, "usage", None)
        if usage is None:
            return

        def _count(name: str) -> int:
            return int(getattr(usage, name, 0) or 0)

        input_tokens = _count("input_tokens")
        output_tokens = _count("output_tokens")
        cache_read = _count("cache_read_input_tokens")
        cache_write = _count("cache_creation_input_tokens")

        totals = getattr(self, "_usage_total", None)
        if totals is None:
            totals = self._usage_total = {
                "calls": 0,
                "input": 0,
                "output": 0,
                "cache_read": 0,
                "cache_write": 0,
            }
        totals["calls"] += 1
        totals["input"] += input_tokens
        totals["output"] += output_tokens
        totals["cache_read"] += cache_read
        totals["cache_write"] += cache_write

        call_cost = self._estimate_usage_cost({
            "input": input_tokens,
            "output": output_tokens,
            "cache_read": cache_read,
        })
        persist_run_usage(
            run_id=getattr(self, "current_run_id", ""),
            session_id=getattr(self, "session_id", ""),
            turn=getattr(self, "_current_turn", 0),
            model_id=self.recovery.current_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            estimated_cost_cny=call_cost,
        )

        logger.info(
            f"[turn {getattr(self, '_current_turn', 0)}] tokens "
            f"in={input_tokens} out={output_tokens} "
            f"cache_read={cache_read} cache_write={cache_write}"
        )

    @staticmethod
    def _estimate_usage_cost(totals: dict) -> float:
        return (
            int(totals.get("input", 0) or 0)
            / 1_000_000
            * PRICE_INPUT_PER_M
            + int(totals.get("output", 0) or 0)
            / 1_000_000
            * PRICE_OUTPUT_PER_M
            + int(totals.get("cache_read", 0) or 0)
            / 1_000_000
            * PRICE_CACHE_HIT_PER_M
        )

    def _usage_summary(self) -> dict:
        """本次 run 的 token 汇总与成本估算（人民币）。"""
        totals = getattr(self, "_usage_total", None) or {
            "calls": 0,
            "input": 0,
            "output": 0,
            "cache_read": 0,
            "cache_write": 0,
        }
        cost = self._estimate_usage_cost(totals)
        return {**totals, "est_cost_cny": round(cost, 4)}

    def _run_stream_impl(
        self,
        user_message: str,
        cancel_event=None,
        *,
        resume: bool = False,
    ):
        """流式执行 Agent 循环，每步 yield 一个事件 dict。

        事件类型：
          {"type": "status", "message": str, "turn": int}
          {"type": "tool_use", "tool": str, "input": dict, "turn": int}
          {"type": "tool_result", "tool": str, "output": str, "turn": int, "duration_ms": int}
          {"type": "thinking", "turn": int}
          {"type": "done", "text": str, "total_turns": int}
          {"type": "cancelled", "text": str}
          {"type": "error", "message": str}
        """
        if resume:
            run_id = getattr(self, "current_run_id", "")
            if not run_id:
                yield {
                    "type": "error",
                    "message": "run_id is required for resume",
                }
                return
            self._persist_run_safe("model")
        else:
            self.current_run_id = f"run_{uuid.uuid4().hex}"
            self._audit(
                "run.started",
                "Agent run started",
                summary=user_message[:300],
                result=RESULT_SUCCESS,
                severity=SEVERITY_INFO,
                actor="agent",
                correlation_id=self.current_run_id,
                payload={"message": user_message},
            )
            self._last_user_query = user_message
            self.messages.append({"role": "user", "content": user_message})
            self._persist_session_state()
            store = getattr(self, "state_store", None)
            if store is not None:
                store.create_run(
                    self.current_run_id,
                    session_id=getattr(self, "session_id", ""),
                    owner_id=self._owner_id(),
                    user_message=user_message,
                    messages=self.messages,
                )
            logger.info(f"[user] {user_message[:200]}")

        if self._is_cancelled(cancel_event):
            yield self._cancelled_event()
            return

        yield {"type": "status", "message": "准备中...", "turn": 0}

        self._usage_total = {
            "calls": 0,
            "input": 0,
            "output": 0,
            "cache_read": 0,
            "cache_write": 0,
        }

        bg_notifications = collect_background_results()
        if bg_notifications:
            self.messages.append(
                {
                    "role": "user",
                    "content": "\n\n".join(bg_notifications),
                }
            )
            yield {
                "type": "status",
                "message": f"收到 {len(bg_notifications)} 条后台任务通知",
                "turn": 0,
            }
            logger.info(f"[bg] 收到 {len(bg_notifications)} 条后台任务通知")

        max_turns = max(1, int(getattr(self, "max_turns", 50) or 50))
        final_text = ""
        context_recovery_attempts = 0
        max_context_recovery_attempts = 2

        for turn in range(max_turns):
            self._current_turn = turn + 1
            if self._is_cancelled(cancel_event):
                yield self._cancelled_event()
                return

            yield {
                "type": "status",
                "message": f"第 {turn+1} 轮：压缩上下文",
                "turn": turn + 1,
            }
            self.messages = self._compact_if_needed(self.messages)

            yield {"type": "thinking", "turn": turn + 1}
            yield {
                "type": "status",
                "message": f"第 {turn+1} 轮：调用大模型 ({self.model})",
                "turn": turn + 1,
            }
            logger.info(
                f"[turn {turn+1}] 调用 {self.recovery.current_model} (ctx {estimate_size(self.messages)} bytes)"
            )

            try:
                response = self._call_api(self.messages)
            except Exception as e:
                if is_prompt_too_long_error(e):
                    if context_recovery_attempts >= max_context_recovery_attempts:
                        self._audit(
                            "run.failed",
                            "Context recovery exhausted",
                            summary="Context remained over the model limit",
                            result=RESULT_FAILED,
                            severity=SEVERITY_HIGH,
                            actor="agent",
                            correlation_id=self.current_run_id,
                        )
                        yield {
                            "type": "error",
                            "message": "上下文压缩后仍然超过模型限制",
                        }
                        self._finish_run_state(
                            RUN_STATUS_FAILED,
                            "failed",
                            "context recovery exhausted",
                            safe_to_resume=True,
                        )
                        return

                    context_recovery_attempts += 1
                    yield {
                        "type": "status",
                        "message": "Prompt 过长，执行上下文恢复压缩...",
                        "turn": turn + 1,
                    }
                    logger.warning(
                        f"[turn {turn+1}] Prompt 过长，执行 " "recover_context_overflow"
                    )

                    try:
                        compacted, stats = recover_context_overflow(
                            self.messages,
                            self.client,
                            self.recovery.current_model,
                        )
                    except Exception as compact_error:
                        logger.error(f"[turn {turn+1}] 上下文压缩失败: {compact_error}")
                        self._audit(
                            "run.failed",
                            "Context compaction failed",
                            summary=str(compact_error),
                            result=RESULT_FAILED,
                            severity=SEVERITY_HIGH,
                            actor="agent",
                            correlation_id=self.current_run_id,
                        )
                        yield {
                            "type": "error",
                            "message": f"上下文压缩失败: {compact_error}",
                        }
                        self._finish_run_state(
                            RUN_STATUS_FAILED,
                            "failed",
                            f"context compaction failed: {compact_error}",
                            safe_to_resume=True,
                        )
                        return

                    self.messages = compacted
                    logger.info(
                        f"[turn {turn+1}] context recovery: "
                        f"{stats['before']} -> {stats['after']} bytes"
                    )
                    if not stats["reduced"]:
                        self._audit(
                            "run.failed",
                            "Context compaction did not reduce input",
                            summary="No effective context reduction",
                            result=RESULT_FAILED,
                            severity=SEVERITY_HIGH,
                            actor="agent",
                            correlation_id=self.current_run_id,
                        )
                        yield {
                            "type": "error",
                            "message": "上下文压缩未有效缩小输入，无法继续调用模型",
                        }
                        self._finish_run_state(
                            RUN_STATUS_FAILED,
                            "failed",
                            "context compaction was ineffective",
                            safe_to_resume=True,
                        )
                        return
                    continue

                if is_output_limit_error(e):
                    if escalate_tokens(self.recovery):
                        yield {
                            "type": "status",
                            "message": (
                                "输出 Token 上限扩容到 "
                                f"{self.recovery.current_max_tokens}"
                            ),
                            "turn": turn + 1,
                        }
                        logger.warning(
                            f"[turn {turn+1}] 输出 Token 上限扩容到 "
                            f"{self.recovery.current_max_tokens}"
                        )
                        continue

                self._audit(
                    "run.failed",
                    "Agent API call failed",
                    summary=str(e),
                    result=RESULT_FAILED,
                    severity=SEVERITY_HIGH,
                    actor="agent",
                    correlation_id=self.current_run_id,
                )
                yield {"type": "error", "message": str(e)}
                self._finish_run_state(
                    RUN_STATUS_FAILED,
                    "failed",
                    str(e),
                    safe_to_resume=True,
                )
                logger.error(f"[turn {turn+1}] API 异常: {e}")
                return

            if self._is_cancelled(cancel_event):
                yield self._cancelled_event()
                return

            self.messages.append({"role": "assistant", "content": response.content})

            if not has_tool_use(response.content):
                # LLM 认为不需要调工具了，输出最终文字
                final_text = extract_text(response.content)
                logger.info(f"[turn {turn+1}] 完成: {len(final_text or '')} 字符")
                if final_text:
                    # 逐字流式输出最终文字（前端能看到逐字出现）
                    for word in final_text.split(" "):
                        yield {"type": "text_delta", "delta": word + " "}
                break

            # 执行所有工具调用
            results = []
            for block_index, block in enumerate(response.content):
                if block.type != "tool_use":
                    continue

                if self._is_cancelled(cancel_event):
                    for remaining in response.content[block_index:]:
                        if remaining.type == "tool_use":
                            results.append(
                                {
                                    "type": "tool_result",
                                    "tool_use_id": remaining.id,
                                    "content": "Error: cancelled by user",
                                }
                            )
                    if results:
                        self.messages.append({"role": "user", "content": results})
                    yield self._cancelled_event()
                    return

                logger.info(f"[turn {turn+1}] tool_use: {block.name}")
                tool_input = (
                    block.input
                    if isinstance(block.input, dict)
                    else {"input": str(block.input)}
                )
                self._audit(
                    "tool.started",
                    f"Tool started: {block.name}",
                    result=RESULT_SUCCESS,
                    severity=SEVERITY_INFO,
                    actor="agent",
                    tool_name=block.name,
                    correlation_id=self.current_run_id,
                    payload={"input": tool_input},
                )
                yield {
                    "type": "tool_use",
                    "tool": block.name,
                    "input": tool_input,
                    "turn": turn + 1,
                }

                t0 = time.time()
                self._mark_run_unsafe(block.name)
                try:
                    output = self._handle_tool_call(block)
                except ToolApprovalRequired as approval:
                    # Register before exposing the event so an automated
                    # consumer can decide while this generator is suspended.
                    approval_coordinator.register(approval.record.id)
                    try:
                        yield {
                            "type": "pending_action",
                            "pending_action": approval.record.to_dict(),
                            "turn": turn + 1,
                        }
                        self._persist_run_state(
                            status="running",
                            phase="waiting_approval",
                            safe_to_resume=False,
                            active_tool=block.name,
                        )
                        output = self._await_tool_approval(
                            approval.record,
                            cancel_event,
                        )
                    finally:
                        approval_coordinator.clear(approval.record.id)
                except Exception as tool_err:
                    output = f"Error: {tool_err}"
                    logger.error(f"[turn {turn+1}] tool {block.name} 异常: {tool_err}")
                duration_ms = int((time.time() - t0) * 1000)
                logger.info(
                    f"[turn {turn+1}] tool_done: {block.name} ({duration_ms}ms)"
                )

                output_str = str(output)
                blocked_prefixes = (
                    "Policy denied:",
                    "Approval rejected or cancelled:",
                )
                if output_str.startswith(blocked_prefixes):
                    tool_result = RESULT_BLOCKED
                    tool_severity = SEVERITY_HIGH
                elif output_str.startswith("Error:"):
                    tool_result = RESULT_FAILED
                    tool_severity = SEVERITY_HIGH
                else:
                    tool_result = RESULT_SUCCESS
                    tool_severity = SEVERITY_INFO
                self._audit(
                    "tool.completed",
                    f"Tool completed: {block.name}",
                    summary=output_str[:500],
                    result=tool_result,
                    severity=tool_severity,
                    actor="agent",
                    tool_name=block.name,
                    correlation_id=self.current_run_id,
                    payload={"input": tool_input},
                    metadata={
                        "duration_ms": duration_ms,
                        "output_preview": output_str[:1000],
                    },
                )
                # 截断太长的输出
                if len(output_str) > 2000:
                    output_str = output_str[:2000] + "\n... (truncated)"

                yield {
                    "type": "tool_result",
                    "tool": block.name,
                    "output": output_str,
                    "turn": turn + 1,
                    "duration_ms": duration_ms,
                }

                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": history_tool_content(block.id, output),
                    }
                )

            self.messages.append({"role": "user", "content": results})

            if self._pending_compaction:
                self.messages = compact_history(
                    self.messages,
                    self.client,
                    self.recovery.current_model,
                )
                self._pending_compaction = False

            self._persist_run_safe("model")

        # 如果循环结束但没拿到 final_text，从后往前找
        if not final_text:
            for msg in reversed(self.messages):
                if msg["role"] == "assistant":
                    final_text = extract_text(msg["content"])
                    if final_text:
                        break

        self._audit(
            "run.completed",
            "Agent run completed",
            summary=(final_text or "")[:300],
            result=RESULT_SUCCESS,
            severity=SEVERITY_INFO,
            actor="agent",
            correlation_id=self.current_run_id,
            payload={"total_turns": turn + 1},
        )
        self._finish_run_state(
            RUN_STATUS_COMPLETED,
            "completed",
        )
        usage = self._usage_summary()
        logger.info(
            f"[usage] run {self.current_run_id} turns={turn + 1} "
            f"calls={usage['calls']} in={usage['input']} out={usage['output']} "
            f"cache_read={usage['cache_read']} "
            f"est_cost=¥{usage['est_cost_cny']}"
        )
        yield {
            "type": "done",
            "text": final_text,
            "total_turns": turn + 1,
            "usage": usage,
        }
        logger.info(f"[done] 共 {turn + 1} 轮, 输出 {len(final_text)} 字符")

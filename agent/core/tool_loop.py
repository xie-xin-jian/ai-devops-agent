"""Tool policy, approvals, and API calls for the Agent runtime."""

from agent.core.error_recovery import with_retry
from agent.orchestration.approval_coordinator import (
    ToolApprovalRequired,
    approval_coordinator,
)
from agent.observability.audit import (
    RESULT_BLOCKED,
    RESULT_SUCCESS,
    SEVERITY_HIGH,
    SEVERITY_INFO,
)
from agent.tools.policy import evaluate_tool_policy


class ToolLoopMixin:
    def _repair_message_sequence(self, messages: list) -> list:
        """Ensure each tool_use has its tool_result in the immediately next user message."""
        if not messages:
            return messages

        def _value(block, name, default=None):
            if isinstance(block, dict):
                return block.get(name, default)
            return getattr(block, name, default)

        def _is_type(block, block_type: str) -> bool:
            return str(_value(block, "type", "") or "") == block_type

        def _merge_content(existing, repair_blocks: list[dict]) -> list:
            if isinstance(existing, list):
                return repair_blocks + list(existing)
            if isinstance(existing, str) and existing:
                return repair_blocks + [{"type": "text", "text": existing}]
            return repair_blocks

        def _repair_blocks(missing_ids: list[str]) -> list[dict]:
            return [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": (
                        "Error: the previous tool call was interrupted "
                        "before a result was produced."
                    ),
                }
                for tool_use_id in missing_ids
            ]

        repaired: list = []
        changed = False
        index = 0
        while index < len(messages):
            msg = messages[index]
            repaired.append(msg)
            if msg.get("role") != "assistant":
                index += 1
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                index += 1
                continue
            tool_use_ids = [
                str(_value(block, "id", "") or "")
                for block in content
                if _is_type(block, "tool_use") and _value(block, "id")
            ]
            if not tool_use_ids:
                index += 1
                continue

            next_message = (
                messages[index + 1]
                if index + 1 < len(messages)
                else None
            )
            existing_result_ids: set[str] = set()
            if (
                next_message is not None
                and next_message.get("role") == "user"
                and isinstance(next_message.get("content"), list)
            ):
                existing_result_ids = {
                    str(_value(block, "tool_use_id", "") or "")
                    for block in next_message["content"]
                    if _is_type(block, "tool_result")
                    and _value(block, "tool_use_id")
                }
            missing_ids = [
                tool_use_id
                for tool_use_id in tool_use_ids
                if tool_use_id not in existing_result_ids
            ]
            if not missing_ids:
                index += 1
                continue

            repair_blocks = _repair_blocks(missing_ids)
            changed = True
            if next_message is not None and next_message.get("role") == "user":
                merged = dict(next_message)
                merged["content"] = _merge_content(
                    next_message.get("content"),
                    repair_blocks,
                )
                repaired.append(merged)
                index += 2
            else:
                repaired.append({"role": "user", "content": repair_blocks})
                index += 1

        return repaired if changed else messages

    def _call_api(self, messages: list):
        # 修复可能因中断导致的 tool_use/tool_result 不配对
        repaired = self._repair_message_sequence(messages)
        if repaired is not messages:
            self.messages = repaired
            messages = repaired
        # 动态合并 MCP 工具：每次调用 API 前把已连接的 MCP 服务器工具合并进来
        registry = self._runtime_tool_registry()
        tools = registry.filtered_schemas(self.tool_context)
        # 刷新系统提示（MCP 连接可能变化）
        system_prompt = self._build_system_prompt()

        def _call():
            return self.client.messages.create(
                model=self.recovery.current_model,
                system=system_prompt,
                messages=messages,
                tools=tools,
                max_tokens=self.recovery.current_max_tokens,
            )

        return with_retry(_call, self.recovery)

    def _create_tool_approval(self, block, decision):
        tool_input = (
            block.input
            if isinstance(block.input, dict)
            else {"input": str(block.input)}
        )
        approval_summary = ""
        if block.name == "bash":
            title = f"执行命令: {str(tool_input.get('command', block.name))[:80]}"
        elif block.name in {"target_write_file", "target_edit_file"}:
            title = f"修改文件: {str(tool_input.get('path', block.name))[:80]}"
        elif block.name == "target_restart":
            title = "重启运维项目"
            target = getattr(self, "target", None)
            if target is not None:
                from agent.targets.tools import _restart_command_preview

                approval_summary = _restart_command_preview(target)
        elif block.name == "target_deploy":
            title = "部署运维项目"
            target = getattr(self, "target", None)
            if target is not None:
                approval_summary = target.deploy_command
        else:
            title = f"执行工具: {block.name}"
        record = self.pending_action_store.create_tool_call(
            block.name,
            tool_input,
            session_id=getattr(self, "session_id", ""),
            target_id=getattr(self, "target_id", ""),
            run_id=getattr(self, "current_run_id", ""),
            tool_use_id=str(getattr(block, "id", "") or ""),
            owner_id=getattr(
                getattr(self, "principal", None),
                "id",
                "",
            ),
            source_message=getattr(self, "_last_user_query", ""),
            summary=approval_summary or title,
        )
        self._audit(
            "pending_action.created",
            f"Pending action created: {block.name}",
            result=RESULT_SUCCESS,
            severity=SEVERITY_INFO,
            action_id=record.id,
            tool_name=block.name,
            risk_level=decision.policy.risk_level,
            correlation_id=record.id,
            payload={
                "summary": record.summary,
                "steps": record.steps,
            },
        )
        return record

    def _handle_tool_call(self, block):
        decision = evaluate_tool_policy(
            block.name,
            getattr(self, "tool_context", None),
        )
        if not decision.allowed:
            self._audit(
                "policy.blocked",
                f"Tool policy blocked: {block.name}",
                summary=decision.reason,
                result=RESULT_BLOCKED,
                severity=SEVERITY_HIGH,
                tool_name=block.name,
                risk_level=decision.policy.risk_level,
                correlation_id=getattr(self, "current_run_id", ""),
                payload={"input": block.input},
                metadata={"reason": decision.reason},
            )
            return f"Policy denied: {decision.reason}"

        if decision.requires_approval:
            record = self._create_tool_approval(block, decision)
            raise ToolApprovalRequired(record)

        self._audit(
            "policy.allowed",
            f"Tool policy allowed: {block.name}",
            result=RESULT_SUCCESS,
            severity=SEVERITY_INFO,
            tool_name=block.name,
            risk_level=decision.policy.risk_level,
            correlation_id=getattr(self, "current_run_id", ""),
            payload={"input": block.input},
            metadata={"requires_approval": decision.requires_approval},
        )

        tool_input = (
            block.input
            if isinstance(block.input, dict)
            else {"input": str(block.input)}
        )
        result = self.tool_executor.execute(
            block.name,
            tool_input,
            run_id=getattr(self, "current_run_id", ""),
            registry=self._runtime_tool_registry(),
            source="chat",
        )
        output = result.output
        return output

    def _await_tool_approval(self, record, cancel_event=None) -> str:
        """Wait for approval and continue the same Agent run."""
        from agent.orchestration.pending_actions import (
            STATUS_EXECUTED,
            STATUS_FAILED,
        )
        from agent.orchestration.pending_executor import execute_pending_action

        approval_coordinator.register(record.id)
        try:
            decision = approval_coordinator.wait(
                record.id,
                cancel_event=cancel_event,
            )
            if not decision.approved:
                current = self.pending_action_store.get(record.id)
                if current is not None and current.status == "pending":
                    self.pending_action_store.cancel(
                        record.id,
                        actor=decision.actor or "user",
                        reason=decision.reason or "rejected",
                    )
                return (
                    "Approval rejected or cancelled: "
                    f"{decision.reason or 'not approved'}. "
                    "The command was not executed."
                )

            result = execute_pending_action(record, self.principal)
            status = (
                STATUS_EXECUTED
                if result.get("success")
                else STATUS_FAILED
            )
            self.pending_action_store.finish(
                record.id,
                status=status,
                result_payload=result,
            )
            self._audit(
                (
                    "pending_action.executed"
                    if result.get("success")
                    else "pending_action.execution_failed"
                ),
                f"Pending action finished: {record.id}",
                summary=str(result.get("summary") or ""),
                result="success" if result.get("success") else "failed",
                severity="info" if result.get("success") else "high",
                actor=decision.actor or "user",
                session_id=getattr(self, "session_id", ""),
                action_id=record.id,
                action_code=record.action_code,
                risk_level=record.risk_level,
                correlation_id=record.id,
                payload={
                    "execution_enabled": True,
                    "success": result.get("success"),
                },
            )
            return str(result.get("summary") or "(no output)")
        finally:
            approval_coordinator.clear(record.id)

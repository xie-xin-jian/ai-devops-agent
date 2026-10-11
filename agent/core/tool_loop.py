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
        """修复消息序列：确保每个 tool_use 后面紧接的 user 消息里有对应 tool_result。

        Anthropic 要求 assistant 的 tool_use 必须在**紧接的下一条** user 消息里
        有对应的 tool_result，否则 API 报 400。
        当 Agent run 在工具执行（尤其是审批等待）期间被中断时，
        会残留 tool_use 而缺少 tool_result，此方法自动补齐。
        """
        if not messages:
            return messages

        # 收集所有已出现的 tool_result id
        all_result_ids: set[str] = set()
        for msg in messages:
            if msg.get("role") != "user":
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tid = block.get("tool_use_id")
                    if tid:
                        all_result_ids.add(tid)

        repaired: list = []
        for i, msg in enumerate(messages):
            repaired.append(msg)
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            tool_use_ids = [
                block.get("id")
                for block in content
                if isinstance(block, dict)
                and block.get("type") == "tool_use"
                and block.get("id")
            ]
            if not tool_use_ids:
                continue
            # 找出该 assistant 消息中缺失对应 tool_result 的 tool_use
            missing_ids = [
                tid for tid in tool_use_ids if tid not in all_result_ids
            ]
            if not missing_ids:
                continue
            # 在 assistant 消息后面紧接插入一个 user 消息补 tool_result
            repair_blocks = [
                {
                    "type": "tool_result",
                    "tool_use_id": tid,
                    "content": (
                        "Error: the previous tool call was interrupted "
                        "before a result was produced."
                    ),
                }
                for tid in missing_ids
            ]
            repaired.append({"role": "user", "content": repair_blocks})

        return repaired

    def _call_api(self, messages: list):
        # 修复可能因中断导致的 tool_use/tool_result 不配对
        messages = self._repair_message_sequence(messages)
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

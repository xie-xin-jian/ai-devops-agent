"""Tool policy, approvals, and API calls for the Agent runtime."""

from agent.core.error_recovery import with_retry
from agent.core.hooks import trigger_hooks
from agent.observability.audit import (
    RESULT_BLOCKED,
    RESULT_SUCCESS,
    SEVERITY_HIGH,
    SEVERITY_INFO,
)
from agent.tools.policy import evaluate_tool_policy


class ToolLoopMixin:
    def _call_api(self, messages: list):
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
        title = f"执行命令: {str(tool_input.get('command', block.name))[:80]}"
        record = self.pending_action_store.create_tool_call(
            block.name,
            tool_input,
            session_id=getattr(self, "session_id", ""),
            owner_id=getattr(
                getattr(self, "principal", None),
                "id",
                "",
            ),
            source_message=getattr(self, "_last_user_query", ""),
            summary=title,
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
        self._pending_action_notifications.append(record.to_dict())
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
            return (
                f"Approval required: pending action {record.id}. "
                "The command will run only after approval."
            )

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

        blocked = trigger_hooks("PreToolUse", block)
        if blocked:
            self._audit(
                "policy.blocked",
                f"PreToolUse hook blocked: {block.name}",
                summary=str(blocked),
                result=RESULT_BLOCKED,
                severity=SEVERITY_HIGH,
                tool_name=block.name,
                correlation_id=getattr(self, "current_run_id", ""),
                payload={"input": block.input},
            )
            return str(blocked)

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
        trigger_hooks("PostToolUse", block, output)
        return output

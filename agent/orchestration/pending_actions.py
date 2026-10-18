"""Persistent pending-action storage."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field

from agent.persistence.repositories import actions as action_repo
from agent.tools.policy import get_tool_policy


STATUS_PENDING = "pending"
STATUS_CONFIRMED = "confirmed"
STATUS_CANCELED = "canceled"
STATUS_EXECUTED = "executed"
STATUS_FAILED = "failed"
STATUS_EXPIRED = "expired"
VALID_STATUSES = {
    STATUS_PENDING,
    STATUS_CONFIRMED,
    STATUS_CANCELED,
    STATUS_EXECUTED,
    STATUS_FAILED,
    STATUS_EXPIRED,
}


def _normalize_steps(steps) -> list[dict]:
    normalized = []
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        item = dict(step)
        item["tool"] = str(item.get("tool") or "").strip()
        item["description"] = str(
            item.get("description") or item.get("title") or ""
        ).strip()
        item["status"] = str(item.get("status") or "pending").strip()
        normalized.append(item)
    return normalized


@dataclass
class PendingAction:
    id: str
    session_id: str
    target_id: str
    run_id: str
    tool_use_id: str
    owner_id: str
    action_code: str
    title: str
    risk_level: str
    agent_mode: str
    status: str = STATUS_PENDING
    source_message: str = ""
    summary: str = ""
    payload: dict = field(default_factory=dict)
    steps: list[dict] = field(default_factory=list)
    impact: str = ""
    rollback_plan: str = ""
    verification: str = ""
    result_payload: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    confirmed_by: str = ""
    confirmed_at: float | None = None
    canceled_by: str = ""
    canceled_at: float | None = None
    cancel_reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PendingAction":
        status = str(data.get("status") or STATUS_PENDING).strip()
        if status not in VALID_STATUSES:
            status = STATUS_PENDING
        return cls(
            id=str(data.get("id") or f"act_{uuid.uuid4().hex}"),
            session_id=str(data.get("session_id") or ""),
            target_id=str(data.get("target_id") or ""),
            run_id=str(data.get("run_id") or ""),
            tool_use_id=str(data.get("tool_use_id") or ""),
            owner_id=str(data.get("owner_id") or ""),
            action_code=str(data.get("action_code") or ""),
            title=str(data.get("title") or ""),
            risk_level=str(data.get("risk_level") or ""),
            agent_mode=str(data.get("agent_mode") or ""),
            status=status,
            source_message=str(data.get("source_message") or ""),
            summary=str(data.get("summary") or ""),
            payload=dict(data.get("payload") or {}),
            steps=_normalize_steps(data.get("steps")),
            impact=str(data.get("impact") or ""),
            rollback_plan=str(data.get("rollback_plan") or ""),
            verification=str(data.get("verification") or ""),
            result_payload=dict(data.get("result_payload") or {}),
            created_at=float(data.get("created_at") or time.time()),
            updated_at=float(data.get("updated_at") or time.time()),
            confirmed_by=str(data.get("confirmed_by") or ""),
            confirmed_at=data.get("confirmed_at"),
            canceled_by=str(data.get("canceled_by") or ""),
            canceled_at=data.get("canceled_at"),
            cancel_reason=str(data.get("cancel_reason") or ""),
        )


class PendingActionStore:
    """Database-backed pending-action store."""

    def create_tool_call(
        self,
        tool_name: str,
        tool_input: dict,
        *,
        session_id: str,
        target_id: str = "",
        run_id: str = "",
        tool_use_id: str = "",
        owner_id: str = "",
        source_message: str = "",
        summary: str = "",
    ) -> PendingAction:
        policy = get_tool_policy(tool_name)
        now = time.time()
        action_id = (
            f"act_{int(now * 1000)}_"
            f"{uuid.uuid4().hex[:8]}"
        )
        title = summary or f"执行工具 {tool_name}"
        record = PendingAction(
            id=action_id,
            session_id=str(session_id or ""),
            target_id=str(target_id or ""),
            run_id=str(run_id or ""),
            tool_use_id=str(tool_use_id or ""),
            owner_id=str(owner_id or ""),
            action_code=f"tool.{tool_name}",
            title=title,
            risk_level=policy.risk_level,
            agent_mode="react",
            status=STATUS_PENDING,
            source_message=str(source_message or "")[:4000],
            summary=title,
            payload={"tool": tool_name, "input": dict(tool_input or {})},
            steps=[{
                "tool": tool_name,
                "description": title,
                "input": dict(tool_input or {}),
                "status": "pending",
            }],
            impact="该操作需要人工确认后才会执行。",
            rollback_plan="",
            verification="执行结果会显示在审批中心。",
            result_payload={
                "execution_enabled": True,
                "message": "Approval required.",
            },
            created_at=now,
            updated_at=now,
        )
        if not action_repo.upsert_action(record.to_dict(), force=True):
            raise RuntimeError("Failed to create pending action")
        return record

    def get(self, action_id: str) -> PendingAction | None:
        record = action_repo.fetch_action(action_id)
        return PendingAction.from_dict(record) if record else None

    def list(
        self,
        *,
        session_id: str | None = None,
        status: str | None = None,
        limit: int = 0,
    ) -> list[PendingAction]:
        """List actions newest-first."""
        records = action_repo.fetch_actions(
            session_id=session_id,
            status=status,
            limit=limit,
        )
        return [
            PendingAction.from_dict(item)
            for item in records
        ]

    def confirm(
        self,
        action_id: str,
        *,
        actor: str = "api-user",
    ) -> PendingAction:
        current = self.get(action_id)
        if current is None:
            raise KeyError(action_id)
        record = self._apply_confirm(current, action_id, actor)
        updated = action_repo.confirm_action(action_id, record.to_dict())
        if updated is None:
            raise ValueError(
                f"Pending action {action_id} is {current.status}"
            )
        return PendingAction.from_dict(updated)

    @staticmethod
    def _apply_confirm(
        record: PendingAction,
        action_id: str,
        actor: str,
    ) -> PendingAction:
        if record.status != STATUS_PENDING:
            raise ValueError(
                f"Pending action {action_id} is {record.status}"
            )
        now = time.time()
        record.status = STATUS_CONFIRMED
        record.confirmed_by = str(actor or "api-user")
        record.confirmed_at = now
        record.updated_at = now
        record.result_payload = {
            **record.result_payload,
            "execution_enabled": False,
            "message": (
                "Action confirmed. Execution will be enabled in the "
                "sandbox execution stage."
            ),
        }
        return record

    def cancel(
        self,
        action_id: str,
        *,
        actor: str = "api-user",
        reason: str = "",
    ) -> PendingAction:
        current = self.get(action_id)
        if current is None:
            raise KeyError(action_id)
        record = self._apply_cancel(current, action_id, actor, reason)
        updated = action_repo.cancel_action(action_id, record.to_dict())
        if updated is None:
            raise ValueError(
                f"Pending action {action_id} is {current.status}"
            )
        return PendingAction.from_dict(updated)

    @staticmethod
    def _apply_cancel(
        record: PendingAction,
        action_id: str,
        actor: str,
        reason: str,
    ) -> PendingAction:
        if record.status not in {STATUS_PENDING, STATUS_CONFIRMED}:
            raise ValueError(
                f"Pending action {action_id} is {record.status}"
            )
        now = time.time()
        record.status = STATUS_CANCELED
        record.canceled_by = str(actor or "api-user")
        record.canceled_at = now
        record.cancel_reason = str(reason or "").strip()
        record.updated_at = now
        return record

    def finish(
        self,
        action_id: str,
        *,
        status: str,
        result_payload: dict,
    ) -> PendingAction:
        if status not in {STATUS_EXECUTED, STATUS_FAILED}:
            raise ValueError(f"Invalid terminal status: {status}")
        current = self.get(action_id)
        if current is None:
            raise KeyError(action_id)
        record = self._apply_finish(
            current,
            action_id,
            status,
            result_payload,
        )
        updated = action_repo.finish_action(action_id, record.to_dict())
        if updated is None:
            raise ValueError(
                f"Pending action {action_id} is {current.status}"
            )
        return PendingAction.from_dict(updated)

    @staticmethod
    def _apply_finish(
        record: PendingAction,
        action_id: str,
        status: str,
        result_payload: dict,
    ) -> PendingAction:
        if record.status != STATUS_CONFIRMED:
            raise ValueError(
                f"Pending action {action_id} is {record.status}"
            )
        record.status = status
        record.result_payload = dict(result_payload or {})
        record.updated_at = time.time()
        return record

    def recover_interrupted(self, reason: str) -> list[PendingAction]:
        """Fail confirmed actions that never reached a terminal state."""
        candidates = self.list(status=STATUS_CONFIRMED)
        if not candidates:
            return []
        action_repo.recover_interrupted_actions(str(reason))
        recovered = []
        for candidate in candidates:
            record = self.get(candidate.id)
            if record is not None:
                recovered.append(record)
        return recovered


__all__ = [
    "PendingAction",
    "PendingActionStore",
    "STATUS_CANCELED",
    "STATUS_CONFIRMED",
    "STATUS_EXECUTED",
    "STATUS_EXPIRED",
    "STATUS_FAILED",
    "STATUS_PENDING",
]

"""Preflight validation and persistent pending-action storage."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from agent.action_router import ActionDefinition, get_action
from agent.config import DATA_DIR
from agent.storage import atomic_write_text, get_path_lock


PENDING_ACTIONS_PATH = DATA_DIR / ".pending_actions" / "actions.json"

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


def _is_present(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return bool(value)
    return True


@dataclass(frozen=True)
class PreflightResult:
    action_code: str
    ready: bool
    required_fields: list[str]
    missing_fields: list[str]
    values: dict

    def to_dict(self) -> dict:
        return asdict(self)


def build_preflight(
    action: ActionDefinition,
    data: dict | None = None,
) -> PreflightResult:
    """Validate that an action has the context needed for approval."""
    values = dict(data or {})
    required_fields = [
        item.name
        for item in action.preflight_fields
        if item.required
    ]
    missing_fields = [
        name
        for name in required_fields
        if not _is_present(values.get(name))
    ]
    return PreflightResult(
        action_code=action.code,
        ready=not missing_fields,
        required_fields=required_fields,
        missing_fields=missing_fields,
        values={
            item.name: values.get(item.name)
            for item in action.preflight_fields
        },
    )


def get_action_preflight_contract(
    action_code: str,
    data: dict | None = None,
) -> PreflightResult:
    action = get_action(action_code)
    if action is None:
        raise ValueError(f"Unknown action: {action_code}")
    return build_preflight(action, data)


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
    preflight: dict = field(default_factory=dict)
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
            preflight=dict(data.get("preflight") or {}),
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
    """JSON-backed pending-action store with atomic writes."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or PENDING_ACTIONS_PATH)
        self._lock = get_path_lock(self.path)

    def _load_unlocked(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {
            str(action_id): value
            for action_id, value in data.items()
            if isinstance(value, dict)
        }

    def _save_unlocked(self, records: dict[str, dict]) -> None:
        atomic_write_text(
            self.path,
            json.dumps(records, ensure_ascii=False, indent=2),
        )

    def create(
        self,
        action: ActionDefinition,
        *,
        session_id: str,
        owner_id: str = "",
        source_message: str,
        summary: str,
        payload: dict,
        steps: list[dict],
        impact: str = "",
        rollback_plan: str = "",
        verification: str = "",
    ) -> PendingAction:
        now = time.time()
        action_id = (
            f"act_{int(now * 1000)}_"
            f"{uuid.uuid4().hex[:8]}"
        )
        record = PendingAction(
            id=action_id,
            session_id=str(session_id or ""),
            owner_id=str(owner_id or ""),
            action_code=action.code,
            title=f"{action.display_name}: {summary[:80]}",
            risk_level=action.risk_level,
            agent_mode=action.agent_mode,
            status=STATUS_PENDING,
            source_message=str(source_message or "")[:4000],
            summary=str(summary or "").strip(),
            payload=dict(payload or {}),
            steps=_normalize_steps(steps),
            impact=str(impact or "").strip(),
            rollback_plan=str(rollback_plan or "").strip(),
            verification=str(verification or "").strip(),
            preflight={
                "required_fields": [
                    item.name
                    for item in action.preflight_fields
                    if item.required
                ],
                "ready": True,
            },
            result_payload={
                "execution_enabled": False,
                "message": "Pending approval. Execution is not enabled yet.",
            },
            created_at=now,
            updated_at=now,
        )

        with self._lock:
            records = self._load_unlocked()
            records[action_id] = record.to_dict()
            self._save_unlocked(records)
        return record

    def get(self, action_id: str) -> PendingAction | None:
        with self._lock:
            data = self._load_unlocked().get(str(action_id))
        return PendingAction.from_dict(data) if data else None

    def list(
        self,
        *,
        session_id: str | None = None,
        status: str | None = None,
    ) -> list[PendingAction]:
        with self._lock:
            records = self._load_unlocked().values()
        actions = [PendingAction.from_dict(item) for item in records]
        if session_id:
            actions = [
                item for item in actions
                if item.session_id == session_id
            ]
        if status:
            actions = [
                item for item in actions
                if item.status == status
            ]
        return sorted(
            actions,
            key=lambda item: (item.created_at, item.id),
            reverse=True,
        )

    def confirm(
        self,
        action_id: str,
        *,
        actor: str = "api-user",
    ) -> PendingAction:
        with self._lock:
            records = self._load_unlocked()
            data = records.get(str(action_id))
            if data is None:
                raise KeyError(action_id)
            record = PendingAction.from_dict(data)
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
            records[action_id] = record.to_dict()
            self._save_unlocked(records)
            return record

    def cancel(
        self,
        action_id: str,
        *,
        actor: str = "api-user",
        reason: str = "",
    ) -> PendingAction:
        with self._lock:
            records = self._load_unlocked()
            data = records.get(str(action_id))
            if data is None:
                raise KeyError(action_id)
            record = PendingAction.from_dict(data)
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
            records[action_id] = record.to_dict()
            self._save_unlocked(records)
            return record


__all__ = [
    "PENDING_ACTIONS_PATH",
    "PendingAction",
    "PendingActionStore",
    "PreflightResult",
    "STATUS_CANCELED",
    "STATUS_CONFIRMED",
    "STATUS_EXECUTED",
    "STATUS_EXPIRED",
    "STATUS_FAILED",
    "STATUS_PENDING",
    "build_preflight",
    "get_action_preflight_contract",
]

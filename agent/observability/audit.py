"""Append-only audit events for Agent runs and governed actions."""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from agent.persistence.repositories import audit as audit_repo
from agent.observability.logger import logger

RESULT_SUCCESS = "success"
RESULT_FAILED = "failed"
RESULT_PENDING = "pending"
RESULT_BLOCKED = "blocked"
RESULT_CANCELED = "canceled"

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_HIGH = "high"

_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
    "access_token",
    "refresh_token",
}
_BEARER_PATTERN = re.compile(
    r"(?i)\b(bearer|basic)\s+[a-z0-9._~+/=-]+"
)


def _redact_value(value: Any, key: str = "") -> Any:
    if key.lower() in _SENSITIVE_KEYS:
        return "***"
    if isinstance(value, dict):
        return {
            str(item_key): _redact_value(item_value, str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_value(item) for item in value]
    if isinstance(value, str):
        redacted = _BEARER_PATTERN.sub(r"\1 ***", value)
        return redacted[:4000]
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return str(value)[:4000]


@dataclass(frozen=True)
class AuditEvent:
    id: str
    occurred_at: float
    event_type: str
    title: str
    summary: str = ""
    result: str = RESULT_SUCCESS
    severity: str = SEVERITY_INFO
    actor: str = "system"
    session_id: str = ""
    run_id: str = ""
    action_id: str = ""
    action_code: str = ""
    tool_name: str = ""
    risk_level: str = ""
    correlation_id: str = ""
    payload: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AuditEvent":
        return cls(
            id=str(data.get("id") or f"evt_{uuid.uuid4().hex}"),
            occurred_at=float(data.get("occurred_at") or time.time()),
            event_type=str(data.get("event_type") or "unknown"),
            title=str(data.get("title") or ""),
            summary=str(data.get("summary") or ""),
            result=str(data.get("result") or RESULT_SUCCESS),
            severity=str(data.get("severity") or SEVERITY_INFO),
            actor=str(data.get("actor") or "system"),
            session_id=str(data.get("session_id") or ""),
            run_id=str(data.get("run_id") or ""),
            action_id=str(data.get("action_id") or ""),
            action_code=str(data.get("action_code") or ""),
            tool_name=str(data.get("tool_name") or ""),
            risk_level=str(data.get("risk_level") or ""),
            correlation_id=str(data.get("correlation_id") or ""),
            payload=_redact_value(data.get("payload") or {}),
            metadata=_redact_value(data.get("metadata") or {}),
        )


class AuditStore:
    """Append-only audit event store backed by the database."""

    def append(self, event: AuditEvent) -> None:
        if not audit_repo.persist_audit_event(event):
            raise RuntimeError("Failed to persist audit event")

    def list_events(
        self,
        *,
        session_id: str | None = None,
        run_id: str | None = None,
        action_id: str | None = None,
        event_type: str | None = None,
        limit: int = 200,
    ) -> list[AuditEvent]:
        return [
            AuditEvent.from_dict(item)
            for item in audit_repo.fetch_audit_events(
                session_id=session_id,
                run_id=run_id,
                action_id=action_id,
                event_type=event_type,
                limit=limit,
            )
        ]

    def get_run_trace(self, run_id: str) -> list[AuditEvent]:
        events = self.list_events(run_id=run_id, limit=1000)
        return list(reversed(events))


def record_event(
    event_type: str,
    title: str,
    *,
    summary: str = "",
    result: str = RESULT_SUCCESS,
    severity: str = SEVERITY_INFO,
    actor: str = "system",
    session_id: str = "",
    run_id: str = "",
    action_id: str = "",
    action_code: str = "",
    tool_name: str = "",
    risk_level: str = "",
    correlation_id: str = "",
    payload: dict | None = None,
    metadata: dict | None = None,
) -> AuditEvent | None:
    """Persist one audit event without breaking the caller on failure."""
    event = AuditEvent(
        id=f"evt_{uuid.uuid4().hex}",
        occurred_at=time.time(),
        event_type=str(event_type or "unknown"),
        title=str(title or "")[:300],
        summary=str(summary or "")[:1000],
        result=str(result or RESULT_SUCCESS),
        severity=str(severity or SEVERITY_INFO),
        actor=str(actor or "system")[:100],
        session_id=str(session_id or ""),
        run_id=str(run_id or ""),
        action_id=str(action_id or ""),
        action_code=str(action_code or ""),
        tool_name=str(tool_name or ""),
        risk_level=str(risk_level or ""),
        correlation_id=str(correlation_id or ""),
        payload=_redact_value(payload or {}),
        metadata=_redact_value(metadata or {}),
    )
    stored = False
    try:
        stored = audit_repo.persist_audit_event(event)
    except Exception:
        logger.exception("Failed to persist audit event: %s", event_type)
    return event if stored else None


__all__ = [
    "AuditEvent",
    "AuditStore",
    "RESULT_BLOCKED",
    "RESULT_CANCELED",
    "RESULT_FAILED",
    "RESULT_PENDING",
    "RESULT_SUCCESS",
    "SEVERITY_HIGH",
    "SEVERITY_INFO",
    "SEVERITY_WARNING",
    "record_event",
]

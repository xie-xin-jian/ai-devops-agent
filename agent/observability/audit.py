"""Append-only audit events for Agent runs and governed actions."""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import agent.platform.config as config
from agent.platform.config import AUDIT_DIR
from agent.persistence import writer as persistence_writer
from agent.observability.logger import logger
from agent.platform.storage import get_path_lock


AUDIT_EVENTS_PATH = AUDIT_DIR / "events.jsonl"

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
    """Thread-safe append-only event store with simple filtered reads."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or AUDIT_EVENTS_PATH)
        self._lock = get_path_lock(self.path)

    def append(self, event: AuditEvent) -> None:
        payload = json.dumps(
            _redact_value(event.to_dict()),
            ensure_ascii=False,
            default=str,
        )
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8", newline="") as handle:
                handle.write(payload + "\n")
                handle.flush()
                os.fsync(handle.fileno())

    def _iter_lines_reverse(self):
        """Yield raw event lines newest-first with bounded reads.

        Audit files grow unboundedly; parsing every line on each listing
        made the audit page slow. Reading tail chunks backwards lets us
        stop as soon as ``limit`` matching events are collected.
        """
        if not self.path.exists():
            return
        with self._lock:
            try:
                with open(self.path, "rb") as handle:
                    handle.seek(0, os.SEEK_END)
                    position = handle.tell()
                    buffer = b""
                    chunk = 65536
                    while position > 0:
                        step = min(chunk, position)
                        position -= step
                        handle.seek(position)
                        buffer = handle.read(step) + buffer
                        lines = buffer.split(b"\n")
                        buffer = lines.pop(0)
                        for raw in reversed(lines):
                            if raw.strip():
                                yield raw
                    if buffer.strip():
                        yield buffer
            except OSError:
                return

    def list_events(
        self,
        *,
        session_id: str | None = None,
        run_id: str | None = None,
        action_id: str | None = None,
        event_type: str | None = None,
        limit: int = 200,
    ) -> list[AuditEvent]:
        limit = max(1, min(int(limit), 1000))
        events = []
        for raw_line in self._iter_lines_reverse():
            try:
                event = AuditEvent.from_dict(json.loads(raw_line))
            except (
                json.JSONDecodeError,
                TypeError,
                ValueError,
                UnicodeDecodeError,
            ):
                continue
            if session_id and event.session_id != session_id:
                continue
            if run_id and event.run_id != run_id:
                continue
            if action_id and event.action_id != action_id:
                continue
            if event_type and event.event_type != event_type:
                continue
            events.append(event)
            if len(events) >= limit:
                break
        events.sort(
            key=lambda item: (item.occurred_at, item.id),
            reverse=True,
        )
        return events

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
    backend = config.PERSISTENCE_BACKEND
    stored = False
    if backend in {"json", "dual"}:
        try:
            AuditStore().append(event)
            stored = True
        except Exception:
            logger.exception("Failed to persist audit event: %s", event_type)
    if backend == "dual":
        stored = persistence_writer.persist_audit_event(event) or stored
    elif backend == "postgres":
        stored = persistence_writer.persist_audit_event(event)
    return event if stored else None


__all__ = [
    "AUDIT_EVENTS_PATH",
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

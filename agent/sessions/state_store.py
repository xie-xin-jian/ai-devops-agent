"""Lightweight durable state for chat sessions and recoverable runs.

This store intentionally keeps only two records:

- Session: owner, timestamps, and the raw Agent message history.
- Run: status, phase, a safe-point message snapshot, and interruption reason.

It does not persist execution decisions, preflight metadata, or an event for
every model step. Those concerns remain in Tool Policy and Audit.
"""

from __future__ import annotations

import time
from typing import Any

from agent.persistence.repositories import runs as run_repo
from agent.persistence.repositories import sessions as session_repo


DEFAULT_SESSION_TTL_SECONDS = 2 * 60 * 60


RUN_STATUS_RUNNING = "running"
RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_FAILED = "failed"
RUN_STATUS_CANCELED = "canceled"
RUN_STATUS_INTERRUPTED = "interrupted"

TERMINAL_RUN_STATUSES = {
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RUN_STATUS_CANCELED,
    RUN_STATUS_INTERRUPTED,
}


def _serialize_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {
            str(key): _serialize_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_serialize_value(item) for item in value]

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            return _serialize_value(model_dump())
        except Exception:
            pass

    block_type = str(getattr(value, "type", "") or "")
    if block_type == "text":
        return {
            "type": "text",
            "text": str(getattr(value, "text", "")),
        }
    if block_type == "tool_use":
        return {
            "type": "tool_use",
            "id": str(getattr(value, "id", "")),
            "name": str(getattr(value, "name", "")),
            "input": _serialize_value(getattr(value, "input", {})),
        }
    if block_type == "tool_result":
        return {
            "type": "tool_result",
            "tool_use_id": str(getattr(value, "tool_use_id", "")),
            "content": _serialize_value(getattr(value, "content", "")),
        }

    if hasattr(value, "__dict__"):
        return {
            str(key): _serialize_value(item)
            for key, item in vars(value).items()
            if not str(key).startswith("_")
        }
    return str(value)


def serialize_message(message: dict) -> dict:
    return {
        "role": str(message.get("role") or "user"),
        "content": _serialize_value(message.get("content", "")),
    }


def serialize_messages(messages: list) -> list[dict]:
    return [
        serialize_message(message)
        for message in messages
        if isinstance(message, dict)
    ]


def deserialize_messages(messages: list | None) -> list[dict]:
    """Return plain dict messages accepted by the Anthropic SDK."""
    restored = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        restored.append({
            "role": str(message.get("role") or "user"),
            "content": message.get("content", ""),
        })
    return restored


def _compose_session_record(
    existing: dict,
    *,
    session_id: str,
    owner_id: str,
    messages: list,
    status: str,
    target_id: str | None,
    title: str | None,
    now: float,
) -> dict:
    """Build a session record from the previous state of the active read path."""
    return {
        "session_id": str(session_id),
        "owner_id": str(owner_id or existing.get("owner_id") or ""),
        "status": str(status or "active"),
        "target_id": (
            str(target_id)
            if target_id is not None
            else str(existing.get("target_id") or "")
        ),
        "title": (
            str(title).strip()[:64]
            if title is not None and str(title).strip()
            else str(existing.get("title") or "")
        ),
        "created_at": float(existing.get("created_at") or now),
        "updated_at": now,
        "messages": serialize_messages(messages),
    }


def _compose_run_record(
    existing: dict,
    *,
    run_id: str,
    session_id: str,
    owner_id: str,
    source: str,
    status: str,
    phase: str,
    user_message: str,
    messages: list,
    safe_to_resume: bool,
    active_tool: str,
    interruption_reason: str,
    now: float,
) -> dict:
    """Build a run record from the previous state of the active read path."""
    terminal = status in TERMINAL_RUN_STATUSES
    return {
        "run_id": str(run_id),
        "session_id": str(session_id),
        "owner_id": str(owner_id or ""),
        "source": str(source or "chat"),
        "status": str(status or RUN_STATUS_RUNNING),
        "phase": str(phase or "model"),
        "user_message": str(user_message or ""),
        "messages": serialize_messages(messages),
        "safe_to_resume": bool(safe_to_resume),
        "active_tool": str(active_tool or ""),
        "interruption_reason": str(interruption_reason or ""),
        "resume_count": int(existing.get("resume_count") or 0),
        "created_at": float(existing.get("created_at") or now),
        "updated_at": now,
        "finished_at": now if terminal else None,
    }


class RecoveryStore:
    """Database-backed session and run state."""

    def get_session(self, session_id: str) -> dict | None:
        return session_repo.fetch_session(session_id)

    def save_session(
        self,
        session_id: str,
        *,
        owner_id: str,
        messages: list,
        status: str = "active",
        target_id: str | None = None,
        title: str | None = None,
        ttl_seconds: float | None = None,
    ) -> dict:
        if not str(session_id or "").strip():
            raise ValueError("session_id is required")
        now = time.time()
        existing = session_repo.fetch_session(session_id) or {}
        record = _compose_session_record(
            existing,
            session_id=session_id,
            owner_id=owner_id,
            messages=messages,
            status=status,
            target_id=target_id,
            title=title,
            now=now,
        )
        if not session_repo.upsert_session(
            record,
            ttl_seconds=ttl_seconds or DEFAULT_SESSION_TTL_SECONDS,
        ):
            raise RuntimeError(f"Failed to save session {session_id}")
        return {
            **record,
            "messages": deserialize_messages(record["messages"]),
        }

    def rename_session(self, session_id: str, title: str) -> dict | None:
        """Set a custom title without touching messages or updated_at."""
        clean = str(title or "").strip()[:64]
        if not clean:
            raise ValueError("title is required")
        if not session_repo.rename_session(session_id, clean):
            return None
        return self.get_session(session_id)

    def reset_session(self, session_id: str) -> None:
        session_repo.delete_session(session_id)

    def list_sessions(
        self,
        *,
        owner_id: str | None = None,
        light: bool = False,
    ) -> list[dict]:
        return session_repo.fetch_sessions(
            owner_id=owner_id,
            include_messages=not light,
        )

    def create_run(
        self,
        run_id: str,
        *,
        session_id: str,
        owner_id: str,
        user_message: str,
        messages: list,
        source: str = "chat",
    ) -> dict:
        return self.save_run(
            run_id,
            session_id=session_id,
            owner_id=owner_id,
            source=source,
            status=RUN_STATUS_RUNNING,
            phase="model",
            user_message=user_message,
            messages=messages,
            safe_to_resume=True,
            active_tool="",
            interruption_reason="",
        )

    def save_run(
        self,
        run_id: str,
        *,
        session_id: str,
        owner_id: str,
        source: str,
        status: str,
        phase: str,
        user_message: str,
        messages: list,
        safe_to_resume: bool,
        active_tool: str = "",
        interruption_reason: str = "",
    ) -> dict:
        if not str(run_id or "").strip():
            raise ValueError("run_id is required")
        now = time.time()
        existing = run_repo.fetch_run(run_id) or {}
        record = _compose_run_record(
            existing,
            run_id=run_id,
            session_id=session_id,
            owner_id=owner_id,
            source=source,
            status=status,
            phase=phase,
            user_message=user_message,
            messages=messages,
            safe_to_resume=safe_to_resume,
            active_tool=active_tool,
            interruption_reason=interruption_reason,
            now=now,
        )
        if not run_repo.upsert_run(record, force=True):
            raise RuntimeError(f"Failed to save run {run_id}")
        return {
            **record,
            "messages": deserialize_messages(record["messages"]),
        }

    def get_run(self, run_id: str) -> dict | None:
        return run_repo.fetch_run(run_id)

    def list_runs(
        self,
        *,
        owner_id: str | None = None,
        session_id: str | None = None,
        status: str | None = None,
        statuses: set[str] | None = None,
        limit: int = 100,
        include_messages: bool = False,
    ) -> list[dict]:
        runs = run_repo.fetch_runs(
            owner_id=owner_id,
            session_id=session_id,
            status=status,
            statuses=statuses,
            limit=limit,
        )
        if include_messages:
            for run in runs:
                stored = run_repo.fetch_run(str(run.get("run_id") or ""))
                run["messages"] = (
                    list(stored.get("messages") or [])
                    if stored
                    else []
                )
        return runs

    def mark_resumed(self, run_id: str) -> dict:
        record = self.get_run(run_id)
        if record is None:
            raise KeyError(run_id)
        return self.save_run(
            run_id,
            session_id=record.get("session_id", ""),
            owner_id=record.get("owner_id", ""),
            source=record.get("source", "chat"),
            status=RUN_STATUS_RUNNING,
            phase="resuming",
            user_message=record.get("user_message", ""),
            messages=record.get("messages", []),
            safe_to_resume=True,
            active_tool="",
            interruption_reason="",
        )

    def interrupt_stale_runs(self, reason: str) -> list[dict]:
        candidates = [
            run
            for run in run_repo.fetch_runs(limit=1000)
            if run.get("status") not in TERMINAL_RUN_STATUSES
        ]
        if not candidates:
            return []
        run_repo.interrupt_stale_runs(str(reason))
        interrupted = []
        for candidate in candidates:
            record = run_repo.fetch_run(str(candidate.get("run_id") or ""))
            if record is not None:
                interrupted.append(record)
        return interrupted


__all__ = [
    "RecoveryStore",
    "RUN_STATUS_CANCELED",
    "RUN_STATUS_COMPLETED",
    "RUN_STATUS_FAILED",
    "RUN_STATUS_INTERRUPTED",
    "RUN_STATUS_RUNNING",
    "TERMINAL_RUN_STATUSES",
    "deserialize_messages",
    "serialize_message",
    "serialize_messages",
]

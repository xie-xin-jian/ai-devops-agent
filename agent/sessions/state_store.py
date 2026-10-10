"""Lightweight durable state for chat sessions and recoverable runs.

This store intentionally keeps only two records:

- Session: owner, timestamps, and the raw Agent message history.
- Run: status, phase, a safe-point message snapshot, and interruption reason.

It does not persist execution decisions, preflight metadata, or an event for
every model step. Those concerns remain in Tool Policy and Audit.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import agent.platform.config as config
from agent.platform.storage import atomic_write_json, get_path_lock


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


def _safe_name(value: str, fallback_prefix: str) -> str:
    safe = "".join(
        char if char.isalnum() or char in "-_" else "_"
        for char in str(value or "")
    )[:120]
    return safe or f"{fallback_prefix}_{int(time.time() * 1000)}"


class RecoveryStore:
    """JSON-backed session and run state with atomic writes."""

    def __init__(
        self,
        *,
        sessions_dir: str | Path | None = None,
        runs_dir: str | Path | None = None,
    ):
        self.sessions_dir = Path(
            sessions_dir or config.SESSIONS_DIR
        )
        self.runs_dir = Path(runs_dir or config.RUNS_DIR)

    def _session_path(self, session_id: str) -> Path:
        name = _safe_name(session_id, "session")
        return self.sessions_dir / f"{name}.json"

    def _run_path(self, run_id: str) -> Path:
        name = _safe_name(run_id, "run")
        return self.runs_dir / f"{name}.json"

    @staticmethod
    def _read_json(path: Path) -> dict | None:
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return None
        return value if isinstance(value, dict) else None

    def get_session(self, session_id: str) -> dict | None:
        path = self._session_path(session_id)
        lock = get_path_lock(path)
        with lock:
            record = self._read_json(path)
        if record is None:
            return None
        return {
            **record,
            "messages": deserialize_messages(record.get("messages")),
        }

    def save_session(
        self,
        session_id: str,
        *,
        owner_id: str,
        messages: list,
        status: str = "active",
        target_id: str | None = None,
    ) -> dict:
        if not str(session_id or "").strip():
            raise ValueError("session_id is required")
        path = self._session_path(session_id)
        lock = get_path_lock(path)
        now = time.time()
        with lock:
            existing = self._read_json(path) or {}
            record = {
                "session_id": str(session_id),
                "owner_id": str(owner_id or existing.get("owner_id") or ""),
                "status": str(status or "active"),
                "target_id": (
                    str(target_id)
                    if target_id is not None
                    else str(existing.get("target_id") or "")
                ),
                "created_at": float(existing.get("created_at") or now),
                "updated_at": now,
                "messages": serialize_messages(messages),
            }
            atomic_write_json(path, record)
        return {
            **record,
            "messages": deserialize_messages(record["messages"]),
        }

    def reset_session(self, session_id: str) -> None:
        path = self._session_path(session_id)
        lock = get_path_lock(path)
        with lock:
            if path.exists():
                path.unlink()

    def list_sessions(
        self,
        *,
        owner_id: str | None = None,
    ) -> list[dict]:
        if not self.sessions_dir.exists():
            return []
        records = []
        for path in self.sessions_dir.glob("*.json"):
            lock = get_path_lock(path)
            with lock:
                record = self._read_json(path)
            if record is None:
                continue
            if (
                owner_id
                and record.get("owner_id")
                and record.get("owner_id") != owner_id
            ):
                continue
            records.append({
                **record,
                "messages": deserialize_messages(record.get("messages")),
            })
        records.sort(
            key=lambda item: (
                float(item.get("updated_at") or 0),
                str(item.get("session_id") or ""),
            ),
            reverse=True,
        )
        return records

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
        path = self._run_path(run_id)
        lock = get_path_lock(path)
        now = time.time()
        with lock:
            existing = self._read_json(path) or {}
            terminal = status in TERMINAL_RUN_STATUSES
            record = {
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
            atomic_write_json(path, record)
        return {
            **record,
            "messages": deserialize_messages(record["messages"]),
        }

    def get_run(self, run_id: str) -> dict | None:
        path = self._run_path(run_id)
        lock = get_path_lock(path)
        with lock:
            record = self._read_json(path)
        if record is None:
            return None
        return {
            **record,
            "messages": deserialize_messages(record.get("messages")),
        }

    def list_runs(
        self,
        *,
        owner_id: str | None = None,
        session_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        if not self.runs_dir.exists():
            return []
        records = []
        for path in self.runs_dir.glob("*.json"):
            lock = get_path_lock(path)
            with lock:
                record = self._read_json(path)
            if record is None:
                continue
            if (
                owner_id
                and record.get("owner_id")
                and record.get("owner_id") != owner_id
            ):
                continue
            if session_id and record.get("session_id") != session_id:
                continue
            if status and record.get("status") != status:
                continue
            records.append({
                **record,
                "messages": deserialize_messages(record.get("messages")),
            })
        records.sort(
            key=lambda item: (
                float(item.get("updated_at") or 0),
                str(item.get("run_id") or ""),
            ),
            reverse=True,
        )
        return records[:max(1, min(int(limit), 500))]

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
        interrupted = []
        if not self.runs_dir.exists():
            return interrupted
        for path in self.runs_dir.glob("*.json"):
            lock = get_path_lock(path)
            with lock:
                record = self._read_json(path)
                if (
                    record is None
                    or record.get("status") in TERMINAL_RUN_STATUSES
                ):
                    continue
                now = time.time()
                record["status"] = RUN_STATUS_INTERRUPTED
                record["phase"] = "interrupted"
                record["interruption_reason"] = str(reason)
                record["active_tool"] = ""
                record["safe_to_resume"] = bool(
                    record.get("safe_to_resume")
                )
                record["updated_at"] = now
                record["finished_at"] = now
                atomic_write_json(path, record)
            interrupted.append({
                **record,
                "messages": deserialize_messages(record.get("messages")),
            })
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

"""Session lifecycle management for chat Agent instances."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta
from typing import Callable

from agent.observability.audit import record_event
from agent.core.comprehensive import ComprehensiveAgent
from agent.platform.identity import Principal, SESSION_MANAGE, system_admin_principal
from agent.sessions.state_store import RecoveryStore


def _message_text(content) -> str:
    """Extract readable text from a raw stored message content value."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return " ".join(parts)
    return ""


def _session_summary(record: dict) -> tuple[int, str]:
    """Message count and first user message, from either read path.

    The local store returns the raw message list; the PostgreSQL list read
    deliberately skips message history and returns a count plus the single
    message the sidebar needs for its title.
    """
    if "messages" in record:
        count = 0
        first_user = ""
        for item in record.get("messages") or []:
            if not isinstance(item, dict):
                continue
            count += 1
            if not first_user and item.get("role") == "user":
                first_user = _message_text(item.get("content"))
        return count, first_user
    return (
        int(record.get("message_count") or 0),
        _message_text(record.get("first_user_message")),
    )


class SessionAccessError(PermissionError):
    """Raised when a principal cannot access an existing session."""


class SessionManager:
    """Owns live Agent sessions, TTL, locks, restoration, and ownership."""

    def __init__(
        self,
        *,
        ttl: timedelta = timedelta(hours=2),
        state_store: RecoveryStore | None = None,
        agent_factory: Callable[..., ComprehensiveAgent] | None = None,
    ):
        self.ttl = ttl
        self.state_store = state_store or RecoveryStore()
        self.agent_factory = agent_factory or ComprehensiveAgent
        self._sessions: dict[str, dict] = {}

    def cleanup_expired(self) -> list[str]:
        now = datetime.now()
        expired = [
            session_id
            for session_id, session in self._sessions.items()
            if now - session["last_used"] > self.ttl
        ]
        for session_id in expired:
            self._sessions.pop(session_id, None)
        return expired

    def get(self, session_id: str) -> dict | None:
        return self._sessions.get(str(session_id or ""))

    def exists(self, session_id: str) -> bool:
        session_id = str(session_id or "")
        return (
            session_id in self._sessions
            or self.state_store.get_session(session_id) is not None
        )

    def get_or_create(
        self,
        session_id: str | None = None,
        principal: Principal | None = None,
    ) -> tuple[str, dict]:
        principal = principal or system_admin_principal()
        self.cleanup_expired()

        if session_id and session_id in self._sessions:
            session = self._sessions[session_id]
            self._check_access(session, principal)
            session["last_used"] = datetime.now()
            return session_id, session

        new_id = session_id or str(uuid.uuid4())
        stored_session = self.state_store.get_session(new_id)
        if stored_session:
            self._check_owner(
                stored_session.get("owner_id", ""),
                principal,
            )

        from agent.mcp.client import load_all_custom_servers

        load_all_custom_servers()
        stored_target_id = (
            str(stored_session.get("target_id") or "")
            if stored_session
            else ""
        )
        agent = self.agent_factory(
            session_id=new_id,
            principal=principal,
        )
        agent.target_id = stored_target_id
        executor = getattr(agent, "tool_executor", None)
        if executor is not None:
            executor.target_id = stored_target_id
        if stored_session:
            agent.messages = stored_session.get("messages", [])
            for message in reversed(agent.messages):
                if (
                    message.get("role") == "user"
                    and isinstance(message.get("content"), str)
                ):
                    agent._last_user_query = message["content"]
                    break

        owner_id = (
            str(stored_session.get("owner_id") or principal.id)
            if stored_session
            else principal.id
        )
        session = {
            "agent": agent,
            "owner_id": owner_id,
            "last_used": datetime.now(),
            "cancel_event": threading.Event(),
            "run_lock": threading.Lock(),
        }
        self._sessions[new_id] = session

        if stored_session is None:
            self.state_store.save_session(
                new_id,
                owner_id=principal.id,
                messages=[],
                target_id="",
                ttl_seconds=self.ttl.total_seconds(),
            )
        record_event(
            "session.restored" if stored_session else "session.created",
            (
                "Agent session restored"
                if stored_session
                else "Agent session created"
            ),
            result="success",
            severity="info",
            actor=owner_id or principal.id,
            session_id=new_id,
            correlation_id=new_id,
            payload={
                "roles": sorted(principal.roles),
                "restored": bool(stored_session),
            },
        )
        return new_id, session

    def activate_target(
        self,
        session_id: str,
        target_id: str,
        principal: Principal,
    ) -> dict:
        session = self._sessions.get(str(session_id or ""))
        if session is None:
            session_id, session = self.get_or_create(session_id, principal)
        self._check_access(session, principal)

        identifier = str(target_id or "").strip()
        agent = session["agent"]
        agent.target_id = identifier
        executor = getattr(agent, "tool_executor", None)
        if executor is not None:
            executor.target_id = identifier
        self.state_store.save_session(
            session_id,
            owner_id=session.get("owner_id") or principal.id,
            messages=agent.get_messages(),
            target_id=identifier,
            ttl_seconds=self.ttl.total_seconds(),
        )
        record_event(
            "session.target_activated",
            "Session target activated",
            result="success",
            severity="info",
            actor=principal.id,
            session_id=session_id,
            correlation_id=session_id,
            payload={"target_id": identifier},
        )
        return {
            "session_id": session_id,
            "target_id": identifier,
        }

    def run_sync(self, session: dict, message: str) -> str:
        with session["run_lock"]:
            session["cancel_event"].clear()
            return session["agent"].run(
                message,
                session["cancel_event"],
            )

    def cancel(self, session_id: str, principal: Principal) -> dict:
        session = self._sessions.get(str(session_id or ""))
        if session is None:
            raise KeyError(session_id)
        self._check_access(session, principal)
        session["cancel_event"].set()
        return session

    def reset(self, session_id: str, principal: Principal) -> None:
        session = self._sessions.get(str(session_id or ""))
        if session is not None:
            self._check_access(session, principal)
            session["agent"].reset()
            record_event(
                "session.reset",
                "Agent session reset",
                result="success",
                severity="info",
                actor=principal.id,
                session_id=session_id,
                correlation_id=session_id,
            )
            return

        stored_session = self.state_store.get_session(session_id)
        if stored_session:
            self._check_owner(
                stored_session.get("owner_id", ""),
                principal,
            )
        self.state_store.reset_session(session_id)

    def list_sessions(self, principal: Principal) -> list[dict]:
        """List sessions ordered by persisted activity.

        Ordering uses the stored ``updated_at`` only: opening a session
        must not reorder the sidebar; order changes when a run persists
        messages, not when a session is merely opened.
        """
        sessions = []
        for record in self.state_store.list_sessions(light=True):
            sid = str(record.get("session_id") or "")
            owner_id = str(record.get("owner_id") or "")
            if not self._can_access_owner(owner_id, principal):
                continue
            message_count, first_user = _session_summary(record)
            title = str(record.get("title") or "").strip()
            sessions.append({
                "id": sid,
                "title": title or first_user[:32] or "新对话",
                "updated_at": float(record.get("updated_at") or 0),
                "message_count": message_count,
            })
        sessions.sort(
            key=lambda item: item["updated_at"],
            reverse=True,
        )
        return sessions

    def rename_session(
        self,
        session_id: str,
        title: str,
        principal: Principal,
    ) -> dict:
        clean = str(title or "").strip()[:64]
        if not clean:
            raise ValueError("title is required")
        stored = self.state_store.get_session(session_id)
        if stored is None:
            raise KeyError(session_id)
        self._check_owner(stored.get("owner_id", ""), principal)
        self.state_store.rename_session(session_id, clean)
        record_event(
            "session.renamed",
            "Session renamed",
            result="success",
            severity="info",
            actor=principal.id,
            session_id=session_id,
            correlation_id=session_id,
            payload={"title": clean},
        )
        return {"session_id": session_id, "title": clean}

    def _check_access(
        self,
        session: dict,
        principal: Principal,
    ) -> None:
        self._check_owner(session.get("owner_id", ""), principal)

    @staticmethod
    def _can_access_owner(
        owner_id: str,
        principal: Principal,
    ) -> bool:
        return (
            not owner_id
            or owner_id == principal.id
            or principal.has(SESSION_MANAGE)
        )

    def _check_owner(
        self,
        owner_id: str,
        principal: Principal,
    ) -> None:
        if not self._can_access_owner(owner_id, principal):
            raise SessionAccessError(
                "Session belongs to another user"
            )


__all__ = [
    "SessionAccessError",
    "SessionManager",
]

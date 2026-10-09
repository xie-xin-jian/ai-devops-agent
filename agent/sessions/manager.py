"""Session lifecycle management for chat Agent instances."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta
from typing import Callable

from agent.observability.audit import record_event
from agent.core.comprehensive import ComprehensiveAgent
from agent.sessions.messages import serialize_visible_messages
from agent.platform.identity import Principal, SESSION_MANAGE, system_admin_principal
from agent.sessions.state_store import RecoveryStore


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
        agent = self.agent_factory(
            session_id=new_id,
            principal=principal,
        )
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
        sessions = []
        for record in self.state_store.list_sessions():
            sid = str(record.get("session_id") or "")
            owner_id = str(record.get("owner_id") or "")
            if not self._can_access_owner(owner_id, principal):
                continue
            visible = serialize_visible_messages(
                record.get("messages", [])
            )
            first_user = next(
                (
                    item.get("content", "")
                    for item in visible
                    if item.get("role") == "user"
                ),
                "",
            )
            live_session = self._sessions.get(sid)
            updated_at = float(record.get("updated_at") or 0)
            if live_session is not None:
                updated_at = max(
                    updated_at,
                    live_session["last_used"].timestamp(),
                )
            sessions.append({
                "id": sid,
                "title": first_user[:32] or "新对话",
                "updated_at": updated_at,
                "message_count": len(visible),
            })
        sessions.sort(
            key=lambda item: item["updated_at"],
            reverse=True,
        )
        return sessions

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

"""SessionManager lifecycle tests."""

from datetime import timedelta

import pytest

from agent.platform.identity import principal_from_roles
from agent.sessions.manager import (
    SessionAccessError,
    SessionManager,
)
from agent.sessions.state_store import RecoveryStore


class FakeAgent:
    def __init__(self, *, session_id="", principal=None):
        self.session_id = session_id
        self.principal = principal
        self.messages = []
        self.reset_called = False

    def run(self, message, cancel_event):
        return f"reply:{message}"

    def reset(self):
        self.messages = []
        self.reset_called = True

    def get_messages(self):
        return list(self.messages)


def _store(tmp_path):
    return RecoveryStore()


def test_session_manager_restores_messages(tmp_path):
    store = _store(tmp_path)
    store.save_session(
        "session-1",
        owner_id="alice",
        messages=[{"role": "user", "content": "hello"}],
    )
    manager = SessionManager(
        state_store=store,
        agent_factory=FakeAgent,
    )

    session_id, session = manager.get_or_create(
        "session-1",
        principal_from_roles("alice", {"developer"}),
    )

    assert session_id == "session-1"
    assert session["agent"].messages[0]["content"] == "hello"
    assert session["agent"]._last_user_query == "hello"


def test_session_manager_rejects_other_owner(tmp_path):
    store = _store(tmp_path)
    store.save_session(
        "session-1",
        owner_id="bob",
        messages=[],
    )
    manager = SessionManager(
        state_store=store,
        agent_factory=FakeAgent,
    )

    with pytest.raises(SessionAccessError):
        manager.get_or_create(
            "session-1",
            principal_from_roles("alice", {"developer"}),
        )


def test_session_manager_run_cancel_and_reset(tmp_path):
    manager = SessionManager(
        state_store=_store(tmp_path),
        agent_factory=FakeAgent,
    )
    principal = principal_from_roles("alice", {"developer"})
    _, session = manager.get_or_create(None, principal)

    assert manager.run_sync(session, "hello") == "reply:hello"

    session_id = session["agent"].session_id
    manager.cancel(session_id, principal)
    assert session["cancel_event"].is_set()

    manager.reset(session_id, principal)
    assert session["agent"].reset_called is True


def test_session_manager_expires_only_live_state(tmp_path):
    store = _store(tmp_path)
    manager = SessionManager(
        ttl=timedelta(seconds=-1),
        state_store=store,
        agent_factory=FakeAgent,
    )
    principal = principal_from_roles("alice", {"developer"})
    session_id, _ = manager.get_or_create(None, principal)

    assert manager.cleanup_expired() == [session_id]
    assert manager.get(session_id) is None
    assert store.get_session(session_id) is not None


def test_session_manager_binds_target_to_session(tmp_path):
    store = _store(tmp_path)
    manager = SessionManager(
        state_store=store,
        agent_factory=FakeAgent,
    )
    principal = principal_from_roles("alice", {"developer"})
    session_id, session = manager.get_or_create(None, principal)

    result = manager.activate_target(session_id, "tgt_test", principal)

    assert result["target_id"] == "tgt_test"
    assert session["agent"].target_id == "tgt_test"
    assert store.get_session(session_id)["target_id"] == "tgt_test"

"""Complete conversation history and model context stay independent."""

from types import SimpleNamespace

from agent.core import comprehensive, context_manager
from agent.platform.identity import (
    principal_from_roles,
    system_admin_principal,
)
from agent.sessions.manager import SessionManager
from agent.sessions.state_store import RecoveryStore


class _ContextFakeAgent:
    def __init__(self, *, session_id="", principal=None):
        self.session_id = session_id
        self.principal = principal
        self.messages = []
        self.history_messages = []
        self.target_id = ""
        self._last_user_query = ""
        self.tool_executor = None

    def get_messages(self):
        return list(self.history_messages)

    def get_model_context(self):
        return list(self.messages)

    def reset(self):
        self.messages = []
        self.history_messages = []


def _history():
    return [
        {"role": "user", "content": "old question"},
        {"role": "assistant", "content": "old answer"},
        {"role": "user", "content": "current question"},
    ]


def test_store_round_trips_history_and_compacted_context_separately():
    store = RecoveryStore()
    compacted = [{
        "role": "user",
        "content": "summary for the model",
    }]

    store.save_session(
        "session-separated",
        owner_id="alice",
        messages=_history(),
        model_context=compacted,
    )
    record = store.get_session("session-separated")

    assert record["messages"] == _history()
    assert record["model_context"] == compacted

    store.reset_session("session-separated")
    assert store.get_session("session-separated") is None


def test_legacy_save_initializes_context_from_complete_history():
    store = RecoveryStore()
    store.save_session(
        "legacy-session",
        owner_id="alice",
        messages=_history(),
    )

    record = store.get_session("legacy-session")

    assert record["messages"] == _history()
    assert record["model_context"] == _history()


def test_session_manager_restores_each_state_to_its_own_field():
    store = RecoveryStore()
    compacted = [{
        "role": "user",
        "content": "compacted model context",
    }]
    store.save_session(
        "session-manager",
        owner_id="alice",
        messages=_history(),
        model_context=compacted,
    )
    manager = SessionManager(
        state_store=store,
        agent_factory=_ContextFakeAgent,
    )

    _, session = manager.get_or_create(
        "session-manager",
        principal_from_roles("alice", {"developer"}),
    )
    agent = session["agent"]

    assert agent.messages == compacted
    assert agent.history_messages == _history()
    assert agent.get_messages() == _history()
    assert agent._last_user_query == "current question"


def test_runtime_persistence_never_uses_compacted_context_as_history():
    store = RecoveryStore()
    agent = object.__new__(comprehensive.ComprehensiveAgent)
    agent.session_id = "session-runtime"
    agent.principal = system_admin_principal()
    agent.state_store = store
    agent.target_id = ""
    agent.messages = [{
        "role": "user",
        "content": "compacted model context",
    }]
    agent.history_messages = _history()

    agent._persist_session_state()
    record = store.get_session("session-runtime")

    assert record["messages"] == _history()
    assert record["model_context"] == agent.messages


def test_compaction_changes_only_model_context(monkeypatch):
    agent = object.__new__(comprehensive.ComprehensiveAgent)
    history = _history()
    agent.messages = [{
        "role": "user",
        "content": "x" * 60000,
    }]
    agent.history_messages = list(history)
    agent.run_goal = "finish the task"
    agent.client = object()
    agent.recovery = SimpleNamespace(current_model="test-model")
    agent._compaction_window = 0

    monkeypatch.setattr(
        context_manager,
        "checkpoint_compact",
        lambda messages, client, model, goal="": [{
            "role": "user",
            "content": "strictly compacted context",
        }],
    )

    agent.messages = agent._compact_if_needed(agent.messages)

    assert agent.messages[0]["content"] == "strictly compacted context"
    assert agent.history_messages == history


def test_append_message_updates_both_state_views():
    agent = object.__new__(comprehensive.ComprehensiveAgent)
    agent.messages = []
    agent.history_messages = []

    agent.append_message({
        "role": "user",
        "content": "hello",
    })

    assert agent.messages == [{"role": "user", "content": "hello"}]
    assert agent.history_messages == [
        {"role": "user", "content": "hello"}
    ]

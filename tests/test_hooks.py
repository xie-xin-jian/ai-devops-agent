"""Hook registry behavior tests."""

import pytest

from agent.core import hooks


@pytest.fixture(autouse=True)
def clean_hooks():
    with hooks._hooks_lock:
        original = {event: list(callbacks) for event, callbacks in hooks.HOOKS.items()}
        for callbacks in hooks.HOOKS.values():
            callbacks.clear()
    yield
    with hooks._hooks_lock:
        hooks.HOOKS.clear()
        hooks.HOOKS.update(original)


def test_register_hook_is_idempotent():
    def callback(block):
        return None

    hooks.register_hook("PreToolUse", callback)
    hooks.register_hook("PreToolUse", callback)

    assert hooks.HOOKS["PreToolUse"] == [callback]


def test_register_hook_rejects_unknown_event():
    with pytest.raises(ValueError, match="Unknown hook event"):
        hooks.register_hook("UnknownEvent", lambda: None)


def test_trigger_hooks_stops_on_first_non_none_result():
    calls = []

    def first_hook(block):
        calls.append("first")
        return "blocked"

    def second_hook(block):
        calls.append("second")
        return None

    hooks.register_hook("PreToolUse", first_hook)
    hooks.register_hook("PreToolUse", second_hook)

    result = hooks.trigger_hooks("PreToolUse", {"name": "bash"})

    assert result == "blocked"
    assert calls == ["first"]

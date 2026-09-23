import threading


HOOKS = {
    "UserPromptSubmit": [],
    "PreToolUse": [],
    "PostToolUse": [],
    "Stop": [],
}
_hooks_lock = threading.RLock()


def register_hook(event, callback):
    if event not in HOOKS:
        raise ValueError(f"Unknown hook event: {event}")
    with _hooks_lock:
        callbacks = HOOKS[event]
        if callback not in callbacks:
            callbacks.append(callback)


def trigger_hooks(event, *args):
    if event not in HOOKS:
        raise ValueError(f"Unknown hook event: {event}")
    with _hooks_lock:
        callbacks = list(HOOKS[event])

    for callback in callbacks:
        result = callback(*args)
        if result is not None:
            return result
    return None

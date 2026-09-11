"""Small, dependency-free helpers for safe local JSON persistence."""

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any


_locks_guard = threading.Lock()
_path_locks: dict[Path, threading.RLock] = {}


def get_path_lock(path: str | Path) -> threading.RLock:
    """Return a process-local lock shared by all writers of the same path."""
    resolved = Path(path).resolve()
    with _locks_guard:
        lock = _path_locks.get(resolved)
        if lock is None:
            lock = threading.RLock()
            _path_locks[resolved] = lock
        return lock


def atomic_write_text(path: str | Path, content: str, encoding: str = "utf-8") -> None:
    """Write text through a temporary file and atomically replace the target."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = get_path_lock(target)

    with lock:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".tmp",
            dir=target.parent,
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding=encoding, newline="") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, target)
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)


def atomic_write_json(
    path: str | Path,
    data: Any,
    *,
    ensure_ascii: bool = False,
    indent: int | None = 2,
) -> None:
    """Serialize data as JSON and persist it atomically."""
    content = json.dumps(data, ensure_ascii=ensure_ascii, indent=indent)
    atomic_write_text(path, content)

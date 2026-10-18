"""Memory persistence and access statistics."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from agent.memory.models import MemoryRecord
from agent.persistence import writer as persistence_writer
from agent.persistence.routing import pg_read, read_from_postgres
from agent.persistence.repositories import memories as memory_repo
from agent.platform.config import (
    MEMORY_ACCESS_FLUSH_BATCH,
    MEMORY_ACCESS_FLUSH_INTERVAL_SECONDS,
    MEMORY_DIR,
)
from agent.platform.storage import atomic_write_text

MEMORY_DIR.mkdir(parents=True, exist_ok=True)
_memory_lock = threading.RLock()


class MemoryStoreMixin:
    def __init__(self):
        self.memories: list[dict] = []
        self._file_state: tuple[int, int] | None = None
        self._access_deltas: dict[str, int] = {}
        self._access_last_accessed: dict[str, float] = {}
        self._last_access_flush = time.time()
        self._load()

    def _path(self) -> Path:
        return MEMORY_DIR / "memories.jsonl"

    def _load(self):
        used_postgres, records = pg_read(
            "memories",
            lambda: memory_repo.fetch_memories(limit=100000),
        )
        if used_postgres:
            self.memories = sorted(
                (dict(item) for item in records or []),
                key=lambda item: (
                    float(item.get("created_at") or 0.0),
                    str(item.get("id") or ""),
                ),
            )
            return

        path = self._path()
        self.memories = []
        if not path.exists():
            self._file_state = None
            return

        stat = path.stat()
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = MemoryRecord.from_dict(json.loads(line))
                except (json.JSONDecodeError, ValueError, TypeError):
                    continue
                self.memories.append(record.to_dict())
        self._file_state = (stat.st_mtime_ns, stat.st_size)

    def _save(self):
        path = self._path()
        content = "".join(
            json.dumps(m, ensure_ascii=False) + "\n" for m in self.memories
        )
        atomic_write_text(path, content)
        stat = path.stat()
        self._file_state = (stat.st_mtime_ns, stat.st_size)
        persistence_writer.persist_memories(self.memories)
        self._access_deltas.clear()
        self._access_last_accessed.clear()
        self._last_access_flush = time.time()

    def _reload_if_changed(self):
        if read_from_postgres("memories"):
            # PostgreSQL is the read source here; the local file is only the
            # write return-path, so its mtime must not drive a reload.
            return
        path = self._path()
        if not path.exists():
            self.memories = []
            self._file_state = None
            return
        stat = path.stat()
        current_state = (stat.st_mtime_ns, stat.st_size)
        if current_state != self._file_state:
            self._load()

    def flush_access_stats(self, force: bool = False) -> int:
        """Persist queued access counters in a batch."""
        with _memory_lock:
            if not self._access_deltas:
                return 0

            now = time.time()
            due = (
                force
                or len(self._access_deltas) >= MEMORY_ACCESS_FLUSH_BATCH
                or now - self._last_access_flush >= MEMORY_ACCESS_FLUSH_INTERVAL_SECONDS
            )
            if not due:
                return 0

            deltas = dict(self._access_deltas)
            last_accessed = dict(self._access_last_accessed)
            self._load()

            applied = 0
            for memory_id, delta in deltas.items():
                memory = self._find_memory(memory_id)
                if memory is None:
                    continue
                memory["access_count"] = memory.get("access_count", 0) + delta
                memory["last_accessed_at"] = max(
                    float(memory.get("last_accessed_at") or 0.0),
                    float(last_accessed.get(memory_id) or 0.0),
                )
                applied += 1

            if applied:
                self._save()
            else:
                self._access_deltas.clear()
                self._access_last_accessed.clear()
                self._last_access_flush = now
            return applied

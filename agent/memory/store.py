"""Memory persistence and access statistics."""

from __future__ import annotations

import threading
import time

from agent.persistence.repositories import memories as memory_repo
from agent.platform.config import (
    MEMORY_ACCESS_FLUSH_BATCH,
    MEMORY_ACCESS_FLUSH_INTERVAL_SECONDS,
)

_memory_lock = threading.RLock()


class MemoryStoreMixin:
    def __init__(self):
        self.memories: list[dict] = []
        self._access_deltas: dict[str, int] = {}
        self._access_last_accessed: dict[str, float] = {}
        self._last_access_flush = time.time()
        self._generation = memory_repo.memory_generation()
        self._load()

    def _load(self):
        self.memories = sorted(
            (dict(item) for item in memory_repo.fetch_memories(limit=100000)),
            key=lambda item: (
                float(item.get("created_at") or 0.0),
                str(item.get("id") or ""),
            ),
        )
        self._generation = memory_repo.memory_generation()

    def _save(self):
        memory_repo.upsert_memories(self.memories, force=True)
        self._generation = memory_repo.memory_generation()
        self._access_deltas.clear()
        self._access_last_accessed.clear()
        self._last_access_flush = time.time()

    def _reload_if_changed(self):
        if memory_repo.memory_generation() != self._generation:
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

"""Memory retrieval and formatting."""

from __future__ import annotations

import time

from agent.memory.models import (
    _memory_score,
    similarity_score,
    tokenize_text,
)
from agent.memory.store import _memory_lock
from agent.platform.config import (
    MEMORY_MIN_SCORE,
    MEMORY_NEAR_DUP_THRESHOLD,
    MEMORY_TOP_K,
)


class MemoryRetrievalMixin:
    def find_similar(
        self,
        content: str,
        *,
        scope: str,
        memory_type: str | None = None,
        threshold: float | None = None,
        limit: int = 5,
    ) -> list[dict]:
        threshold_value = MEMORY_NEAR_DUP_THRESHOLD if threshold is None else threshold
        with _memory_lock:
            self._reload_if_changed()
            matches = []
            for memory in self.memories:
                if memory.get("status", "active") != "active":
                    continue
                if memory.get("scope", "global") != scope:
                    continue
                if memory_type and memory.get("memory_type") != memory_type:
                    continue

                similarity = similarity_score(content, memory.get("content", ""))
                if similarity >= threshold_value:
                    matches.append(
                        {
                            "memory": dict(memory),
                            "similarity": similarity,
                        }
                    )

            matches.sort(
                key=lambda item: item["similarity"],
                reverse=True,
            )
            return matches[: max(1, limit)]

    def _best_near_duplicate(
        self,
        content: str,
        *,
        scope: str,
        memory_type: str,
        entity_type: str,
        entity_key: str,
    ) -> tuple[dict | None, float]:
        best_memory = None
        best_similarity = 0.0
        for memory in self.memories:
            if memory.get("status") != "active":
                continue
            if memory.get("scope", "global") != scope:
                continue
            if memory.get("memory_type") != memory_type:
                continue
            if (
                entity_type
                and entity_key
                and memory.get("entity_type") == entity_type
                and memory.get("entity_key")
                and memory.get("entity_key") != entity_key
            ):
                continue

            similarity = similarity_score(content, memory.get("content", ""))
            if similarity > best_similarity:
                best_memory = memory
                best_similarity = similarity

        return best_memory, best_similarity

    def select(
        self,
        query: str,
        top_k: int | None = None,
        *,
        scope: str | None = None,
        scopes: set[str] | tuple[str, ...] | list[str] | None = None,
        memory_type: str | None = None,
        status: str = "active",
        min_score: float | None = None,
    ) -> list[dict]:
        """Select memories with lightweight keyword and metadata scoring."""
        with _memory_lock:
            self._reload_if_changed()
            query_tokens = tokenize_text(query)
            scored = []
            threshold = MEMORY_MIN_SCORE if min_score is None else min_score
            limit = MEMORY_TOP_K if top_k is None else max(1, top_k)

            for memory in self.memories:
                if status and memory.get("status", "active") != status:
                    continue
                if scope and memory.get("scope", "global") != scope:
                    continue
                if scopes and memory.get("scope", "global") not in scopes:
                    continue
                if memory_type and memory.get("memory_type") != memory_type:
                    continue

                score, relevance = _memory_score(query, query_tokens, memory)
                if relevance > 0 and score >= threshold:
                    scored.append((score, memory))

            scored.sort(key=lambda item: item[0], reverse=True)
            result = [memory for _, memory in scored[:limit]]
            now = time.time()
            for memory in result:
                memory["access_count"] = memory.get("access_count", 0) + 1
                memory["last_accessed_at"] = now
                memory_id = memory["id"]
                self._access_deltas[memory_id] = (
                    self._access_deltas.get(memory_id, 0) + 1
                )
                self._access_last_accessed[memory_id] = now

        self.flush_access_stats()
        return result

    def extract(self, memories: list[dict]) -> str:
        """Format selected memories for injection into the system prompt."""
        if not memories:
            return "(no relevant memories)"
        lines = []
        for index, memory in enumerate(memories, 1):
            lines.append(
                f"[{index}] "
                f"(id={memory.get('id', '')}, "
                f"{memory.get('memory_type', 'semantic')}, "
                f"{memory.get('category', 'general')}, "
                f"importance={memory.get('importance', 3)}) "
                f"{memory.get('content', '')}"
            )
        return "\n".join(lines)

    def format_relevant(
        self,
        query: str,
        *,
        scope: str | None = None,
        scopes: set[str] | tuple[str, ...] | list[str] | None = None,
        memory_type: str | None = None,
    ) -> str:
        """Select and format relevant memories."""
        selected = self.select(
            query,
            scope=scope,
            scopes=scopes,
            memory_type=memory_type,
        )
        return self.extract(selected)

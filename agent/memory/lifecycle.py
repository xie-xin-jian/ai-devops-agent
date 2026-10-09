"""Memory lifecycle and mutation operations."""

from __future__ import annotations

import time
import uuid

from agent.memory.models import (
    MemoryRecord,
    _normalize_tags,
    _validate_confidence,
    _validate_importance,
    _validate_memory_type,
    content_hash,
    normalize_content,
)
from agent.memory.store import _memory_lock
from agent.platform.config import MEMORY_AUTO_MERGE_THRESHOLD, MEMORY_NEAR_DUP_THRESHOLD


class MemoryLifecycleMixin:
    def _find_memory(self, memory_id: str) -> dict | None:
        return next(
            (memory for memory in self.memories if memory.get("id") == memory_id),
            None,
        )

    def _archive_entity_conflicts(
        self,
        *,
        scope: str,
        entity_type: str,
        entity_key: str,
        entity_value: str,
        memory_type: str,
        replacement_id: str,
        now: float,
    ) -> list[str]:
        if (
            memory_type != "entity"
            or not entity_type
            or not entity_key
            or not entity_value
        ):
            return []

        superseded_ids = []
        for memory in self.memories:
            if memory.get("id") == replacement_id:
                continue
            if memory.get("status") != "active":
                continue
            if memory.get("memory_type") != "entity":
                continue
            if memory.get("scope", "global") != scope:
                continue
            if memory.get("entity_type") != entity_type:
                continue
            if memory.get("entity_key") != entity_key:
                continue
            if memory.get("entity_value") == entity_value:
                continue

            memory["status"] = "archived"
            memory["updated_at"] = now
            memory["version"] = memory.get("version", 1) + 1
            memory["superseded_by"] = replacement_id
            superseded_ids.append(memory["id"])
        return superseded_ids

    def _merge_record(self, target: dict, source: dict, now: float) -> dict:
        target["importance"] = max(
            target.get("importance", 3),
            source.get("importance", 3),
        )
        target["confidence"] = max(
            target.get("confidence", 0.8),
            source.get("confidence", 0.8),
        )
        target["tags"] = _normalize_tags(
            list(target.get("tags", [])) + list(source.get("tags", []))
        )
        target["supersedes"] = _normalize_tags(
            list(target.get("supersedes", []))
            + list(source.get("supersedes", []))
            + [source["id"]]
        )
        if target.get("source") == "legacy" and source.get("source"):
            target["source"] = source["source"]
        for field_name in ("entity_type", "entity_key", "entity_value"):
            if not target.get(field_name) and source.get(field_name):
                target[field_name] = source[field_name]

        target["updated_at"] = now
        target["version"] = target.get("version", 1) + 1
        source["status"] = "archived"
        source["superseded_by"] = target["id"]
        source["updated_at"] = now
        source["version"] = source.get("version", 1) + 1
        self._save()
        return target

    def get(self, memory_id: str) -> dict | None:
        with _memory_lock:
            self._reload_if_changed()
            memory = self._find_memory(memory_id)
            return dict(memory) if memory is not None else None

    def update(
        self,
        memory_id: str,
        *,
        content: str | None = None,
        importance: int | None = None,
        category: str | None = None,
        memory_type: str | None = None,
        entity_type: str | None = None,
        entity_key: str | None = None,
        entity_value: str | None = None,
        tags: list[str] | str | None = None,
        scope: str | None = None,
        confidence: float | None = None,
    ) -> dict:
        with _memory_lock:
            self._reload_if_changed()
            memory = self._find_memory(memory_id)
            if memory is None:
                raise ValueError(f"Memory not found: {memory_id}")

            updated = dict(memory)
            if content is not None:
                normalized_content = normalize_content(content)
                if not normalized_content:
                    raise ValueError("Memory content cannot be empty")
                updated["content"] = normalized_content
                updated["content_hash"] = content_hash(normalized_content)
            if importance is not None:
                updated["importance"] = _validate_importance(importance)
            if confidence is not None:
                updated["confidence"] = _validate_confidence(confidence)
            if memory_type is not None:
                updated["memory_type"] = _validate_memory_type(memory_type)
            if category is not None:
                updated["category"] = str(category).strip() or "general"
            if entity_type is not None:
                updated["entity_type"] = str(entity_type).strip()
            if entity_key is not None:
                updated["entity_key"] = str(entity_key).strip()
            if entity_value is not None:
                updated["entity_value"] = str(entity_value).strip()
            if tags is not None:
                updated["tags"] = _normalize_tags(tags)
            if scope is not None:
                updated["scope"] = str(scope).strip() or "global"

            now = time.time()
            if memory.get("status") == "active":
                duplicate = next(
                    (
                        candidate
                        for candidate in self.memories
                        if candidate.get("id") != memory_id
                        and candidate.get("status") == "active"
                        and candidate.get("scope", "global")
                        == updated.get("scope", "global")
                        and candidate.get("content_hash") == updated.get("content_hash")
                    ),
                    None,
                )
                if duplicate is not None:
                    return self._merge_record(duplicate, memory, now)

                superseded_ids = self._archive_entity_conflicts(
                    scope=updated.get("scope", "global"),
                    entity_type=updated.get("entity_type", ""),
                    entity_key=updated.get("entity_key", ""),
                    entity_value=updated.get("entity_value", ""),
                    memory_type=updated.get("memory_type", "semantic"),
                    replacement_id=memory_id,
                    now=now,
                )
                if superseded_ids:
                    updated["supersedes"] = _normalize_tags(
                        list(updated.get("supersedes", [])) + superseded_ids
                    )

            updated["updated_at"] = now
            updated["version"] = updated.get("version", 1) + 1
            memory.clear()
            memory.update(updated)
            self._save()
            return memory

    def archive(self, memory_id: str) -> dict:
        with _memory_lock:
            self._reload_if_changed()
            memory = self._find_memory(memory_id)
            if memory is None:
                raise ValueError(f"Memory not found: {memory_id}")
            if memory.get("status") != "archived":
                memory["status"] = "archived"
                memory["updated_at"] = time.time()
                memory["version"] = memory.get("version", 1) + 1
                self._save()
            return memory

    def delete(self, memory_id: str) -> dict:
        """Soft-delete a memory while keeping the record for audit/recovery."""
        with _memory_lock:
            self._reload_if_changed()
            memory = self._find_memory(memory_id)
            if memory is None:
                raise ValueError(f"Memory not found: {memory_id}")
            if memory.get("status") != "deleted":
                memory["status"] = "deleted"
                memory["updated_at"] = time.time()
                memory["version"] = memory.get("version", 1) + 1
                self._save()
            return memory

    def restore(self, memory_id: str) -> dict:
        with _memory_lock:
            self._reload_if_changed()
            memory = self._find_memory(memory_id)
            if memory is None:
                raise ValueError(f"Memory not found: {memory_id}")

            duplicate = next(
                (
                    candidate
                    for candidate in self.memories
                    if candidate.get("id") != memory_id
                    and candidate.get("status") == "active"
                    and candidate.get("scope", "global")
                    == memory.get("scope", "global")
                    and candidate.get("content_hash") == memory.get("content_hash")
                ),
                None,
            )
            if duplicate is not None:
                now = time.time()
                return self._merge_record(duplicate, memory, now)

            now = time.time()
            superseded_ids = self._archive_entity_conflicts(
                scope=memory.get("scope", "global"),
                entity_type=memory.get("entity_type", ""),
                entity_key=memory.get("entity_key", ""),
                entity_value=memory.get("entity_value", ""),
                memory_type=memory.get("memory_type", "semantic"),
                replacement_id=memory_id,
                now=now,
            )
            if superseded_ids:
                memory["supersedes"] = _normalize_tags(
                    list(memory.get("supersedes", [])) + superseded_ids
                )
            memory["status"] = "active"
            memory["superseded_by"] = ""
            memory["updated_at"] = now
            memory["version"] = memory.get("version", 1) + 1
            self._save()
            return memory

    def approve(self, memory_id: str) -> dict:
        """Promote a candidate memory to active after review."""
        with _memory_lock:
            self._reload_if_changed()
            memory = self._find_memory(memory_id)
            if memory is None:
                raise ValueError(f"Memory not found: {memory_id}")
            if memory.get("status") != "candidate":
                raise ValueError(f"Memory {memory_id} is not a candidate")
            return self.restore(memory_id)

    def add(
        self,
        content: str,
        importance: int = 3,
        category: str = "general",
        *,
        memory_type: str = "semantic",
        entity_type: str = "",
        entity_key: str = "",
        entity_value: str = "",
        tags: list[str] | str | None = None,
        scope: str = "global",
        owner_id: str = "",
        session_id: str = "",
        run_id: str = "",
        source: str = "agent",
        confidence: float = 0.8,
    ):
        """Add an active memory, updating an exact duplicate in the same scope."""
        normalized_content = normalize_content(content)
        if not normalized_content:
            raise ValueError("Memory content cannot be empty")

        importance_value = _validate_importance(importance)
        confidence_value = _validate_confidence(confidence)
        memory_type_value = _validate_memory_type(memory_type)

        scope_value = str(scope or "global").strip() or "global"
        category_value = str(category or "general").strip() or "general"
        source_value = str(source or "agent").strip() or "agent"
        digest = content_hash(normalized_content)

        with _memory_lock:
            self._reload_if_changed()

            duplicate = next(
                (
                    memory
                    for memory in self.memories
                    if memory.get("status") in {"active", "candidate"}
                    and memory.get("scope", "global") == scope_value
                    and memory.get("content_hash") == digest
                ),
                None,
            )
            if duplicate is not None:
                now = time.time()
                duplicate["importance"] = max(
                    duplicate.get("importance", 3),
                    importance_value,
                )
                duplicate["confidence"] = max(
                    duplicate.get("confidence", 0.8),
                    confidence_value,
                )
                duplicate["tags"] = _normalize_tags(
                    list(duplicate.get("tags", [])) + _normalize_tags(tags)
                )
                duplicate["updated_at"] = now
                duplicate["version"] = duplicate.get("version", 1) + 1
                if not duplicate.get("entity_type") and entity_type:
                    duplicate["entity_type"] = str(entity_type).strip()
                if not duplicate.get("entity_key") and entity_key:
                    duplicate["entity_key"] = str(entity_key).strip()
                if not duplicate.get("entity_value") and entity_value:
                    duplicate["entity_value"] = str(entity_value).strip()
                self._save()
                return duplicate

            now = time.time()
            superseded_ids = self._archive_entity_conflicts(
                scope=scope_value,
                entity_type=str(entity_type or "").strip(),
                entity_key=str(entity_key or "").strip(),
                entity_value=str(entity_value or "").strip(),
                memory_type=memory_type_value,
                replacement_id="",
                now=now,
            )
            near_duplicate, near_similarity = self._best_near_duplicate(
                normalized_content,
                scope=scope_value,
                memory_type=memory_type_value,
                entity_type=str(entity_type or "").strip(),
                entity_key=str(entity_key or "").strip(),
            )
            record = MemoryRecord(
                id=f"mem_{uuid.uuid4().hex}",
                content=normalized_content,
                memory_type=memory_type_value,
                entity_type=str(entity_type or "").strip(),
                entity_key=str(entity_key or "").strip(),
                entity_value=str(entity_value or "").strip(),
                category=category_value,
                tags=_normalize_tags(tags),
                scope=scope_value,
                owner_id=str(owner_id or "").strip(),
                session_id=str(session_id or "").strip(),
                run_id=str(run_id or "").strip(),
                source=source_value,
                confidence=confidence_value,
                importance=importance_value,
                status="active",
                created_at=now,
                updated_at=now,
                last_accessed_at=0.0,
                access_count=0,
                content_hash=digest,
                version=1,
                supersedes=superseded_ids,
            )
            memory = record.to_dict()
            for memory_id in superseded_ids:
                old_memory = self._find_memory(memory_id)
                if old_memory is not None:
                    old_memory["superseded_by"] = record.id
            self.memories.append(memory)
            if (
                near_duplicate is not None
                and near_similarity >= MEMORY_AUTO_MERGE_THRESHOLD
            ):
                return self._merge_record(near_duplicate, memory, now)
            if (
                near_duplicate is not None
                and near_similarity >= MEMORY_NEAR_DUP_THRESHOLD
            ):
                memory["status"] = "candidate"
            self._save()
            return memory

    def consolidate(self) -> str:
        """Archive the oldest records into one deterministic summary."""
        with _memory_lock:
            self._reload_if_changed()
            active = [
                memory
                for memory in self.memories
                if memory.get("status", "active") == "active"
            ]
            if len(active) < 10:
                return "Not enough memories to consolidate"

            old_memories = sorted(active, key=lambda m: m["created_at"])[:5]
            contents = [memory["content"] for memory in old_memories]
            summary = "Consolidated: " + "; ".join(contents[:3])
            old_ids = {memory["id"] for memory in old_memories}
            now = time.time()

            for memory in self.memories:
                if memory["id"] in old_ids:
                    memory["status"] = "archived"
                    memory["updated_at"] = now
                    memory["version"] = memory.get("version", 1) + 1

            scopes = {memory.get("scope", "global") for memory in old_memories}
            scope = scopes.pop() if len(scopes) == 1 else "global"
            record = MemoryRecord(
                id=f"mem_{uuid.uuid4().hex}",
                content=summary,
                memory_type="semantic",
                category="consolidated",
                tags=[],
                scope=scope,
                source="consolidation",
                confidence=0.7,
                importance=2,
                status="active",
                created_at=now,
                updated_at=now,
                content_hash=content_hash(summary),
                version=1,
            )
            self.memories.append(record.to_dict())
            self._save()
            return f"Consolidated {len(old_memories)} old memories"

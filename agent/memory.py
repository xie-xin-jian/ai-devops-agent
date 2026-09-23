import hashlib
import json
import math
import re
import threading
import time
import unicodedata
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from agent.config import MEMORY_DIR, MEMORY_MIN_SCORE, MEMORY_TOP_K
from agent.storage import atomic_write_text

MEMORY_DIR.mkdir(parents=True, exist_ok=True)
_memory_lock = threading.RLock()

VALID_MEMORY_TYPES = {"entity", "semantic", "episodic", "procedural"}
VALID_STATUSES = {"active", "archived", "candidate", "deleted"}
_LATIN_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.:/-]*")
_CJK_SEQUENCE_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")


def normalize_content(content: str) -> str:
    """Normalize content for stable exact-duplicate detection."""
    normalized = unicodedata.normalize("NFKC", str(content))
    return re.sub(r"\s+", " ", normalized).strip()


def content_hash(content: str) -> str:
    normalized = normalize_content(content).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def tokenize_text(text: str) -> set[str]:
    """Tokenize Latin terms and use CJK character bigrams for matching."""
    normalized = normalize_content(text).lower()
    tokens = set(_LATIN_TOKEN_RE.findall(normalized))

    for sequence in _CJK_SEQUENCE_RE.findall(normalized):
        tokens.add(sequence)
        if len(sequence) == 1:
            tokens.add(sequence)
            continue
        for index in range(len(sequence) - 1):
            tokens.add(sequence[index:index + 2])

    return {token for token in tokens if token}


def _keyword_score(query: str, query_tokens: set[str], content: str) -> float:
    if not query_tokens:
        return 0.0

    content_lower = normalize_content(content).lower()
    query_lower = normalize_content(query).lower()
    phrase_match = 1.0 if query_lower and query_lower in content_lower else 0.0
    content_tokens = tokenize_text(content)
    overlap = len(query_tokens & content_tokens) / len(query_tokens)
    return min(1.0, phrase_match * 0.35 + overlap * 0.65)


def _metadata_score(
    query: str,
    query_tokens: set[str],
    memory: dict,
) -> float:
    query_lower = normalize_content(query).lower()
    entity_values = {
        str(memory.get("entity_type", "")).lower(),
        str(memory.get("entity_key", "")).lower(),
        str(memory.get("entity_value", "")).lower(),
    }
    entity_values.discard("")
    entity_match = 1.0 if any(
        value in query_lower or value in query_tokens
        for value in entity_values
    ) else 0.0

    tags = {
        str(tag).lower()
        for tag in memory.get("tags", [])
        if str(tag).strip()
    }
    tag_match = 1.0 if any(
        tag in query_lower or tag in query_tokens
        for tag in tags
    ) else 0.0

    category = str(memory.get("category", "")).lower()
    category_match = 1.0 if category and (
        category in query_lower or category in query_tokens
    ) else 0.0

    return min(1.0, entity_match * 0.6 + tag_match * 0.3 + category_match * 0.1)


def _recency_score(timestamp: float) -> float:
    if timestamp <= 0:
        return 0.0
    age_days = max(0.0, (time.time() - timestamp) / 86400)
    return max(0.0, min(1.0, 2.718281828 ** (-age_days / 30)))


def _access_score(access_count: int) -> float:
    if access_count <= 0:
        return 0.0
    return min(1.0, math.log1p(access_count) / 5)


def _memory_score(
    query: str,
    query_tokens: set[str],
    memory: dict,
) -> tuple[float, float]:
    lexical = _keyword_score(query, query_tokens, memory.get("content", ""))
    metadata = _metadata_score(query, query_tokens, memory)
    if lexical == 0.0 and metadata == 0.0:
        return 0.0, 0.0

    importance = max(0.0, min(1.0, (memory.get("importance", 3) - 1) / 4))
    confidence = max(0.0, min(1.0, float(memory.get("confidence", 0.8))))
    recency = _recency_score(
        float(memory.get("updated_at") or memory.get("created_at") or 0.0)
    )
    access = _access_score(int(memory.get("access_count", 0)))

    score = (
        lexical * 0.50
        + metadata * 0.25
        + importance * 0.10
        + confidence * 0.05
        + recency * 0.05
        + access * 0.05
    )
    return score, lexical + metadata


def _normalize_tags(tags) -> list[str]:
    if tags is None:
        return []
    if isinstance(tags, str):
        tags = tags.split(",")
    if not isinstance(tags, list):
        return []

    normalized = []
    seen = set()
    for tag in tags:
        value = str(tag).strip()
        if value and value not in seen:
            normalized.append(value)
            seen.add(value)
    return normalized


def _legacy_int(value, default: int, minimum: int, maximum: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(result, maximum))


def _legacy_float(value, default: float, minimum: float, maximum: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(result, maximum))


def _validate_importance(value) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("importance must be an integer from 1 to 5") from exc
    if not 1 <= result <= 5:
        raise ValueError("importance must be between 1 and 5")
    return result


def _validate_confidence(value) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence must be between 0 and 1") from exc
    if not 0.0 <= result <= 1.0:
        raise ValueError("confidence must be between 0 and 1")
    return result


def _validate_memory_type(value: str) -> str:
    result = str(value or "semantic").strip().lower()
    if result not in VALID_MEMORY_TYPES:
        raise ValueError(f"memory_type must be one of {sorted(VALID_MEMORY_TYPES)}")
    return result


@dataclass
class MemoryRecord:
    id: str
    content: str
    memory_type: str = "semantic"
    entity_type: str = ""
    entity_key: str = ""
    entity_value: str = ""
    category: str = "general"
    tags: list[str] = field(default_factory=list)
    scope: str = "global"
    source: str = "agent"
    confidence: float = 0.8
    importance: int = 3
    status: str = "active"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_accessed_at: float = 0.0
    access_count: int = 0
    content_hash: str = ""
    version: int = 1
    supersedes: list[str] = field(default_factory=list)
    superseded_by: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["content"] = normalize_content(self.content)
        data["tags"] = _normalize_tags(self.tags)
        data["content_hash"] = self.content_hash or content_hash(self.content)
        data["supersedes"] = _normalize_tags(self.supersedes)
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryRecord":
        """Load legacy records and fill fields introduced by newer versions."""
        content = normalize_content(data.get("content", ""))
        if not content:
            raise ValueError("Memory content cannot be empty")

        created_at = float(data.get("created_at") or time.time())
        updated_at = float(data.get("updated_at") or created_at)
        memory_type = str(data.get("memory_type") or "semantic").strip().lower()
        if memory_type not in VALID_MEMORY_TYPES:
            memory_type = "semantic"

        status = str(data.get("status") or "active").strip().lower()
        if status not in VALID_STATUSES:
            status = "active"

        return cls(
            id=str(data.get("id") or f"mem_{uuid.uuid4().hex}"),
            content=content,
            memory_type=memory_type,
            entity_type=str(data.get("entity_type") or "").strip(),
            entity_key=str(data.get("entity_key") or "").strip(),
            entity_value=str(data.get("entity_value") or "").strip(),
            category=str(data.get("category") or "general").strip() or "general",
            tags=_normalize_tags(data.get("tags")),
            scope=str(data.get("scope") or "global").strip() or "global",
            source=str(data.get("source") or "legacy").strip() or "legacy",
            confidence=_legacy_float(data.get("confidence"), 0.8, 0.0, 1.0),
            importance=_legacy_int(data.get("importance"), 3, 1, 5),
            status=status,
            created_at=created_at,
            updated_at=updated_at,
            last_accessed_at=float(data.get("last_accessed_at") or 0.0),
            access_count=max(0, _legacy_int(data.get("access_count"), 0, 0, 2**31 - 1)),
            content_hash=str(data.get("content_hash") or content_hash(content)),
            version=max(1, _legacy_int(data.get("version"), 1, 1, 2**31 - 1)),
            supersedes=_normalize_tags(data.get("supersedes")),
            superseded_by=str(data.get("superseded_by") or "").strip(),
        )


class MemorySystem:
    def __init__(self):
        self.memories: list[dict] = []
        self._file_state: tuple[int, int] | None = None
        self._load()

    def _path(self) -> Path:
        return MEMORY_DIR / "memories.jsonl"

    def _load(self):
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
            json.dumps(m, ensure_ascii=False) + "\n"
            for m in self.memories
        )
        atomic_write_text(path, content)
        stat = path.stat()
        self._file_state = (stat.st_mtime_ns, stat.st_size)

    def _reload_if_changed(self):
        path = self._path()
        if not path.exists():
            self.memories = []
            self._file_state = None
            return
        stat = path.stat()
        current_state = (stat.st_mtime_ns, stat.st_size)
        if current_state != self._file_state:
            self._load()

    def _find_memory(self, memory_id: str) -> dict | None:
        return next(
            (
                memory
                for memory in self.memories
                if memory.get("id") == memory_id
            ),
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
                        and candidate.get("content_hash")
                        == updated.get("content_hash")
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
                    and candidate.get("content_hash")
                    == memory.get("content_hash")
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
                    if memory.get("status") == "active"
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
            self._save()
            return memory

    def select(
        self,
        query: str,
        top_k: int | None = None,
        *,
        scope: str | None = None,
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

    def format_relevant(
        self,
        query: str,
        *,
        scope: str | None = None,
        memory_type: str | None = None,
    ) -> str:
        """Select and format relevant memories."""
        selected = self.select(
            query,
            scope=scope,
            memory_type=memory_type,
        )
        return self.extract(selected)

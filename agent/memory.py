import hashlib
import json
import re
import threading
import time
import unicodedata
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from agent.config import MEMORY_DIR
from agent.storage import atomic_write_text

MEMORY_DIR.mkdir(parents=True, exist_ok=True)
_memory_lock = threading.RLock()

VALID_MEMORY_TYPES = {"entity", "semantic", "episodic", "procedural"}
VALID_STATUSES = {"active", "archived", "candidate"}


def normalize_content(content: str) -> str:
    """Normalize content for stable exact-duplicate detection."""
    normalized = unicodedata.normalize("NFKC", str(content))
    return re.sub(r"\s+", " ", normalized).strip()


def content_hash(content: str) -> str:
    normalized = normalize_content(content).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


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

    def to_dict(self) -> dict:
        data = asdict(self)
        data["content"] = normalize_content(self.content)
        data["tags"] = _normalize_tags(self.tags)
        data["content_hash"] = self.content_hash or content_hash(self.content)
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

        try:
            importance_value = int(importance)
        except (TypeError, ValueError) as exc:
            raise ValueError("importance must be an integer from 1 to 5") from exc
        if not 1 <= importance_value <= 5:
            raise ValueError("importance must be between 1 and 5")

        try:
            confidence_value = float(confidence)
        except (TypeError, ValueError) as exc:
            raise ValueError("confidence must be between 0 and 1") from exc
        if not 0.0 <= confidence_value <= 1.0:
            raise ValueError("confidence must be between 0 and 1")

        memory_type_value = str(memory_type or "semantic").strip().lower()
        if memory_type_value not in VALID_MEMORY_TYPES:
            raise ValueError(
                f"memory_type must be one of {sorted(VALID_MEMORY_TYPES)}"
            )

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
            )
            memory = record.to_dict()
            self.memories.append(memory)
            self._save()
            return memory

    def select(
        self,
        query: str,
        top_k: int = 5,
        *,
        scope: str | None = None,
        memory_type: str | None = None,
        status: str = "active",
    ) -> list[dict]:
        """Select memories with lightweight keyword and metadata scoring."""
        with _memory_lock:
            self._reload_if_changed()
            query_lower = normalize_content(query).lower()
            scored = []

            for memory in self.memories:
                if status and memory.get("status", "active") != status:
                    continue
                if scope and memory.get("scope", "global") != scope:
                    continue
                if memory_type and memory.get("memory_type") != memory_type:
                    continue

                score = 0
                content_lower = str(memory.get("content", "")).lower()
                for word in query_lower.split():
                    if word and word in content_lower:
                        score += 1

                for tag in memory.get("tags", []):
                    if str(tag).lower() in query_lower:
                        score += 1

                score += memory.get("importance", 3) * 0.5
                score += memory.get("access_count", 0) * 0.1
                if score > 0:
                    scored.append((score, memory))

            scored.sort(key=lambda item: item[0], reverse=True)
            result = [memory for _, memory in scored[:top_k]]
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
                f"({memory.get('memory_type', 'semantic')}, "
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

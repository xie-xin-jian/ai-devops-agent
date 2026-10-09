"""Memory models, validation, hashing, and scoring helpers."""

from __future__ import annotations

import hashlib
import math
import re
import time
import unicodedata
import uuid
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher

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
            tokens.add(sequence[index : index + 2])

    return {token for token in tokens if token}


def similarity_score(left: str, right: str) -> float:
    """Estimate lexical similarity without requiring an embedding model."""
    left_normalized = normalize_content(left).lower()
    right_normalized = normalize_content(right).lower()
    if not left_normalized or not right_normalized:
        return 0.0

    left_tokens = tokenize_text(left_normalized)
    right_tokens = tokenize_text(right_normalized)
    union = left_tokens | right_tokens
    token_similarity = len(left_tokens & right_tokens) / len(union) if union else 0.0
    sequence_similarity = SequenceMatcher(
        None,
        left_normalized,
        right_normalized,
    ).ratio()
    return min(
        1.0,
        token_similarity * 0.65 + sequence_similarity * 0.35,
    )


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
    entity_match = (
        1.0
        if any(value in query_lower or value in query_tokens for value in entity_values)
        else 0.0
    )

    tags = {str(tag).lower() for tag in memory.get("tags", []) if str(tag).strip()}
    tag_match = (
        1.0 if any(tag in query_lower or tag in query_tokens for tag in tags) else 0.0
    )

    category = str(memory.get("category", "")).lower()
    category_match = (
        1.0
        if category and (category in query_lower or category in query_tokens)
        else 0.0
    )

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
    owner_id: str = ""
    session_id: str = ""
    run_id: str = ""
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
            owner_id=str(data.get("owner_id") or "").strip(),
            session_id=str(data.get("session_id") or "").strip(),
            run_id=str(data.get("run_id") or "").strip(),
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

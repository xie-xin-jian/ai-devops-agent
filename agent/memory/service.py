"""Public MemorySystem facade."""

from __future__ import annotations

from agent.memory.lifecycle import MemoryLifecycleMixin
from agent.memory.models import (
    MemoryRecord,
    content_hash,
    normalize_content,
    similarity_score,
    tokenize_text,
)
from agent.memory.retrieval import MemoryRetrievalMixin
from agent.memory.store import MemoryStoreMixin


class MemorySystem(
    MemoryStoreMixin,
    MemoryRetrievalMixin,
    MemoryLifecycleMixin,
):
    pass


__all__ = [
    "MemoryRecord",
    "MemorySystem",
    "content_hash",
    "normalize_content",
    "similarity_score",
    "tokenize_text",
]

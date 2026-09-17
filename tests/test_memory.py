"""Memory persistence behavior tests."""

import json

import pytest

from agent import memory


def test_memory_select_does_not_rewrite_file(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_DIR", tmp_path)
    system = memory.MemorySystem()
    system.add("remember this")

    write_calls = []
    monkeypatch.setattr(
        memory,
        "atomic_write_text",
        lambda *args, **kwargs: write_calls.append((args, kwargs)),
    )

    system.select("remember")
    assert write_calls == []


def test_legacy_memory_is_normalized(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_DIR", tmp_path)
    path = tmp_path / "memories.jsonl"
    path.write_text(
        json.dumps({
            "id": "mem_legacy",
            "content": "  User prefers   Python  ",
            "importance": 4,
            "category": "preference",
            "created_at": 100.0,
            "access_count": 2,
        }) + "\n",
        encoding="utf-8",
    )

    system = memory.MemorySystem()
    record = system.memories[0]

    assert record["content"] == "User prefers Python"
    assert record["memory_type"] == "semantic"
    assert record["scope"] == "global"
    assert record["source"] == "legacy"
    assert record["status"] == "active"
    assert record["content_hash"] == memory.content_hash("User prefers Python")
    assert record["access_count"] == 2


def test_exact_duplicate_updates_existing_memory(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_DIR", tmp_path)
    system = memory.MemorySystem()

    first = system.add(
        "Server A uses Nginx",
        importance=3,
        tags=["server-a"],
    )
    second = system.add(
        "  Server A   uses Nginx ",
        importance=5,
        tags=["nginx"],
    )

    assert second["id"] == first["id"]
    assert len(system.memories) == 1
    assert second["importance"] == 5
    assert set(second["tags"]) == {"server-a", "nginx"}
    assert second["version"] == 2


def test_scope_filter_prevents_cross_scope_recall(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_DIR", tmp_path)
    system = memory.MemorySystem()

    system.add("Use Nginx", scope="project:a")
    system.add("Use Apache", scope="project:b")

    selected = system.select("Nginx", scope="project:a")

    assert [item["content"] for item in selected] == ["Use Nginx"]


def test_invalid_importance_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_DIR", tmp_path)
    system = memory.MemorySystem()

    with pytest.raises(ValueError, match="importance"):
        system.add("Invalid memory", importance=9)

    assert system.memories == []

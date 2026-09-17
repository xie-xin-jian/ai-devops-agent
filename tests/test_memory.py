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


def test_update_memory_changes_fields_and_version(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_DIR", tmp_path)
    system = memory.MemorySystem()
    record = system.add("Server A uses Nginx")

    updated = system.update(
        record["id"],
        importance=5,
        tags=["server-a", "nginx"],
        confidence=0.95,
    )

    assert updated["importance"] == 5
    assert updated["tags"] == ["server-a", "nginx"]
    assert updated["confidence"] == 0.95
    assert updated["version"] == 2
    assert system.get(record["id"])["importance"] == 5


def test_update_to_existing_content_merges_records(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_DIR", tmp_path)
    system = memory.MemorySystem()
    first = system.add("Server A uses Nginx", tags=["nginx"])
    second = system.add("Server A listens on port 80", tags=["port-80"])

    merged = system.update(second["id"], content=first["content"])

    assert merged["id"] == first["id"]
    assert set(merged["tags"]) == {"nginx", "port-80"}
    assert system.get(second["id"])["status"] == "archived"
    assert system.get(second["id"])["superseded_by"] == first["id"]


def test_archive_and_restore_memory(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_DIR", tmp_path)
    system = memory.MemorySystem()
    record = system.add("Archive this memory")

    archived = system.archive(record["id"])
    assert archived["status"] == "archived"
    assert system.select("Archive") == []

    restored = system.restore(record["id"])
    assert restored["status"] == "active"
    assert system.select("Archive")[0]["id"] == record["id"]


def test_delete_memory_is_soft_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_DIR", tmp_path)
    system = memory.MemorySystem()
    record = system.add("Delete this memory")

    deleted = system.delete(record["id"])

    assert deleted["status"] == "deleted"
    assert system.get(record["id"]) is not None
    assert system.select("Delete") == []


def test_entity_conflict_archives_old_value(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_DIR", tmp_path)
    system = memory.MemorySystem()
    old = system.add(
        "Server A uses Nginx",
        memory_type="entity",
        entity_type="server",
        entity_key="server-a",
        entity_value="nginx",
    )
    new = system.add(
        "Server A uses Apache",
        memory_type="entity",
        entity_type="server",
        entity_key="server-a",
        entity_value="apache",
    )

    assert system.get(old["id"])["status"] == "archived"
    assert system.get(old["id"])["superseded_by"] == new["id"]
    assert new["supersedes"] == [old["id"]]
    assert [item["id"] for item in system.select("Server A")] == [new["id"]]


def test_updating_archived_entity_does_not_archive_active_value(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(memory, "MEMORY_DIR", tmp_path)
    system = memory.MemorySystem()
    archived = system.add(
        "Server A uses Nginx",
        memory_type="entity",
        entity_type="server",
        entity_key="server-a",
        entity_value="nginx",
    )
    system.archive(archived["id"])
    active = system.add(
        "Server A uses Apache",
        memory_type="entity",
        entity_type="server",
        entity_key="server-a",
        entity_value="apache",
    )

    system.update(
        archived["id"],
        entity_value="nginx-old",
    )

    assert system.get(active["id"])["status"] == "active"

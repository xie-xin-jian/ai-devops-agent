"""Near-duplicate and access persistence tests."""

from agent import memory


def test_similarity_score_detects_close_text():
    assert memory.similarity_score(
        "Server A uses Nginx",
        "Server A uses Nginx!",
    ) >= 0.95


def test_high_similarity_memory_is_merged(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_DIR", tmp_path)
    system = memory.MemorySystem()
    first = system.add("Server A uses Nginx")

    merged = system.add("Server A uses Nginx!")

    assert merged["id"] == first["id"]
    archived = [
        item
        for item in system.memories
        if item["status"] == "archived"
    ]
    assert len(archived) == 1
    assert archived[0]["id"] in merged["supersedes"]


def test_medium_similarity_memory_becomes_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_DIR", tmp_path)
    monkeypatch.setattr(memory, "MEMORY_NEAR_DUP_THRESHOLD", 0.60)
    monkeypatch.setattr(memory, "MEMORY_AUTO_MERGE_THRESHOLD", 0.99)
    system = memory.MemorySystem()
    system.add("Server A uses Nginx")

    candidate = system.add("Server A uses Apache")

    assert candidate["status"] == "candidate"
    assert all(
        item["id"] != candidate["id"]
        for item in system.select("Server A uses Apache")
    )


def test_access_counts_are_persisted_in_batch(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_DIR", tmp_path)
    system = memory.MemorySystem()
    record = system.add("remember this")

    system.select("remember")
    system.select("remember")
    assert system.flush_access_stats(force=True) == 1

    reloaded = memory.MemorySystem()
    assert reloaded.get(record["id"])["access_count"] == 2


def test_access_counts_are_not_double_counted_after_save(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(memory, "MEMORY_DIR", tmp_path)
    system = memory.MemorySystem()
    record = system.add("remember this")

    system.select("remember")
    system.add("another memory")

    reloaded = memory.MemorySystem()
    assert reloaded.get(record["id"])["access_count"] == 1

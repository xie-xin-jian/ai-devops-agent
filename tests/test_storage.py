"""Atomic local persistence tests."""

import json
from concurrent.futures import ThreadPoolExecutor

from agent import memory
from agent.storage import atomic_write_json


def test_atomic_write_json_survives_concurrent_writers(tmp_path):
    target = tmp_path / "state.json"

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(
            lambda index: atomic_write_json(target, {"writer": index}),
            range(40),
        ))

    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["writer"] in range(40)
    assert list(tmp_path.glob(".state.json.*.tmp")) == []


def test_memory_instances_do_not_overwrite_each_other(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_DIR", tmp_path)
    first = memory.MemorySystem()
    second = memory.MemorySystem()

    first.add("first memory")
    second.add("second memory")

    reloaded = memory.MemorySystem()
    contents = {item["content"] for item in reloaded.memories}
    assert contents == {"first memory", "second memory"}

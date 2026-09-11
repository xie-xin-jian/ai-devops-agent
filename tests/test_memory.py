"""Memory persistence behavior tests."""

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

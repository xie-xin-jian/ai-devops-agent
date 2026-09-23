"""Retrieval quality regression tests for long-term memory."""

from agent import comprehensive, memory


def _build_memory_system(tmp_path, monkeypatch) -> memory.MemorySystem:
    monkeypatch.setattr(memory, "MEMORY_DIR", tmp_path)
    system = memory.MemorySystem()
    system.add(
        "Nginx 502，上游 PHP-FPM 未监听",
        importance=5,
        category="incident",
        tags=["nginx", "502", "php-fpm"],
        scope="project:a",
        confidence=0.95,
    )
    system.add(
        "CPU 使用率达到 95%，负载过高",
        importance=4,
        category="performance",
        tags=["cpu", "load"],
        scope="project:a",
        confidence=0.9,
    )
    system.add(
        "根分区磁盘使用率过高，需要清理日志",
        importance=4,
        category="maintenance",
        tags=["disk", "cleanup"],
        scope="project:a",
        confidence=0.9,
    )
    system.add(
        "生产服务器 A 使用 Nginx",
        importance=4,
        memory_type="entity",
        entity_type="server",
        entity_key="server-a",
        entity_value="nginx",
        tags=["server-a", "nginx"],
        scope="project:a",
    )
    system.add(
        "另一个项目使用 Apache",
        importance=5,
        tags=["apache"],
        scope="project:b",
    )
    return system


def test_chinese_text_uses_character_bigrams():
    tokens = memory.tokenize_text("服务器A端口被占用")

    assert {"服务", "务器", "端口", "口被", "被占", "占用"} <= tokens


def test_retrieval_matches_relevant_memories(tmp_path, monkeypatch):
    system = _build_memory_system(tmp_path, monkeypatch)

    nginx = system.select("nginx 502", scope="project:a")
    php = system.select("PHP-FPM 未监听", scope="project:a")
    cpu = system.select("CPU 负载高", scope="project:a")
    disk = system.select("磁盘清理", scope="project:a")
    server = system.select("服务器 A Web 服务", scope="project:a")

    assert nginx and "Nginx" in nginx[0]["content"]
    assert php and "PHP-FPM" in php[0]["content"]
    assert cpu and "CPU" in cpu[0]["content"]
    assert disk and "磁盘" in disk[0]["content"]
    assert server and server[0]["entity_key"] == "server-a"


def test_irrelevant_query_returns_no_memories(tmp_path, monkeypatch):
    system = _build_memory_system(tmp_path, monkeypatch)

    assert system.select("今天天气", scope="project:a") == []


def test_retrieval_respects_scope(tmp_path, monkeypatch):
    system = _build_memory_system(tmp_path, monkeypatch)

    assert system.select("Apache", scope="project:a") == []
    assert system.select("Apache", scope="project:b")[0]["content"] == (
        "另一个项目使用 Apache"
    )


def test_relevance_gate_ignores_high_importance_noise(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "MEMORY_DIR", tmp_path)
    system = memory.MemorySystem()
    system.add(
        "公司年会在三月举办",
        importance=5,
        scope="project:a",
    )

    assert system.select("今天天气", scope="project:a") == []


def test_memory_tools_default_to_agent_scope(tmp_path, monkeypatch):
    system = _build_memory_system(tmp_path, monkeypatch)
    agent = object.__new__(comprehensive.ComprehensiveAgent)
    agent.memory = system
    agent.memory_scope = "project:a"
    agent.tools = []
    agent.handlers = {}
    agent._add_memory_tools()

    result = agent.handlers["search_memory"]("Apache")
    added = agent.handlers["add_memory"]("项目 A 的新记忆")

    assert "Apache" not in result
    assert added.startswith("Memory saved")
    assert any(
        item["content"] == "项目 A 的新记忆"
        and item["scope"] == "project:a"
        for item in system.memories
    )


def test_system_prompt_uses_agent_scope(tmp_path, monkeypatch):
    system = _build_memory_system(tmp_path, monkeypatch)
    agent = object.__new__(comprehensive.ComprehensiveAgent)
    agent.memory = system
    agent.memory_scope = "project:a"
    agent.tools = []
    agent._last_user_query = "Apache"

    prompt = agent._build_system_prompt()

    assert "另一个项目使用 Apache" not in prompt

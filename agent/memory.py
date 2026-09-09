import json
import time
from pathlib import Path
from agent.config import WORKDIR

MEMORY_DIR = WORKDIR / ".memory"
MEMORY_DIR.mkdir(exist_ok=True)


class MemorySystem:
    def __init__(self):
        self.memories: list[dict] = []
        self._load()

    def _path(self) -> Path:
        return MEMORY_DIR / "memories.jsonl"

    def _load(self):
        path = self._path()
        if not path.exists():
            return
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    self.memories.append(json.loads(line))

    def _save(self):
        path = self._path()
        with open(path, "w") as f:
            for m in self.memories:
                f.write(json.dumps(m) + "\n")

    def add(self, content: str, importance: int = 3, category: str = "general"):
        """添加一条记忆。importance: 1-5，数字越重要。"""
        mem = {
            "id": f"mem_{int(time.time())}_{len(self.memories):04d}",
            "content": content,
            "importance": importance,
            "category": category,
            "created_at": time.time(),
            "access_count": 0
        }
        self.memories.append(mem)
        self._save()
        return mem

    def select(self, query: str, top_k: int = 5) -> list[dict]:
        """第一层：选择 - 根据关键词匹配和重要性筛选相关记忆。"""
        query_lower = query.lower()
        scored = []
        for mem in self.memories:
            score = 0
            content_lower = mem["content"].lower()
            for word in query_lower.split():
                if word in content_lower:
                    score += 1
            score += mem["importance"] * 0.5
            score += mem.get("access_count", 0) * 0.1
            if score > 0:
                scored.append((score, mem))
        scored.sort(key=lambda x: x[0], reverse=True)
        result = [mem for _, mem in scored[:top_k]]
        for mem in result:
            mem["access_count"] = mem.get("access_count", 0) + 1
        self._save()
        return result

    def extract(self, memories: list[dict]) -> str:
        """第二层：提取 - 把选中的记忆格式化为文本。"""
        if not memories:
            return "(no relevant memories)"
        lines = []
        for i, mem in enumerate(memories, 1):
            lines.append(f"[{i}] ({mem['category']}, importance={mem['importance']}) {mem['content']}")
        return "\n".join(lines)

    def consolidate(self) -> str:
        """第三层：整合 - 定期整合旧记忆，压缩为摘要。"""
        if len(self.memories) < 10:
            return "Not enough memories to consolidate"
        old_memories = sorted(self.memories, key=lambda m: m["created_at"])[:5]
        contents = [m["content"] for m in old_memories]
        summary = "Consolidated: " + "; ".join(contents[:3])
        self.add(summary, importance=2, category="consolidated")
        old_ids = set(m["id"] for m in old_memories)
        self.memories = [m for m in self.memories if m["id"] not in old_ids]
        self._save()
        return f"Consolidated {len(old_memories)} old memories"

    def format_relevant(self, query: str) -> str:
        """选择 + 提取，返回格式化的相关记忆文本。"""
        selected = self.select(query)
        return self.extract(selected)

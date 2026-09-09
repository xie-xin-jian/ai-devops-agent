"""pytest 共享 fixture。"""
import pytest


@pytest.fixture
def isolated_tasks_dir(tmp_path, monkeypatch):
    """提供隔离的 TASKS_DIR，避免测试污染真实数据。"""
    tasks_dir = tmp_path / ".tasks"
    tasks_dir.mkdir()
    monkeypatch.setattr("agent.task_system.TASKS_DIR", tasks_dir)
    monkeypatch.setattr("agent.config.TASKS_DIR", tasks_dir)
    yield tasks_dir

"""pytest 共享 fixture。"""
import pytest


@pytest.fixture(autouse=True)
def isolated_persistence_config(monkeypatch):
    """Keep tests independent of the developer's ``.env``.

    ``agent.platform.config`` calls ``load_dotenv(override=True)``, so a local
    ``.env`` with ``PERSISTENCE_BACKEND=dual`` would otherwise turn every test
    into a dual-write test against a real database. Tests that need a mirror
    enable it explicitly in their own fixture.
    """
    monkeypatch.setattr("agent.platform.config.PERSISTENCE_BACKEND", "json")
    monkeypatch.setattr("agent.platform.config.DATABASE_URL", "")
    monkeypatch.setattr("agent.platform.config.PERSISTENCE_READ", "json")
    monkeypatch.setattr("agent.platform.config.PERSISTENCE_READ_DOMAINS", ())
    monkeypatch.setattr("agent.platform.config.PERSISTENCE_SHADOW", False)
    monkeypatch.setattr(
        "agent.platform.config.PERSISTENCE_CONSISTENCY_INTERVAL_SECONDS",
        0,
    )
    # Mirror counters and the failure cooldown are process state: reset them so
    # one test's simulated outage cannot defer another test's writes.
    monkeypatch.setattr("agent.platform.config.DB_FAILURE_COOLDOWN_SECONDS", 0)
    from agent.persistence import writer as mirror_writer

    mirror_writer.reset_mirror_stats()
    yield
    mirror_writer.reset_mirror_stats()


@pytest.fixture(autouse=True)
def isolated_audit_log(tmp_path, monkeypatch):
    """Keep test runs out of the real audit log.

    ``record_event`` writes to the configured audit path, so without this
    fixture every test run appends events to the developer's real data
    directory.
    """
    monkeypatch.setattr(
        "agent.observability.audit.AUDIT_EVENTS_PATH",
        tmp_path / "events.jsonl",
    )
    yield


@pytest.fixture
def isolated_tasks_dir(tmp_path, monkeypatch):
    """提供隔离的 TASKS_DIR，避免测试污染真实数据。"""
    tasks_dir = tmp_path / ".tasks"
    tasks_dir.mkdir()
    monkeypatch.setattr("agent.orchestration.tasks.TASKS_DIR", tasks_dir)
    monkeypatch.setattr("agent.platform.config.TASKS_DIR", tasks_dir)
    yield tasks_dir

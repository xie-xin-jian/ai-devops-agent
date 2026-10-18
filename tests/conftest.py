"""pytest 共享 fixture。"""

import pytest
import sqlalchemy
from sqlalchemy.pool import StaticPool

import agent.platform.config as config
from agent.persistence import database
from agent.persistence.models import Base


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch):
    """Give every test a fresh in-memory database."""
    engine = sqlalchemy.create_engine(
        "sqlite+pysqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr(config, "DATABASE_URL", "sqlite+pysqlite://")
    monkeypatch.setattr(database, "_engine", engine)
    monkeypatch.setattr(database, "_session_factory", None)
    yield engine
    database.dispose_engine()
    monkeypatch.setattr(database, "_engine", None)
    monkeypatch.setattr(database, "_session_factory", None)


@pytest.fixture
def isolated_tasks_dir(tmp_path, monkeypatch):
    """Compatibility fixture; tasks are now stored in the test database."""
    tasks_dir = tmp_path / ".tasks"
    tasks_dir.mkdir()
    yield tasks_dir

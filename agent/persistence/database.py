"""Lazy SQLAlchemy engine and session management."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import agent.platform.config as config


_engine = None
_session_factory = None


def persistence_enabled() -> bool:
    return bool(config.DATABASE_URL)


def _require_sqlalchemy():
    try:
        import sqlalchemy
    except ImportError as exc:
        raise RuntimeError(
            "SQLAlchemy is required for PostgreSQL persistence"
        ) from exc
    return sqlalchemy


def get_engine():
    global _engine
    if not persistence_enabled():
        raise RuntimeError("DATABASE_URL is required")
    if _engine is not None:
        return _engine

    sqlalchemy = _require_sqlalchemy()
    kwargs = {"pool_pre_ping": True}
    if config.DATABASE_URL.startswith("postgresql"):
        kwargs.update(
            pool_size=config.DB_POOL_SIZE,
            max_overflow=config.DB_MAX_OVERFLOW,
            pool_timeout=config.DB_CONNECT_TIMEOUT,
            connect_args={"connect_timeout": config.DB_CONNECT_TIMEOUT},
        )
    elif config.DATABASE_URL.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    _engine = sqlalchemy.create_engine(config.DATABASE_URL, **kwargs)
    return _engine


def get_session_factory():
    global _session_factory
    if _session_factory is not None:
        return _session_factory
    sqlalchemy = _require_sqlalchemy()
    _session_factory = sqlalchemy.orm.sessionmaker(
        bind=get_engine(),
        autoflush=False,
        expire_on_commit=False,
    )
    return _session_factory


@contextmanager
def session_scope() -> Iterator:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ping_database() -> tuple[bool, str]:
    if not persistence_enabled():
        return False, "disabled"
    try:
        sqlalchemy = _require_sqlalchemy()
        with get_engine().connect() as connection:
            connection.execute(sqlalchemy.text("SELECT 1"))
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def create_all() -> None:
    """Create the schema for isolated SQLite evaluation and test databases."""
    from agent.persistence.models import Base

    Base.metadata.create_all(get_engine())


def persistence_status() -> dict:
    ok, detail = ping_database()
    return {
        "database_url_configured": bool(config.DATABASE_URL),
        "database_reachable": ok,
        "database_status": detail,
        "dialect": (
            get_engine().dialect.name
            if config.DATABASE_URL
            else ""
        ),
    }


__all__ = [
    "dispose_engine",
    "create_all",
    "get_engine",
    "get_session_factory",
    "ping_database",
    "persistence_status",
    "persistence_enabled",
    "session_scope",
]

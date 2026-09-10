"""SQLite 持久化层 —— 统一管理原有的 JSON 文件存储。

覆盖 5 类数据：tasks / cron_jobs / cron_logs / memories / mcp_servers。
Python 标准库 sqlite3，零外部依赖。连接线程安全（单例 + 锁）。
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Optional
from agent.config import WORKDIR

DB_PATH = WORKDIR / "agent.db"

# ---------------------------------------------------------------------------
# 连接管理（单例 + 线程安全）
# ---------------------------------------------------------------------------

_conn: Optional[sqlite3.Connection] = None
_lock = threading.Lock()


def get_conn() -> sqlite3.Connection:
    """获取全局唯一的 SQLite 连接，首次调用时创建表。"""
    global _conn
    if _conn is not None:
        return _conn
    with _lock:
        if _conn is not None:
            return _conn
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")   # 写前日志，读并发不阻塞
        _conn.execute("PRAGMA foreign_keys=ON")
        _init_schema(_conn)
        return _conn


def close_conn() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


# ---------------------------------------------------------------------------
# Schema（5 张表 + 索引）
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT PRIMARY KEY,
    subject     TEXT NOT NULL,
    description TEXT DEFAULT '',
    status      TEXT NOT NULL CHECK(status IN ('pending','in_progress','completed','failed')),
    owner       TEXT,
    blocked_by  TEXT NOT NULL DEFAULT '[]'   -- JSON 数组
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);

CREATE TABLE IF NOT EXISTS cron_jobs (
    id          TEXT PRIMARY KEY,
    cron        TEXT NOT NULL,
    prompt      TEXT NOT NULL,
    recurring   INTEGER NOT NULL DEFAULT 1,
    durable     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS cron_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT NOT NULL,
    cron        TEXT NOT NULL,
    fired_at    TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    success     INTEGER NOT NULL,
    output      TEXT,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_cron_logs_job ON cron_logs(job_id);

CREATE TABLE IF NOT EXISTS memories (
    id           TEXT PRIMARY KEY,
    content      TEXT NOT NULL,
    importance   INTEGER NOT NULL DEFAULT 3,
    category     TEXT NOT NULL DEFAULT 'general',
    created_at   REAL NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance);

CREATE TABLE IF NOT EXISTS mcp_servers (
    name        TEXT PRIMARY KEY,
    config_json TEXT NOT NULL   -- 原始 JSON 配置完整保留，避免字段演进时频繁改 schema
);
"""


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

def task_create(task_id: str, subject: str, description: str,
                status: str, owner: Optional[str], blocked_by_json: str) -> None:
    get_conn().execute(
        "INSERT INTO tasks (id,subject,description,status,owner,blocked_by) VALUES (?,?,?,?,?,?)",
        (task_id, subject, description, status, owner, blocked_by_json),
    )
    get_conn().commit()


def task_save(task_id: str, subject: str, description: str,
              status: str, owner: Optional[str], blocked_by_json: str) -> None:
    get_conn().execute(
        """INSERT INTO tasks VALUES (?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
               subject=excluded.subject,
               description=excluded.description,
               status=excluded.status,
               owner=excluded.owner,
               blocked_by=excluded.blocked_by""",
        (task_id, subject, description, status, owner, blocked_by_json),
    )
    get_conn().commit()


def task_load(task_id: str) -> Optional[sqlite3.Row]:
    cur = get_conn().execute("SELECT * FROM tasks WHERE id=?", (task_id,))
    return cur.fetchone()


def task_list() -> list[sqlite3.Row]:
    return get_conn().execute("SELECT * FROM tasks ORDER BY id").fetchall()


# ---------------------------------------------------------------------------
# Cron jobs
# ---------------------------------------------------------------------------

def cron_job_save(job_id: str, cron: str, prompt: str,
                  recurring: bool, durable: bool) -> None:
    get_conn().execute(
        """INSERT INTO cron_jobs VALUES (?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
               cron=excluded.cron, prompt=excluded.prompt,
               recurring=excluded.recurring, durable=excluded.durable""",
        (job_id, cron, prompt, int(recurring), int(durable)),
    )
    get_conn().commit()


def cron_job_load_all() -> list[sqlite3.Row]:
    return get_conn().execute("SELECT * FROM cron_jobs WHERE durable=1").fetchall()


def cron_job_delete(job_id: str) -> None:
    get_conn().execute("DELETE FROM cron_jobs WHERE id=?", (job_id,))
    get_conn().commit()


def cron_log_insert(job_id: str, cron: str, fired_at: str, finished_at: str,
                    success: bool, output: str, error: Optional[str]) -> None:
    get_conn().execute(
        """INSERT INTO cron_logs (job_id,cron,fired_at,finished_at,success,output,error)
           VALUES (?,?,?,?,?,?,?)""",
        (job_id, cron, fired_at, finished_at, int(success), output, error),
    )
    get_conn().commit()


def cron_log_list(job_id: Optional[str] = None, limit: int = 20) -> list[sqlite3.Row]:
    if job_id:
        return get_conn().execute(
            "SELECT * FROM cron_logs WHERE job_id=? ORDER BY id DESC LIMIT ?",
            (job_id, limit),
        ).fetchall()
    return get_conn().execute(
        "SELECT * FROM cron_logs ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()


# ---------------------------------------------------------------------------
# Memories
# ---------------------------------------------------------------------------

def memory_insert(mem_id: str, content: str, importance: int,
                  category: str, created_at: float, access_count: int = 0) -> None:
    get_conn().execute(
        """INSERT INTO memories VALUES (?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET access_count=excluded.access_count""",
        (mem_id, content, importance, category, created_at, access_count),
    )
    get_conn().commit()


def memory_select_all() -> list[sqlite3.Row]:
    return get_conn().execute("SELECT * FROM memories ORDER BY created_at").fetchall()


def memory_update_access(mem_id: str, access_count: int) -> None:
    get_conn().execute(
        "UPDATE memories SET access_count=? WHERE id=?", (access_count, mem_id)
    )
    get_conn().commit()


def memory_delete(mem_id: str) -> None:
    get_conn().execute("DELETE FROM memories WHERE id=?", (mem_id,))
    get_conn().commit()


# ---------------------------------------------------------------------------
# MCP servers
# ---------------------------------------------------------------------------

def mcp_server_save(name: str, config_json: str) -> None:
    get_conn().execute(
        """INSERT INTO mcp_servers VALUES (?,?)
           ON CONFLICT(name) DO UPDATE SET config_json=excluded.config_json""",
        (name, config_json),
    )
    get_conn().commit()


def mcp_server_load_all() -> list[sqlite3.Row]:
    return get_conn().execute("SELECT * FROM mcp_servers").fetchall()


def mcp_server_delete(name: str) -> None:
    get_conn().execute("DELETE FROM mcp_servers WHERE name=?", (name,))
    get_conn().commit()

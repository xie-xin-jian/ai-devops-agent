"""task_system.py 任务系统测试。

使用 isolated_tasks_dir fixture 隔离测试数据，避免污染真实 .tasks/ 目录。
"""
import pytest
from agent.task_system import (
    create_task, claim_task, complete_task, list_tasks,
    can_start, get_task_json, load_task,
)


# ── 创建与查询 ──

def test_create_task(isolated_tasks_dir):
    """创建任务应生成正确格式。"""
    t = create_task("Task 1", "First task")
    assert t.id.startswith("task_")
    assert t.status == "pending"
    assert t.owner is None


def test_get_task_json(isolated_tasks_dir):
    """get_task_json 应返回含必要字段的 JSON。"""
    t = create_task("Task 1", "First task")
    json_str = get_task_json(t.id)
    assert "id" in json_str
    assert "subject" in json_str


def test_list_tasks(isolated_tasks_dir):
    """list_tasks 应返回所有任务。"""
    create_task("Task 1")
    create_task("Task 2")
    create_task("Task 3")
    tasks = list_tasks()
    assert len(tasks) == 3


# ── 认领与完成 ──

def test_claim_task(isolated_tasks_dir):
    """认领任务后状态应为 in_progress。"""
    t = create_task("Task 1")
    result = claim_task(t.id, "agent1")
    assert "Claimed" in result
    loaded = load_task(t.id)
    assert loaded.status == "in_progress"
    assert loaded.owner == "agent1"


def test_claim_already_owned(isolated_tasks_dir):
    """已被认领的任务（状态变为 in_progress）再次认领应被阻止。"""
    t = create_task("Task 1")
    claim_task(t.id, "agent1")
    result = claim_task(t.id, "agent2")
    assert "cannot claim" in result


def test_complete_task(isolated_tasks_dir):
    """完成任务后状态应为 completed。"""
    t = create_task("Task 1")
    claim_task(t.id)
    result = complete_task(t.id)
    assert "Completed" in result
    loaded = load_task(t.id)
    assert loaded.status == "completed"


# ── 依赖关系 ──

def test_task_dependency_resolved(isolated_tasks_dir):
    """依赖任务完成后应可启动。"""
    t1 = create_task("Task 1")
    claim_task(t1.id)
    complete_task(t1.id)
    t2 = create_task("Task 2", blockedBy=[t1.id])
    assert can_start(t2.id) is True


def test_cannot_claim_blocked_task(isolated_tasks_dir):
    """依赖未完成时应阻止认领。"""
    t1 = create_task("Task 1")
    t2 = create_task("Task 2", blockedBy=[t1.id])
    result = claim_task(t2.id)
    assert "Cannot start" in result


def test_complete_returns_unblocked(isolated_tasks_dir):
    """完成任务应返回被解锁的任务列表。"""
    t1 = create_task("Task 1")
    create_task("Task 2", blockedBy=[t1.id])
    claim_task(t1.id)
    result = complete_task(t1.id)
    assert "Unblocked" in result


# ── 状态机非法转移 ──

def test_cannot_claim_non_pending(isolated_tasks_dir):
    """非 pending 状态应阻止认领。"""
    t = create_task("Task 1")
    claim_task(t.id)
    result = claim_task(t.id)
    assert "cannot claim" in result


def test_cannot_complete_non_in_progress(isolated_tasks_dir):
    """非 in_progress 状态应阻止完成。"""
    t = create_task("Task 1")
    result = complete_task(t.id)
    assert "cannot complete" in result

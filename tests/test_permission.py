"""permission.py 权限系统测试。

测试真实的 permission_hook（从 agent.permission import），而非配置副本。
"""
import pytest
from agent.permission import permission_hook, safe_path
from agent.config import DENY_LIST, DESTRUCTIVE


class MockBlock:
    """模拟 Anthropic SDK 的 tool_use block（对象形态）。"""

    def __init__(self, name, input_data):
        self.name = name
        self.input = input_data


class MockInput:
    """模拟 input 为对象的情况。"""

    def __init__(self, command=None, path=None):
        if command is not None:
            self.command = command
        if path is not None:
            self.path = path


# ── 正常路径 ──

def test_bash_normal_command_dict():
    """dict 类型 block - 正常 bash 命令应通过。"""
    block = {"name": "bash", "input": {"command": "ls -la"}}
    assert permission_hook(block) is None


def test_bash_normal_command_object():
    """对象类型 block - 正常命令应通过。"""
    block = MockBlock("bash", {"command": "echo hello world"})
    assert permission_hook(block) is None


def test_write_file_normal_path():
    """write_file 正常路径应通过。"""
    block = MockBlock("write_file", {"path": "test.txt"})
    assert permission_hook(block) is None


def test_other_tool_passes():
    """其他工具（read_file）应直接通过。"""
    block = {"name": "read_file", "input": {"path": "test.txt"}}
    assert permission_hook(block) is None


# ── 拒绝路径 ──

def test_bash_deny_list_dict():
    """dict 类型 block - DENY_LIST 匹配应拒绝。"""
    block = {"name": "bash", "input": {"command": "sudo apt-get install"}}
    result = permission_hook(block)
    assert result is not None
    assert "Permission denied" in result


def test_bash_destructive_non_cli():
    """对象类型 block - DESTRUCTIVE 匹配，非 CLI 模式应需要审批。"""
    block = MockBlock("bash", {"command": "rm -rf test_dir"})
    result = permission_hook(block)
    assert result is not None
    assert "Permission required" in result


def test_write_file_path_escape():
    """write_file 路径逃逸应拒绝。"""
    block = {"name": "write_file", "input": {"path": "../../etc/passwd"}}
    result = permission_hook(block)
    assert result is not None
    assert "escapes workspace" in result


def test_edit_file_path_escape():
    """edit_file 路径逃逸应拒绝。"""
    block = {"name": "edit_file", "input": {"path": "../secret.txt"}}
    result = permission_hook(block)
    assert result is not None
    assert "escapes workspace" in result


def test_input_is_object():
    """input 也是对象的情况应正确处理。"""
    block = MockBlock("bash", MockInput("sudo test"))
    result = permission_hook(block)
    assert result is not None
    assert "Permission denied" in result


# ── 真实配置覆盖验证 ──

def test_deny_list_covers_all_patterns():
    """验证 DENY_LIST 中的每个模式都能被真实 permission_hook 拦截。"""
    for pattern in DENY_LIST:
        block = {"name": "bash", "input": {"command": f"{pattern} something"}}
        result = permission_hook(block)
        assert result is not None, f"DENY_LIST pattern '{pattern}' should be blocked"


def test_destructive_covers_all_tokens():
    """验证 DESTRUCTIVE 中的每个 token 都能触发审批。"""
    for token in DESTRUCTIVE:
        block = {"name": "bash", "input": {"command": f"{token} target"}}
        result = permission_hook(block)
        assert result is not None, f"DESTRUCTIVE token '{token}' should require approval"


# ── safe_path 单元测试 ──

def test_safe_path_normal():
    """safe_path 正常路径应返回解析后的 Path。"""
    p = safe_path("test.txt")
    assert p.name == "test.txt"


def test_safe_path_escape_raises():
    """safe_path 路径逃逸应抛 ValueError。"""
    with pytest.raises(ValueError, match="escapes workspace"):
        safe_path("../../etc/passwd")

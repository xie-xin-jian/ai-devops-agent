from pathlib import Path

DENY_LIST = ['rm -rf /', 'sudo', 'shutdown', 'reboot', 'mkfs', 'dd if=']
DESTRUCTIVE = ['rm ', '> /etc/', 'chmod 777']
CLI_ACTIVE = False
WORKDIR = Path.cwd()


def safe_path(p, cwd=None):
    base = cwd or WORKDIR
    path = (Path(base) / p).resolve()
    if not path.is_relative_to(Path(base)):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def interactive_approve(command):
    print(f"\n[permission] destructive command")
    print(f"  {command}")
    choice = input("  Allow? [y/N] ").strip().lower()
    return choice in ("y", "yes")


def _get_name(block):
    if isinstance(block, dict):
        return block.get("name", "")
    return getattr(block, "name", "")


def _get_input(block):
    if isinstance(block, dict):
        return block.get("input", {})
    return getattr(block, "input", {})


def permission_hook(block):
    name = _get_name(block)
    tool_input = _get_input(block)

    if name == "bash":
        command = tool_input.get("command", "") if isinstance(tool_input, dict) else getattr(tool_input, "command", "")
        for pattern in DENY_LIST:
            if pattern in command:
                return f"Permission denied: '{pattern}' is on the deny list"
        if any(token in command for token in DESTRUCTIVE):
            if CLI_ACTIVE:
                if not interactive_approve(command):
                    return "Permission denied by user"
            else:
                return f"Permission required: destructive command needs approval: {command}"
    if name in ("write_file", "edit_file"):
        path = tool_input.get("path", "") if isinstance(tool_input, dict) else getattr(tool_input, "path", "")
        try:
            safe_path(path)
        except Exception:
            return f"Permission denied: path escapes workspace: {path}"
    return None


print("=== permission.py 功能测试 ===")

# 测试 1: dict 类型的 block - 正常 bash 命令
block_dict = {"name": "bash", "input": {"command": "ls -la"}}
result = permission_hook(block_dict)
print(f"测试 1 - bash ls (dict): {result}")
assert result is None, "应该通过"

# 测试 2: dict 类型的 block - DENY_LIST 匹配
block_deny = {"name": "bash", "input": {"command": "sudo apt-get install"}}
result = permission_hook(block_deny)
print(f"测试 2 - sudo 拒绝 (dict): {result}")
assert result is not None and "Permission denied" in result, "应该被拒绝"

# 测试 3: 对象类型的 block - 正常命令
class MockBlock:
    def __init__(self, name, input):
        self.name = name
        self.input = input

block_obj = MockBlock("bash", {"command": "echo hello world"})
result = permission_hook(block_obj)
print(f"测试 3 - bash echo (object): {result}")
assert result is None, "应该通过"

# 测试 4: 对象类型 - DESTRUCTIVE 匹配，非 CLI 模式
block_destructive = MockBlock("bash", {"command": "rm -rf test_dir"})
result = permission_hook(block_destructive)
print(f"测试 4 - rm 破坏性命令 (object, 非CLI): {result}")
assert result is not None and "Permission required" in result, "应该需要审批"

# 测试 5: write_file - 路径逃逸
block_write_escape = {"name": "write_file", "input": {"path": "../../etc/passwd"}}
result = permission_hook(block_write_escape)
print(f"测试 5 - write_file 路径逃逸 (dict): {result}")
assert result is not None and "escapes workspace" in result, "应该被拒绝"

# 测试 6: write_file - 正常路径
block_write_ok = MockBlock("write_file", {"path": "test.txt"})
result = permission_hook(block_write_ok)
print(f"测试 6 - write_file 正常路径 (object): {result}")
assert result is None, "应该通过"

# 测试 7: edit_file - 路径逃逸
block_edit_escape = {"name": "edit_file", "input": {"path": "../secret.txt"}}
result = permission_hook(block_edit_escape)
print(f"测试 7 - edit_file 路径逃逸 (dict): {result}")
assert result is not None and "escapes workspace" in result, "应该被拒绝"

# 测试 8: 其他工具 - 直接通过
block_other = {"name": "read_file", "input": {"path": "test.txt"}}
result = permission_hook(block_other)
print(f"测试 8 - read_file 其他工具 (dict): {result}")
assert result is None, "应该通过"

# 测试 9: input 也是对象的情况
class MockInput:
    def __init__(self, command):
        self.command = command

block_input_obj = MockBlock("bash", MockInput("sudo test"))
result = permission_hook(block_input_obj)
print(f"测试 9 - input 也是对象 (object): {result}")
assert result is not None and "Permission denied" in result, "应该被拒绝"

print()
print("✓ 所有 permission.py 功能测试通过!")

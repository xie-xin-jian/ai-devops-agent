from pathlib import Path
from agent.config import DENY_LIST, DESTRUCTIVE, CLI_ACTIVE, WORKDIR


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

    # MCP destructive 工具审批（对齐 s20 line 918-922）
    # mcp__deploy__trigger 这类破坏性工具需要用户确认
    from agent.mcp import is_destructive_mcp_tool
    if is_destructive_mcp_tool(name):
        if CLI_ACTIVE:
            print(f"\n[permission] MCP destructive tool: {name}")
            if not interactive_approve(name):
                return "Permission denied by user"
        else:
            return f"Permission required: MCP destructive tool needs approval: {name}"

    return None

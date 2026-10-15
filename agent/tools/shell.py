import subprocess
import re
from pathlib import Path

from agent.platform.config import WORKDIR


# (正则, 建议工具, 理由)。只收「语义唯一」的巡检命令；复合命令(&&/;)不拦截。
BASH_REDIRECT_RULES = [
    (r"\b(ss|netstat)\s+-\w*t\w*l\w*n\w*", "port_listen", "查看监听端口"),
    (r"^\s*(sudo\s+)?df\s+-h\s*$", "disk_usage", "查看磁盘用量"),
    (r"^\s*(sudo\s+)?free\s+-h?\s*$", "memory_usage", "查看内存用量"),
    (r"^\s*(sudo\s+)?uptime\s*$", "system_info", "查看系统概况"),
    (r"\bpgrep\b", "process_search", "按名查进程"),
    (r"\bps\s+(-ef|aux)\s*\|\s*grep\b", "process_search", "按名查进程"),
]

_CURL_GET = re.compile(r"\bcurl\b.*https?://", re.S)
_CURL_WRITE = re.compile(
    r"(-d\b|--data\b|-X\s*(POST|PUT|DELETE|PATCH)|-T\b)"
)


def suggest_tool_for_command(command: str) -> tuple[str, str] | None:
    """命中专用工具规则时返回 (tool_name, reason)，否则返回 None。

    `force:` 前缀为逃生门，显式绕过拦截。
    """
    cmd = (command or "").strip()
    if not cmd or cmd.startswith("force:"):
        return None
    if "&&" in cmd or ";" in cmd:
        return None
    if _CURL_GET.search(cmd) and not _CURL_WRITE.search(cmd):
        return ("http_check", "HTTP 健康检查/GET 请求")
    for pattern, tool, reason in BASH_REDIRECT_RULES:
        if re.search(pattern, cmd):
            return (tool, reason)
    return None


def run_host_bash(
    command: str,
    cwd: str | Path | None = None,
    *,
    default_cwd: str | Path | None = None,
    timeout: int = 120,
) -> str:
    """Run an approved command directly on the host.

    The command has the same filesystem permissions as the Agent process.
    Approval must happen before this function is called.
    """
    try:
        if not str(command or "").strip():
            return "Error: command is required"

        base = Path(default_cwd or WORKDIR).resolve()
        if not base.is_dir():
            return f"Error: Default working directory does not exist: {base}"

        if cwd:
            working_dir = Path(cwd).expanduser()
            if not working_dir.is_absolute():
                working_dir = base / working_dir
            working_dir = working_dir.resolve()
        else:
            working_dir = base

        if not working_dir.is_dir():
            return f"Error: Working directory does not exist: {working_dir}"

        effective_timeout = max(1, min(int(timeout or 120), 600))
        result = subprocess.run(
            command,
            shell=True,
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=effective_timeout,
        )
        output = (result.stdout + result.stderr).strip()
        if not output:
            output = "(no output)"
        return (
            f"exit_code={result.returncode}\n"
            f"cwd={working_dir}\n"
            f"{output}"
        )[:50000]
    except subprocess.TimeoutExpired:
        return f"Error: Timeout ({timeout}s)"
    except Exception as exc:
        return f"Error: {exc}"


BASH_SCHEMA = {
    "name": "bash",
    "description": "Run a shell command.",
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "cwd": {"type": "string"},
            "run_in_background": {"type": "boolean"},
        },
        "required": ["command"],
    },
}

SHELL_TOOL_SCHEMAS = [BASH_SCHEMA]

SHELL_TOOL_HANDLERS = {
    "bash": run_host_bash,
}

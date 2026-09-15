import subprocess
from pathlib import Path

from agent.config import WORKDIR
from agent.tools.file_tools import safe_path


def _resolve_cwd(cwd: str | Path | None) -> Path:
    resolved = safe_path(str(cwd) if cwd else ".", WORKDIR)
    if not resolved.is_dir():
        raise ValueError(f"Working directory does not exist: {cwd}")
    return resolved


def run_bash(command: str, cwd: str | Path | None = None,
             run_in_background: bool = False) -> str:
    try:
        working_dir = _resolve_cwd(cwd)
        r = subprocess.run(command, shell=True, cwd=working_dir,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except ValueError as e:
        return f"Error: {e}"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"


def run_bash_long(command: str, cwd: str | Path | None = None) -> str:
    try:
        working_dir = _resolve_cwd(cwd)
        p = subprocess.Popen(command, shell=True, cwd=working_dir,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True)
    except ValueError as e:
        return f"Error: {e}"
    try:
        out, _ = p.communicate()
    except KeyboardInterrupt:
        p.kill()
        return "Error: interrupted"
    out = (out or "").strip()
    return out[:50000] if out else "(no output)"


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
    "bash": run_bash,
}

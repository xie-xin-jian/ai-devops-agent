import subprocess
from pathlib import Path

from agent.config import WORKDIR


def run_bash(command: str, cwd: str | Path | None = None,
             run_in_background: bool = False) -> str:
    try:
        r = subprocess.run(command, shell=True, cwd=cwd or WORKDIR,
                           capture_output=True, text=True, timeout=120)
        out = (r.stdout + r.stderr).strip()
        return out[:50000] if out else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Timeout (120s)"


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

import subprocess
from pathlib import Path

from agent.platform.config import WORKDIR


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

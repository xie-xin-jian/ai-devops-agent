"""Project-scoped read and operation tools."""

from __future__ import annotations

import difflib
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import agent.platform.config as config
from agent.targets.service import is_sensitive_path
from agent.targets.store import TargetStore


TARGET_TOOL_NAMES = {
    "target_status",
    "target_logs",
    "target_http",
    "target_list_files",
    "target_read_file",
    "target_glob",
    "target_write_file",
    "target_edit_file",
    "target_restart",
    "target_deploy",
}
MAX_FILE_BYTES = 1_000_000
MAX_RESULTS = 500
TARGET_BACKUP_ROOT = config.DATA_DIR / ".target_backups"


def _target(target_id: str):
    identifier = str(target_id or "").strip()
    if not identifier:
        raise ValueError(
            "No active target is selected for this Session. "
            "Select a project in the frontend first."
        )
    target = TargetStore().get(identifier)
    if target is None:
        raise ValueError(f"Target not found: {identifier}")
    return target


def _resolve(target, path: str, *, must_exist: bool = True) -> Path:
    value = str(path or ".").strip() or "."
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = Path(target.root) / candidate
    resolved = candidate.expanduser().resolve(strict=False)
    root = Path(target.root).resolve()
    if resolved != root and not resolved.is_relative_to(root):
        raise ValueError(f"Path escapes target root: {path}")
    if must_exist and not resolved.exists():
        raise ValueError(f"Target path does not exist: {resolved}")
    return resolved


def _read_path(path: Path, limit: int | None, offset: int) -> str:
    if is_sensitive_path(path):
        raise ValueError(f"Sensitive file is blocked by default: {path}")
    if not path.is_file():
        raise ValueError(f"Target path is not a regular file: {path}")
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise ValueError(
            f"Target file is too large ({size} bytes; max {MAX_FILE_BYTES})"
        )
    raw = path.read_bytes()
    if b"\x00" in raw:
        raise ValueError(f"Target file appears to be binary: {path}")
    lines = raw.decode("utf-8", errors="replace").splitlines()
    start = max(int(offset or 0), 0)
    lines = lines[start:]
    if limit is not None:
        max_lines = max(int(limit), 0)
        if max_lines < len(lines):
            lines = lines[:max_lines] + [
                f"... ({len(lines) - max_lines} more lines)"
            ]
    return "\n".join(lines)


def _validate_text_file(path: Path) -> None:
    if is_sensitive_path(path):
        raise ValueError(f"Sensitive file is blocked by default: {path}")
    if path.exists():
        if not path.is_file():
            raise ValueError(f"Target path is not a regular file: {path}")
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise ValueError(
                f"Target file is too large ({size} bytes; max {MAX_FILE_BYTES})"
            )
        raw = path.read_bytes()
        if b"\x00" in raw:
            raise ValueError(f"Target file appears to be binary: {path}")


def _backup_file(target, path: Path) -> str:
    if not path.exists():
        return ""
    relative = path.resolve().relative_to(Path(target.root).resolve())
    stamp = f"{time.strftime('%Y%m%d-%H%M%S')}-{time.time_ns() % 1_000_000_000:09d}"
    backup = TARGET_BACKUP_ROOT / target.id / stamp / relative
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_bytes(path.read_bytes())
    return str(backup)


def _text_diff(path: Path, before: str, after: str) -> str:
    diff = difflib.unified_diff(
        before.splitlines(),
        after.splitlines(),
        fromfile=f"{path} (before)",
        tofile=f"{path} (after)",
        lineterm="",
    )
    text = "\n".join(diff)
    return text[:10000] if text else "(no textual changes)"


def _http_check(url: str) -> dict:
    started = time.time()
    request = Request(url, headers={"User-Agent": "ai-devops-agent/1.0"})
    try:
        with urlopen(request, timeout=10) as response:
            body = response.read(2000).decode("utf-8", errors="replace")
            return {
                "ok": 200 <= response.status < 400,
                "status_code": response.status,
                "elapsed_ms": int((time.time() - started) * 1000),
                "body": body,
            }
    except HTTPError as exc:
        body = exc.read(2000).decode("utf-8", errors="replace")
        return {
            "ok": False,
            "status_code": exc.code,
            "elapsed_ms": int((time.time() - started) * 1000),
            "body": body,
            "error": str(exc),
        }
    except (URLError, OSError, TimeoutError) as exc:
        return {
            "ok": False,
            "status_code": None,
            "elapsed_ms": int((time.time() - started) * 1000),
            "error": str(exc),
        }


def _select_http_url(target, url: str) -> str:
    selected = str(url or target.health_url or "").strip()
    if not selected:
        raise ValueError("Target has no health_url configured")
    if not selected.lower().startswith(("http://", "https://")):
        raise ValueError("URL must start with http:// or https://")
    if target.health_url and selected == target.health_url:
        return selected
    hostname = (urlparse(selected).hostname or "").lower()
    if hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(
            "target_http may only probe the configured health_url or "
            "a loopback URL"
        )
    return selected


def _run_project_command(target, command: str, timeout_seconds: int = 120) -> str:
    value = str(command or "").strip()
    if not value:
        raise ValueError("Project command is required")
    timeout = max(1, min(int(timeout_seconds or 120), 600))
    result = subprocess.run(
        value,
        shell=True,
        cwd=target.root,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    output = (result.stdout + result.stderr).strip()
    if not output:
        output = "(no output)"
    return f"exit_code={result.returncode}\n{output}"[:50000]


def _restart_command_preview(target) -> str:
    if target.restart_command:
        return target.restart_command
    if target.service:
        return f"systemctl restart {target.service}"
    return ""


def _run_systemctl_restart(target) -> str:
    if not target.service:
        raise ValueError("Target has no service configured")
    result = subprocess.run(
        ["systemctl", "restart", target.service],
        cwd=target.root,
        capture_output=True,
        text=True,
        timeout=120,
    )
    output = (result.stdout + result.stderr).strip()
    if not output:
        output = "(no output)"
    return f"exit_code={result.returncode}\n{output}"


def run_target_status(target_id: str) -> str:
    try:
        from agent.tools.ops import (
            run_port_listen,
            run_process_search,
            run_service_status,
        )

        target = _target(target_id)
        sections = [
            f"Target: {target.name} ({target.id})",
            f"Root: {target.root}",
        ]
        if target.service:
            sections.append("Service status:\n" + run_service_status(target.service))
        if target.health_url:
            sections.append(
                "Health check:\n"
                + str(_http_check(target.health_url))
            )
        if target.service:
            sections.append("Processes:\n" + run_process_search(target.service))
        sections.append("Listening ports:\n" + run_port_listen())
        return "\n\n".join(sections)
    except Exception as exc:
        return f"Error: {exc}"


def run_target_logs(
    target_id: str,
    lines: int = 100,
    path: str = "",
) -> str:
    try:
        target = _target(target_id)
        count = max(1, min(int(lines or 100), 500))
        selected = str(path or target.log_path or "").strip()
        if selected:
            log_path = _resolve(target, selected)
            if not log_path.is_file():
                return f"Error: Log path is not a regular file: {log_path}"
            all_lines = _read_path(
                log_path,
                limit=None,
                offset=0,
            ).splitlines()
            return "\n".join(all_lines[-count:])
        if target.service:
            from agent.tools.ops import run_system_logs

            return run_system_logs(target.service, count)
        return "Error: Target has no service or log_path configured."
    except Exception as exc:
        return f"Error: {exc}"


def run_target_http(target_id: str, url: str = "") -> str:
    try:
        target = _target(target_id)
        selected = _select_http_url(target, url)
        return str(_http_check(selected))
    except Exception as exc:
        return f"Error: {exc}"


def run_target_list_files(target_id: str, path: str = ".", limit: int = 200) -> str:
    try:
        target = _target(target_id)
        directory = _resolve(target, path)
        if not directory.is_dir():
            return f"Error: Target path is not a directory: {directory}"
        max_entries = max(1, min(int(limit or 200), MAX_RESULTS))
        entries = sorted(
            directory.iterdir(),
            key=lambda item: (not item.is_dir(), item.name.lower()),
        )
        lines = []
        for item in entries[:max_entries]:
            kind = "dir" if item.is_dir() else "file"
            size = item.stat().st_size if item.is_file() else 0
            lines.append(f"{kind}\t{size}\t{item.name}")
        if len(entries) > max_entries:
            lines.append(f"... ({len(entries) - max_entries} more entries)")
        return "\n".join(lines) if lines else "(empty directory)"
    except Exception as exc:
        return f"Error: {exc}"


def run_target_read_file(
    target_id: str,
    path: str,
    limit: int | None = None,
    offset: int = 0,
) -> str:
    try:
        target = _target(target_id)
        return _read_path(_resolve(target, path), limit, offset)
    except Exception as exc:
        return f"Error: {exc}"


def run_target_glob(target_id: str, pattern: str, limit: int = 200) -> str:
    try:
        target = _target(target_id)
        relative = Path(str(pattern or "").strip())
        if not str(relative) or relative.is_absolute() or ".." in relative.parts:
            return "Error: Pattern must be relative and cannot contain '..'"
        max_results = max(1, min(int(limit or 200), MAX_RESULTS))
        matches = []
        for item in Path(target.root).glob(str(relative)):
            resolved = item.resolve(strict=False)
            if not resolved.is_relative_to(Path(target.root).resolve()):
                continue
            matches.append(
                resolved.relative_to(Path(target.root).resolve()).as_posix()
            )
            if len(matches) >= max_results:
                break
        return "\n".join(matches) if matches else "(no matches)"
    except Exception as exc:
        return f"Error: {exc}"


def run_target_write_file(
    target_id: str,
    path: str,
    content: str,
    backup: bool = True,
) -> str:
    try:
        target = _target(target_id)
        destination = _resolve(target, path, must_exist=False)
        _validate_text_file(destination)
        text = str(content)
        size = len(text.encode("utf-8"))
        if size > MAX_FILE_BYTES:
            raise ValueError(
                f"Content is too large ({size} bytes; max {MAX_FILE_BYTES})"
            )

        before = (
            destination.read_text(encoding="utf-8")
            if destination.exists()
            else ""
        )
        backup_path = _backup_file(target, destination) if backup else ""
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8", newline="")
        return (
            f"Wrote {size} bytes to {destination}\n"
            f"backup: {backup_path or '(none)'}\n\n"
            f"{_text_diff(destination, before, text)}"
        )
    except Exception as exc:
        return f"Error: {exc}"


def run_target_edit_file(
    target_id: str,
    path: str,
    old_text: str,
    new_text: str,
    replace_all: bool = False,
    backup: bool = True,
) -> str:
    try:
        target = _target(target_id)
        destination = _resolve(target, path)
        _validate_text_file(destination)
        if not destination.is_file():
            raise ValueError(f"Target path is not a regular file: {destination}")

        before = destination.read_text(encoding="utf-8")
        occurrences = before.count(str(old_text))
        if occurrences == 0:
            raise ValueError("old_text was not found in the target file")
        if occurrences > 1 and not replace_all:
            raise ValueError(
                f"old_text occurs {occurrences} times; set replace_all=true "
                "or provide a more specific block"
            )

        after = before.replace(
            str(old_text),
            str(new_text),
            -1 if replace_all else 1,
        )
        backup_path = _backup_file(target, destination) if backup else ""
        destination.write_text(after, encoding="utf-8", newline="")
        return (
            f"Edited {destination}\n"
            f"replacements: {occurrences if replace_all else 1}\n"
            f"backup: {backup_path or '(none)'}\n\n"
            f"{_text_diff(destination, before, after)}"
        )
    except Exception as exc:
        return f"Error: {exc}"


def run_target_restart(target_id: str) -> str:
    try:
        target = _target(target_id)
        command = _restart_command_preview(target)
        if not command:
            return "Error: Target has no restart_command or service configured."
        if target.restart_command:
            output = _run_project_command(target, target.restart_command, 120)
        else:
            output = _run_systemctl_restart(target)
        time.sleep(1)
        health = (
            str(_http_check(target.health_url))
            if target.health_url
            else "No health_url configured."
        )
        return f"Restart command:\n{output}\n\nHealth check:\n{health}"
    except Exception as exc:
        return f"Error: {exc}"


def run_target_deploy(target_id: str) -> str:
    try:
        target = _target(target_id)
        if not target.deploy_command:
            return "Error: Target has no deploy_command configured."
        output = _run_project_command(target, target.deploy_command, 600)
        time.sleep(1)
        health = (
            str(_http_check(target.health_url))
            if target.health_url
            else "No health_url configured."
        )
        return f"Deploy command:\n{output}\n\nHealth check:\n{health}"
    except Exception as exc:
        return f"Error: {exc}"


TARGET_STATUS_SCHEMA = {
    "name": "target_status",
    "description": (
        "Inspect the active project target: service status, health endpoint, "
        "processes, and listening ports. Read-only."
    ),
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

TARGET_LOGS_SCHEMA = {
    "name": "target_logs",
    "description": (
        "Read recent logs for the active target from its configured log file "
        "or systemd service. Read-only."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Optional path relative to the target root",
            },
            "lines": {"type": "integer"},
        },
        "required": [],
    },
}

TARGET_HTTP_SCHEMA = {
    "name": "target_http",
    "description": (
        "Check the active target's health URL, or an explicitly supplied "
        "HTTP(S) URL. Read-only."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": [],
    },
}

TARGET_LIST_FILES_SCHEMA = {
    "name": "target_list_files",
    "description": (
        "List files inside the active project root. Read-only and confined "
        "to the selected target directory."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "limit": {"type": "integer"},
        },
        "required": [],
    },
}

TARGET_READ_FILE_SCHEMA = {
    "name": "target_read_file",
    "description": (
        "Read a text file inside the active project root. Sensitive files "
        "such as .env and private keys are blocked. Read-only."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "limit": {"type": "integer"},
            "offset": {"type": "integer"},
        },
        "required": ["path"],
    },
}

TARGET_GLOB_SCHEMA = {
    "name": "target_glob",
    "description": (
        "Find files using a relative glob inside the active project root. "
        "Read-only."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "limit": {"type": "integer"},
        },
        "required": ["pattern"],
    },
}

TARGET_WRITE_FILE_SCHEMA = {
    "name": "target_write_file",
    "description": (
        "Write a UTF-8 text file inside the active project root. This is a "
        "mutating operation and requires user approval. A backup is created "
        "under DATA_DIR/.target_backups by default."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path inside the target root",
            },
            "content": {"type": "string"},
            "backup": {"type": "boolean", "default": True},
        },
        "required": ["path", "content"],
    },
}

TARGET_EDIT_FILE_SCHEMA = {
    "name": "target_edit_file",
    "description": (
        "Replace exact old_text in a target file with new_text. Requires "
        "approval, rejects ambiguous multi-match edits unless replace_all=true, "
        "and creates a backup by default."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_text": {"type": "string"},
            "new_text": {"type": "string"},
            "replace_all": {"type": "boolean", "default": False},
            "backup": {"type": "boolean", "default": True},
        },
        "required": ["path", "old_text", "new_text"],
    },
}

TARGET_RESTART_SCHEMA = {
    "name": "target_restart",
    "description": (
        "Restart the active project's configured service. Requires approval."
    ),
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

TARGET_DEPLOY_SCHEMA = {
    "name": "target_deploy",
    "description": (
        "Run the active project's configured deploy command and verify its "
        "health endpoint. Requires approval."
    ),
    "input_schema": {"type": "object", "properties": {}, "required": []},
}

TARGET_TOOL_SCHEMAS = [
    TARGET_STATUS_SCHEMA,
    TARGET_LOGS_SCHEMA,
    TARGET_HTTP_SCHEMA,
    TARGET_LIST_FILES_SCHEMA,
    TARGET_READ_FILE_SCHEMA,
    TARGET_GLOB_SCHEMA,
    TARGET_WRITE_FILE_SCHEMA,
    TARGET_EDIT_FILE_SCHEMA,
    TARGET_RESTART_SCHEMA,
    TARGET_DEPLOY_SCHEMA,
]

TARGET_TOOL_HANDLERS = {
    "target_status": run_target_status,
    "target_logs": run_target_logs,
    "target_http": run_target_http,
    "target_list_files": run_target_list_files,
    "target_read_file": run_target_read_file,
    "target_glob": run_target_glob,
    "target_write_file": run_target_write_file,
    "target_edit_file": run_target_edit_file,
    "target_restart": run_target_restart,
    "target_deploy": run_target_deploy,
}


__all__ = [
    "TARGET_TOOL_HANDLERS",
    "TARGET_TOOL_NAMES",
    "TARGET_TOOL_SCHEMAS",
]

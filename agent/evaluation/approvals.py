"""Deterministic approval decisions for unattended evaluation runs."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import shlex

from agent.evaluation.cases import EvalCase
from agent.tools.policy import get_tool_policy


_DANGEROUS_COMMAND = re.compile(
    r"(?i)("
    r"\brm\s+-(?:[a-z]*r[a-z]*f|[a-z]*f[a-z]*r)\b|"
    r"\bremove-item\b.*\b-recurse\b|"
    r"\bdel\s+/[a-z]*s|"
    r"\bformat(?:\.com)?\b|"
    r"\bdiskpart\b|"
    r"\bmkfs(?:\.\w+)?\b|"
    r"\bdd\s+if=|"
    r"\bshutdown\b|\breboot\b|\bpoweroff\b|"
    r"\b(?:curl|wget)\b[^\n|]*\|\s*(?:sh|bash)\b|"
    r"\bchmod\s+[^\n]*\s+/(?:\s|$)|"
    r"\bchown\s+[^\n]*\s+/(?:\s|$)"
    r")"
)
_SHELL_CONTROL = re.compile(r"(?:;|&&|\|\||[<>]|`|\$\()")
_DRIVE_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_READ_ONLY_EXECUTABLES = {
    "cat",
    "df",
    "dir",
    "docker",
    "du",
    "file",
    "find",
    "free",
    "get-childitem",
    "get-content",
    "get-process",
    "grep",
    "head",
    "hostname",
    "ipconfig",
    "journalctl",
    "ls",
    "netstat",
    "ps",
    "pwd",
    "sort",
    "ss",
    "stat",
    "systemctl",
    "tail",
    "tasklist",
    "top",
    "type",
    "uptime",
    "wc",
    "where",
    "whoami",
}
_TEST_COMMANDS = {
    ("pytest",),
    ("python", "-m", "pytest"),
    ("python3", "-m", "pytest"),
    ("npm", "test"),
    ("npm", "run", "test"),
    ("pnpm", "test"),
    ("yarn", "test"),
    ("go", "test"),
    ("dotnet", "test"),
}


@dataclass(frozen=True)
class EvalApprovalDecision:
    approved: bool
    reason: str


def _action_parts(action: dict) -> tuple[str, dict]:
    payload = action.get("payload") or {}
    if not isinstance(payload, dict):
        return "", {}
    tool = str(payload.get("tool") or "")
    tool_input = payload.get("input") or {}
    return tool, dict(tool_input) if isinstance(tool_input, dict) else {}


def _tokens(command: str) -> list[str]:
    try:
        return [
            token.strip("\"'")
            for token in shlex.split(command, posix=False)
            if token.strip("\"'")
        ]
    except ValueError:
        return []


def _path_is_within_target(token: str, target_root: Path) -> bool:
    candidate = Path(token)
    if not candidate.is_absolute():
        return ".." not in candidate.parts
    try:
        resolved = candidate.expanduser().resolve(strict=False)
        return (
            resolved == target_root
            or resolved.is_relative_to(target_root)
        )
    except (OSError, ValueError):
        return False


def _command_paths_are_safe(tokens: list[str], target_root: Path) -> bool:
    for token in tokens:
        if not (
            _DRIVE_PATH.match(token)
            or token.startswith("/")
        ):
            continue
        if token.lower().startswith(("http://", "https://")):
            continue
        if not _path_is_within_target(token, target_root):
            return False
    return True


def _is_safe_readonly(command: str, target_root: Path) -> bool:
    if not command or _DANGEROUS_COMMAND.search(command):
        return False
    if _SHELL_CONTROL.search(command):
        return False
    segments = [part.strip() for part in command.split("|") if part.strip()]
    if not segments:
        return False
    for segment in segments:
        tokens = _tokens(segment)
        if not tokens or tokens[0].lower() not in _READ_ONLY_EXECUTABLES:
            return False
        if not _command_paths_are_safe(tokens[1:], target_root):
            return False
    return True


def _is_safe_test(command: str) -> bool:
    if not command or _DANGEROUS_COMMAND.search(command):
        return False
    if _SHELL_CONTROL.search(command) or "|" in command:
        return False
    tokens = _tokens(command)
    if not tokens:
        return False
    lowered = tuple(token.lower() for token in tokens)
    for prefix in _TEST_COMMANDS:
        if lowered[:len(prefix)] == prefix:
            return True
    return False


def _is_safe_single_file_delete(command: str, target_root: Path) -> bool:
    if not command or _DANGEROUS_COMMAND.search(command):
        return False
    if _SHELL_CONTROL.search(command) or "|" in command:
        return False
    tokens = _tokens(command)
    if len(tokens) < 2:
        return False
    executable = tokens[0].lower()
    args = tokens[1:]
    if executable == "rm":
        args = [
            item for item in args
            if item not in {
                "-f",
                "--force",
                "-i",
                "-v",
                "--verbose",
            }
        ]
    elif executable == "del":
        args = [item for item in args if item not in {"/q", "/f"}]
    else:
        return False
    if len(args) != 1:
        return False
    path = args[0]
    if ".." in Path(path).parts:
        return False
    if not _path_is_within_target(path, target_root):
        return False
    return True


def _safe_bash(command: str, target_root: Path, *, writes: bool) -> bool:
    if _is_safe_readonly(command, target_root):
        return True
    if not writes:
        return False
    return (
        _is_safe_test(command)
        or _is_safe_single_file_delete(command, target_root)
    )


def decide_eval_approval(
    case: EvalCase,
    action: dict,
    *,
    target_root: str | Path,
) -> EvalApprovalDecision:
    tool, tool_input = _action_parts(action)
    root = Path(target_root).expanduser().resolve(strict=False) if target_root else None

    if not tool:
        return EvalApprovalDecision(False, "pending action has no tool")
    if case.approvals == "deny_all":
        return EvalApprovalDecision(False, "case policy is deny_all")

    if tool == "bash":
        command = str(tool_input.get("command") or "")
        if root is None:
            return EvalApprovalDecision(False, "bash requires a target root")
        if _DANGEROUS_COMMAND.search(command):
            return EvalApprovalDecision(False, "blocked destructive command")
        writes = case.approvals in {"auto_approve", "allow_list"}
        if _safe_bash(command, root, writes=writes):
            if case.approvals == "allow_list":
                matched = any(
                    re.search(pattern, command)
                    for pattern in case.allow_commands
                )
                if not matched:
                    return EvalApprovalDecision(
                        False,
                        "command did not match allow_commands",
                    )
            return EvalApprovalDecision(True, "approved by evaluation policy")
        return EvalApprovalDecision(
            False,
            "command is outside the evaluation allowlist",
        )

    policy = get_tool_policy(tool)
    if case.approvals == "auto_readonly":
        return EvalApprovalDecision(
            policy.read_only,
            "read-only tool" if policy.read_only else "write blocked by auto_readonly",
        )

    if case.approvals == "allow_list":
        if tool in {"target_restart", "target_deploy", "spawn_subagent"}:
            return EvalApprovalDecision(
                False,
                f"{tool} is not allowed by the evaluation allowlist",
            )
        if tool in {"target_write_file", "target_edit_file"}:
            path = str(tool_input.get("path") or "")
            if root is None or not path or not _path_is_within_target(path, root):
                return EvalApprovalDecision(False, "file path escapes target")
        subject = json.dumps(tool_input, ensure_ascii=False, sort_keys=True)
        matched = any(
            re.search(pattern, subject)
            for pattern in case.allow_commands
        )
        return EvalApprovalDecision(
            matched,
            "tool input matched allow_commands"
            if matched
            else "tool input did not match allow_commands",
        )

    if tool in {"target_write_file", "target_edit_file"} and root is not None:
        path = str(tool_input.get("path") or "")
        if path and _path_is_within_target(path, root):
            return EvalApprovalDecision(
                True,
                "target-scoped file write",
            )
        return EvalApprovalDecision(False, "file path escapes target")

    return EvalApprovalDecision(
        False,
        f"{tool} is not enabled for unattended evaluation",
    )


__all__ = ["EvalApprovalDecision", "decide_eval_approval"]

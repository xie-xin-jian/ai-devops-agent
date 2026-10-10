"""Target validation and server-side directory browsing."""

from __future__ import annotations

from pathlib import Path
import re
import time
import uuid

import agent.platform.config as config
from agent.targets.models import Target


MAX_BROWSE_ENTRIES = 500
SENSITIVE_NAMES = {
    ".env",
    ".env.local",
    "credentials",
    "id_rsa",
    "id_ed25519",
}
SENSITIVE_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}
SERVICE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_.@-]{1,255}$")


def allowed_roots() -> tuple[Path, ...]:
    return tuple(
        Path(path).expanduser().resolve()
        for path in getattr(config, "TARGET_BROWSE_ROOTS", ())
    )


def _ensure_browsable(path: Path, *, must_exist: bool = True) -> Path:
    roots = allowed_roots()
    if not roots:
        raise ValueError(
            "Target browsing is disabled. Configure TARGET_BROWSE_ROOTS."
        )
    if not path.is_absolute():
        raise ValueError("Target paths must be absolute")
    resolved = path.expanduser().resolve(strict=False)
    if not any(
        resolved == root or resolved.is_relative_to(root)
        for root in roots
    ):
        raise ValueError(f"Path is outside TARGET_BROWSE_ROOTS: {path}")
    if must_exist and not resolved.exists():
        raise ValueError(f"Target path does not exist: {resolved}")
    return resolved


def is_sensitive_path(path: Path) -> bool:
    return (
        path.name in SENSITIVE_NAMES
        or path.suffix.lower() in SENSITIVE_SUFFIXES
    )


def _validate_url(url: str) -> str:
    value = str(url or "").strip()
    if not value:
        return ""
    if not re.match(r"^https?://", value, re.IGNORECASE):
        raise ValueError("health_url must start with http:// or https://")
    return value


def validate_service_name(service: str) -> str:
    value = str(service or "").strip()
    if value and not SERVICE_NAME_PATTERN.fullmatch(value):
        raise ValueError(
            "service must be a valid systemd unit name "
            "(letters, digits, '.', '_', '@', '-')"
        )
    return value


def normalize_target(
    payload: dict,
    *,
    target_id: str = "",
    created_at: float | None = None,
) -> Target:
    root = _ensure_browsable(Path(str(payload.get("root") or "")))
    if not root.is_dir():
        raise ValueError(f"Target root is not a directory: {root}")

    name = str(payload.get("name") or root.name).strip()
    if not name:
        raise ValueError("Target name is required")

    identifier = str(target_id or "").strip()
    if not identifier:
        identifier = f"tgt_{uuid.uuid4().hex[:12]}"

    return Target(
        id=identifier,
        name=name,
        root=str(root),
        description=str(payload.get("description") or "").strip(),
        service=validate_service_name(str(payload.get("service") or "")),
        health_url=_validate_url(str(payload.get("health_url") or "")),
        deploy_command=str(payload.get("deploy_command") or "").strip(),
        restart_command=str(payload.get("restart_command") or "").strip(),
        log_path=str(payload.get("log_path") or "").strip(),
        created_at=float(created_at or time.time()),
        updated_at=time.time(),
    )


def browse_directories(path: str | None = None) -> dict:
    roots = allowed_roots()
    if not roots:
        return {
            "allowed_roots": [],
            "current": "",
            "parent": "",
            "entries": [],
            "selectable": False,
            "message": "Target browsing is disabled. Configure TARGET_BROWSE_ROOTS.",
        }

    if not path:
        entries = []
        for root in roots:
            if root.exists() and root.is_dir():
                entries.append({
                    "name": root.name or str(root),
                    "path": str(root),
                })
        return {
            "allowed_roots": [str(root) for root in roots],
            "current": "",
            "parent": "",
            "entries": entries,
            "selectable": False,
        }

    current = _ensure_browsable(Path(path))
    if not current.is_dir():
        raise ValueError(f"Browse path is not a directory: {current}")

    parent = ""
    if current.parent != current:
        try:
            candidate = _ensure_browsable(current.parent, must_exist=False)
            if any(
                candidate == root or candidate.is_relative_to(root)
                for root in roots
            ):
                parent = str(candidate)
        except ValueError:
            parent = ""

    entries = []
    for item in sorted(current.iterdir(), key=lambda value: value.name.lower()):
        if len(entries) >= MAX_BROWSE_ENTRIES:
            break
        try:
            resolved = item.resolve(strict=False)
            if not resolved.is_dir():
                continue
            if not any(
                resolved == root or resolved.is_relative_to(root)
                for root in roots
            ):
                continue
        except OSError:
            continue
        entries.append({"name": item.name, "path": str(resolved)})

    return {
        "allowed_roots": [str(root) for root in roots],
        "current": str(current),
        "parent": parent,
        "entries": entries,
        "selectable": True,
    }


__all__ = [
    "allowed_roots",
    "browse_directories",
    "is_sensitive_path",
    "normalize_target",
    "validate_service_name",
]

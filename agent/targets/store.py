"""JSON-backed target configuration store."""

from __future__ import annotations

import json
from pathlib import Path

import agent.platform.config as config
from agent.platform.storage import atomic_write_json, get_path_lock
from agent.targets.models import Target
from agent.targets.service import normalize_target


TARGETS_PATH = config.TARGETS_DIR / "targets.json"


class TargetStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or TARGETS_PATH)
        self._lock = get_path_lock(self.path)

    def _load_unlocked(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        if not isinstance(data, dict):
            return {}
        return {
            str(key): value
            for key, value in data.items()
            if isinstance(value, dict)
        }

    def _save_unlocked(self, records: dict[str, dict]) -> None:
        atomic_write_json(self.path, records)

    def list(self) -> list[Target]:
        with self._lock:
            records = self._load_unlocked().values()
        targets = [Target.from_dict(item) for item in records]
        return sorted(targets, key=lambda item: item.name.lower())

    def get(self, target_id: str) -> Target | None:
        with self._lock:
            data = self._load_unlocked().get(str(target_id or ""))
        return Target.from_dict(data) if data else None

    def create(self, payload: dict) -> Target:
        target = normalize_target(payload)
        with self._lock:
            records = self._load_unlocked()
            if target.id in records:
                raise ValueError(f"Target already exists: {target.id}")
            records[target.id] = target.to_dict()
            self._save_unlocked(records)
        return target

    def update(self, target_id: str, payload: dict) -> Target:
        with self._lock:
            records = self._load_unlocked()
            existing = records.get(str(target_id))
            if existing is None:
                raise KeyError(target_id)
            current = Target.from_dict(existing)
            target = normalize_target(
                {**current.to_dict(), **payload},
                target_id=current.id,
                created_at=current.created_at,
            )
            records[target.id] = target.to_dict()
            self._save_unlocked(records)
        return target

    def delete(self, target_id: str) -> None:
        with self._lock:
            records = self._load_unlocked()
            if str(target_id) not in records:
                raise KeyError(target_id)
            del records[str(target_id)]
            self._save_unlocked(records)


__all__ = ["TARGETS_PATH", "TargetStore"]

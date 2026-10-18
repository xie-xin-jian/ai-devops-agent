"""Database-backed target configuration store."""

from __future__ import annotations

from agent.persistence.repositories import targets as target_repo
from agent.targets.models import Target
from agent.targets.service import normalize_target


class TargetStore:
    """CRUD facade over the shared persistence database."""

    def list(self) -> list[Target]:
        targets = [
            Target.from_dict(item)
            for item in target_repo.fetch_targets()
        ]
        return sorted(targets, key=lambda item: item.name.lower())

    def get(self, target_id: str) -> Target | None:
        record = target_repo.fetch_target(target_id)
        return Target.from_dict(record) if record else None

    def create(self, payload: dict) -> Target:
        target = normalize_target(payload)
        if target_repo.fetch_target(target.id) is not None:
            raise ValueError(f"Target already exists: {target.id}")
        if not target_repo.upsert_target(target.to_dict(), force=True):
            raise RuntimeError("Failed to create target")
        return target

    def update(self, target_id: str, payload: dict) -> Target:
        existing = target_repo.fetch_target(target_id)
        if existing is None:
            raise KeyError(target_id)
        target = self._merge(Target.from_dict(existing), payload)
        if not target_repo.upsert_target(target.to_dict(), force=True):
            raise RuntimeError("Failed to update target")
        return target

    @staticmethod
    def _merge(current: Target, payload: dict) -> Target:
        return normalize_target(
            {**current.to_dict(), **payload},
            target_id=current.id,
            created_at=current.created_at,
        )

    def delete(self, target_id: str) -> None:
        if not target_repo.delete_target(target_id):
            raise KeyError(target_id)


__all__ = ["TargetStore"]

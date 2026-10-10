"""Target data model."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import time


@dataclass
class Target:
    id: str
    name: str
    root: str
    description: str = ""
    service: str = ""
    health_url: str = ""
    deploy_command: str = ""
    restart_command: str = ""
    log_path: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Target":
        return cls(
            id=str(data.get("id") or ""),
            name=str(data.get("name") or ""),
            root=str(data.get("root") or ""),
            description=str(data.get("description") or ""),
            service=str(data.get("service") or ""),
            health_url=str(data.get("health_url") or ""),
            deploy_command=str(data.get("deploy_command") or ""),
            restart_command=str(data.get("restart_command") or ""),
            log_path=str(data.get("log_path") or ""),
            created_at=float(data.get("created_at") or time.time()),
            updated_at=float(data.get("updated_at") or time.time()),
        )


__all__ = ["Target"]

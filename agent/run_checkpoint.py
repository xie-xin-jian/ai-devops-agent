"""Persistent Agent run checkpoints and safe resume helpers."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agent.config import RUNS_DIR
from agent.storage import atomic_write_text, get_path_lock


STATUS_RUNNING = "running"
STATUS_WAITING_APPROVAL = "waiting_approval"
STATUS_COMPLETED = "completed"
STATUS_CANCELED = "canceled"
STATUS_FAILED = "failed"
STATUS_INTERRUPTED = "interrupted"

VALID_STATUSES = {
    STATUS_RUNNING,
    STATUS_WAITING_APPROVAL,
    STATUS_COMPLETED,
    STATUS_CANCELED,
    STATUS_FAILED,
    STATUS_INTERRUPTED,
}

PHASE_INITIALIZED = "initialized"
PHASE_ACTION_SELECTED = "action_selected"
PHASE_MODEL_RESPONSE = "model_response"
PHASE_TOOLS_RUNNING = "tools_running"
PHASE_WAITING_APPROVAL = "waiting_approval"
PHASE_COMPLETED = "completed"
PHASE_CANCELED = "canceled"
PHASE_FAILED = "failed"


def serialize_block(block: Any) -> dict:
    if isinstance(block, dict):
        return {
            str(key): serialize_value(value)
            for key, value in block.items()
        }

    block_type = getattr(block, "type", "")
    if block_type == "text":
        return {
            "type": "text",
            "text": str(getattr(block, "text", "")),
        }
    if block_type == "tool_use":
        return {
            "type": "tool_use",
            "id": str(getattr(block, "id", "")),
            "name": str(getattr(block, "name", "")),
            "input": serialize_value(getattr(block, "input", {})),
        }
    if block_type == "tool_result":
        return {
            "type": "tool_result",
            "tool_use_id": str(getattr(block, "tool_use_id", "")),
            "content": serialize_value(getattr(block, "content", "")),
        }

    if hasattr(block, "__dict__"):
        return {
            str(key): serialize_value(value)
            for key, value in vars(block).items()
            if not str(key).startswith("_")
        }
    return {"type": block_type or "unknown", "value": str(block)}


def serialize_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {
            str(key): serialize_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [serialize_value(item) for item in value]
    return serialize_block(value)


def serialize_message(message: dict) -> dict:
    return {
        "role": str(message.get("role") or "user"),
        "content": serialize_value(message.get("content", "")),
    }


def _content_blocks(content) -> list:
    return content if isinstance(content, list) else []


def repair_pending_tool_results(messages: list[dict]) -> tuple[list[dict], list[str]]:
    """Pair interrupted tool_use blocks without re-executing them."""
    repaired = [serialize_message(message) for message in messages]
    repaired_ids = []

    index = 0
    while index < len(repaired):
        message = repaired[index]
        if message.get("role") != "assistant":
            index += 1
            continue

        tool_use_ids = [
            str(block.get("id") or "")
            for block in _content_blocks(message.get("content"))
            if isinstance(block, dict)
            and block.get("type") == "tool_use"
            and block.get("id")
        ]
        if not tool_use_ids:
            index += 1
            continue

        next_index = index + 1
        if (
            next_index < len(repaired)
            and repaired[next_index].get("role") == "user"
            and isinstance(repaired[next_index].get("content"), list)
        ):
            result_message = repaired[next_index]
            result_blocks = result_message["content"]
        else:
            result_blocks = []
            result_message = {"role": "user", "content": result_blocks}
            repaired.insert(next_index, result_message)

        existing_ids = {
            str(block.get("tool_use_id") or "")
            for block in result_blocks
            if isinstance(block, dict)
            and block.get("type") == "tool_result"
        }
        for tool_use_id in tool_use_ids:
            if tool_use_id in existing_ids:
                continue
            result_blocks.append({
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": (
                    "Error: previous run was interrupted before the "
                    "tool returned a result"
                ),
            })
            repaired_ids.append(tool_use_id)
        index += 1

    return repaired, repaired_ids


@dataclass
class RunCheckpoint:
    run_id: str
    session_id: str
    owner_id: str
    source: str = "chat"
    parent_run_id: str = ""
    resource_id: str = ""
    status: str = STATUS_RUNNING
    phase: str = PHASE_INITIALIZED
    user_message: str = ""
    action_code: str = ""
    messages: list[dict] = field(default_factory=list)
    recovery: dict = field(default_factory=dict)
    turn: int = 0
    pending_action_ids: list[str] = field(default_factory=list)
    sandbox_workspace: str = ""
    metadata: dict = field(default_factory=dict)
    last_error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    resume_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "RunCheckpoint":
        status = str(data.get("status") or STATUS_RUNNING)
        if status not in VALID_STATUSES:
            status = STATUS_RUNNING
        return cls(
            run_id=str(data.get("run_id") or f"run_{uuid.uuid4().hex}"),
            session_id=str(data.get("session_id") or ""),
            owner_id=str(data.get("owner_id") or ""),
            source=str(data.get("source") or "chat"),
            parent_run_id=str(data.get("parent_run_id") or ""),
            resource_id=str(data.get("resource_id") or ""),
            status=status,
            phase=str(data.get("phase") or PHASE_INITIALIZED),
            user_message=str(data.get("user_message") or ""),
            action_code=str(data.get("action_code") or ""),
            messages=[
                serialize_message(message)
                for message in (data.get("messages") or [])
                if isinstance(message, dict)
            ],
            recovery=dict(data.get("recovery") or {}),
            turn=max(0, int(data.get("turn") or 0)),
            pending_action_ids=[
                str(action_id)
                for action_id in (data.get("pending_action_ids") or [])
                if str(action_id).strip()
            ],
            sandbox_workspace=str(data.get("sandbox_workspace") or ""),
            metadata=dict(data.get("metadata") or {}),
            last_error=str(data.get("last_error") or ""),
            created_at=float(data.get("created_at") or time.time()),
            updated_at=float(data.get("updated_at") or time.time()),
            finished_at=data.get("finished_at"),
            resume_count=max(0, int(data.get("resume_count") or 0)),
        )


class RunCheckpointStore:
    def __init__(self, base_dir: str | Path | None = None):
        self.base_dir = Path(base_dir or RUNS_DIR)

    def _path(self, run_id: str) -> Path:
        safe_id = "".join(
            char if char.isalnum() or char in "-_" else "_"
            for char in str(run_id)
        )[:120]
        if not safe_id:
            raise ValueError("run_id is required")
        base = self.base_dir.resolve()
        path = (base / f"{safe_id}.json").resolve()
        if not path.is_relative_to(base):
            raise ValueError("run checkpoint path escapes base directory")
        return path

    def save(self, checkpoint: RunCheckpoint) -> RunCheckpoint:
        checkpoint.updated_at = time.time()
        path = self._path(checkpoint.run_id)
        lock = get_path_lock(path)
        with lock:
            atomic_write_text(
                path,
                json.dumps(
                    checkpoint.to_dict(),
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        return checkpoint

    def get(self, run_id: str) -> RunCheckpoint | None:
        path = self._path(run_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return None
        return RunCheckpoint.from_dict(data)

    def list(
        self,
        *,
        session_id: str | None = None,
        owner_id: str | None = None,
        status: str | None = None,
    ) -> list[RunCheckpoint]:
        if not self.base_dir.exists():
            return []
        checkpoints = []
        for path in self.base_dir.glob("*.json"):
            try:
                checkpoint = RunCheckpoint.from_dict(
                    json.loads(path.read_text(encoding="utf-8"))
                )
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
            if session_id and checkpoint.session_id != session_id:
                continue
            if owner_id and checkpoint.owner_id != owner_id:
                continue
            if status and checkpoint.status != status:
                continue
            checkpoints.append(checkpoint)
        return sorted(
            checkpoints,
            key=lambda item: (item.updated_at, item.run_id),
            reverse=True,
        )


__all__ = [
    "PHASE_ACTION_SELECTED",
    "PHASE_CANCELED",
    "PHASE_COMPLETED",
    "PHASE_FAILED",
    "PHASE_INITIALIZED",
    "PHASE_MODEL_RESPONSE",
    "PHASE_TOOLS_RUNNING",
    "PHASE_WAITING_APPROVAL",
    "RunCheckpoint",
    "RunCheckpointStore",
    "STATUS_CANCELED",
    "STATUS_COMPLETED",
    "STATUS_FAILED",
    "STATUS_INTERRUPTED",
    "STATUS_RUNNING",
    "STATUS_WAITING_APPROVAL",
    "repair_pending_tool_results",
    "serialize_block",
    "serialize_message",
    "serialize_value",
]

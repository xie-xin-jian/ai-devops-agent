"""In-process coordination for active Agent approval waits."""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time


@dataclass(frozen=True)
class ApprovalDecision:
    approved: bool
    actor: str = ""
    reason: str = ""


class ToolApprovalRequired(RuntimeError):
    def __init__(self, record):
        super().__init__(f"Approval required: {record.id}")
        self.record = record


class ApprovalCoordinator:
    """Waiters shared by the Agent run and the approval API."""

    def __init__(self):
        self._lock = threading.Lock()
        self._waiters: dict[str, dict] = {}

    def register(self, action_id: str) -> None:
        with self._lock:
            self._waiters[str(action_id)] = {
                "event": threading.Event(),
                "decision": None,
            }

    def resolve(
        self,
        action_id: str,
        *,
        approved: bool,
        actor: str = "",
        reason: str = "",
    ) -> bool:
        with self._lock:
            waiter = self._waiters.get(str(action_id))
            if waiter is None:
                return False
            waiter["decision"] = ApprovalDecision(
                approved=bool(approved),
                actor=str(actor or ""),
                reason=str(reason or ""),
            )
            waiter["event"].set()
            return True

    def wait(
        self,
        action_id: str,
        *,
        cancel_event=None,
        timeout_seconds: int = 1800,
    ) -> ApprovalDecision:
        with self._lock:
            waiter = self._waiters.get(str(action_id))
        if waiter is None:
            return ApprovalDecision(
                approved=False,
                reason="approval waiter is not registered",
            )

        deadline = time.monotonic() + max(1, int(timeout_seconds))
        while time.monotonic() < deadline:
            if cancel_event is not None and cancel_event.is_set():
                return ApprovalDecision(
                    approved=False,
                    actor="user",
                    reason="cancelled",
                )
            if waiter["event"].wait(0.2):
                return waiter["decision"] or ApprovalDecision(
                    approved=False,
                    reason="approval decision missing",
                )
        return ApprovalDecision(
            approved=False,
            reason="approval timed out",
        )

    def clear(self, action_id: str) -> None:
        with self._lock:
            self._waiters.pop(str(action_id), None)


approval_coordinator = ApprovalCoordinator()


__all__ = [
    "ApprovalDecision",
    "ApprovalCoordinator",
    "ToolApprovalRequired",
    "approval_coordinator",
]

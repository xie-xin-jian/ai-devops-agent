"""Agent run and session persistence."""


class RuntimePersistenceMixin:
    def _owner_id(self) -> str:
        return getattr(
            getattr(self, "principal", None),
            "id",
            "",
        )

    def _persist_session_state(self) -> None:
        store = getattr(self, "state_store", None)
        session_id = getattr(self, "session_id", "")
        if store is None or not session_id:
            return
        store.save_session(
            session_id,
            owner_id=self._owner_id(),
            messages=getattr(self, "messages", []),
        )

    def _persist_run_state(
        self,
        *,
        status: str,
        phase: str,
        safe_to_resume: bool,
        active_tool: str = "",
        interruption_reason: str = "",
    ) -> None:
        store = getattr(self, "state_store", None)
        run_id = getattr(self, "current_run_id", "")
        if store is None or not run_id:
            return
        self._persist_session_state()
        store.save_run(
            run_id,
            session_id=getattr(self, "session_id", ""),
            owner_id=self._owner_id(),
            source="chat",
            status=status,
            phase=phase,
            user_message=getattr(self, "_last_user_query", ""),
            messages=getattr(self, "messages", []),
            safe_to_resume=safe_to_resume,
            active_tool=active_tool,
            interruption_reason=interruption_reason,
        )

    def _persist_run_safe(self, phase: str = "model") -> None:
        self._persist_run_state(
            status="running",
            phase=phase,
            safe_to_resume=True,
        )

    def _mark_run_unsafe(self, tool_name: str) -> None:
        self._persist_run_state(
            status="running",
            phase="executing_tool",
            safe_to_resume=False,
            active_tool=tool_name,
        )

    def _finish_run_state(
        self,
        status: str,
        phase: str,
        reason: str = "",
        *,
        safe_to_resume: bool = False,
    ) -> None:
        self._persist_run_state(
            status=status,
            phase=phase,
            safe_to_resume=safe_to_resume,
            interruption_reason=reason,
        )

"""Memory tool registration."""

from __future__ import annotations


from agent.memory.policy import (
    can_manage_record,
    can_read_scope,
    can_write_scope,
    readable_scopes,
)
from agent.observability.audit import (
    RESULT_BLOCKED,
    RESULT_SUCCESS,
    SEVERITY_HIGH,
    SEVERITY_INFO,
)
from agent.platform.identity import system_admin_principal


class MemoryToolsMixin:
    def _add_memory_tools(self):
        tools = [
            {
                "name": "add_memory",
                "description": "Save a piece of information to long-term memory for future sessions.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "importance": {"type": "integer", "default": 3},
                        "category": {"type": "string", "default": "general"},
                        "memory_type": {
                            "type": "string",
                            "enum": [
                                "entity",
                                "semantic",
                                "episodic",
                                "procedural",
                            ],
                            "default": "semantic",
                        },
                        "entity_type": {"type": "string"},
                        "entity_key": {"type": "string"},
                        "entity_value": {"type": "string"},
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "scope": {"type": "string", "default": "global"},
                        "confidence": {
                            "type": "number",
                            "default": 0.8,
                        },
                    },
                    "required": ["content"],
                },
            },
            {
                "name": "search_memory",
                "description": "Search long-term memory for relevant past information.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "scope": {"type": "string"},
                        "memory_type": {
                            "type": "string",
                            "enum": [
                                "entity",
                                "semantic",
                                "episodic",
                                "procedural",
                            ],
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "update_memory",
                "description": "Update a long-term memory by id.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "memory_id": {"type": "string"},
                        "content": {"type": "string"},
                        "importance": {"type": "integer"},
                        "category": {"type": "string"},
                        "memory_type": {
                            "type": "string",
                            "enum": [
                                "entity",
                                "semantic",
                                "episodic",
                                "procedural",
                            ],
                        },
                        "entity_type": {"type": "string"},
                        "entity_key": {"type": "string"},
                        "entity_value": {"type": "string"},
                        "tags": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "scope": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["memory_id"],
                },
            },
            {
                "name": "archive_memory",
                "description": "Archive a long-term memory without deleting it.",
                "input_schema": {
                    "type": "object",
                    "properties": {"memory_id": {"type": "string"}},
                    "required": ["memory_id"],
                },
            },
            {
                "name": "delete_memory",
                "description": (
                    "Soft-delete a long-term memory. The record is retained "
                    "for audit and can be restored."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {"memory_id": {"type": "string"}},
                    "required": ["memory_id"],
                },
            },
            {
                "name": "restore_memory",
                "description": "Restore an archived or deleted memory.",
                "input_schema": {
                    "type": "object",
                    "properties": {"memory_id": {"type": "string"}},
                    "required": ["memory_id"],
                },
            },
            {
                "name": "approve_memory",
                "description": "Approve a candidate memory and make it active.",
                "input_schema": {
                    "type": "object",
                    "properties": {"memory_id": {"type": "string"}},
                    "required": ["memory_id"],
                },
            },
        ]

        principal = getattr(self, "principal", None) or system_admin_principal()
        session_id = getattr(self, "session_id", "")
        run_id = getattr(self, "current_run_id", "")

        def _memory_audit(
            event_type,
            memory,
            *,
            summary="",
            result=RESULT_SUCCESS,
            severity=SEVERITY_INFO,
        ):
            self._audit(
                event_type,
                f"{event_type}: {memory.get('id', '')}",
                summary=summary,
                result=result,
                severity=severity,
                correlation_id=memory.get("id", ""),
                payload={
                    "memory_id": memory.get("id", ""),
                    "scope": memory.get("scope", ""),
                    "owner_id": memory.get("owner_id", ""),
                    "session_id": memory.get("session_id", ""),
                    "run_id": memory.get("run_id", ""),
                    "status": memory.get("status", ""),
                },
            )

        def _deny(tool_name, reason):
            self._audit(
                "memory.access_denied",
                f"Memory access denied: {tool_name}",
                summary=reason,
                result=RESULT_BLOCKED,
                severity=SEVERITY_HIGH,
                tool_name=tool_name,
                correlation_id=run_id,
                payload={"reason": reason},
            )
            return f"Permission denied: {reason}"

        def _read_scopes(scope=None):
            if scope:
                if not can_read_scope(
                    principal,
                    scope,
                    session_id=session_id,
                ):
                    return None
                return {scope}
            return readable_scopes(
                principal,
                default_scope=self.memory_scope,
                session_id=session_id,
            )

        def _get_manageable(memory_id):
            memory = self.memory.get(memory_id)
            if memory is None:
                return None, f"Memory not found: {memory_id}"
            if not can_manage_record(
                principal,
                memory,
                session_id=session_id,
            ):
                return None, "memory scope is not accessible"
            return memory, None

        def _add_memory(
            content,
            importance=3,
            category="general",
            memory_type="semantic",
            entity_type="",
            entity_key="",
            entity_value="",
            tags=None,
            scope=None,
            confidence=0.8,
        ):
            target_scope = str(scope or self.memory_scope).strip() or "global"
            if not can_write_scope(
                principal,
                target_scope,
                session_id=session_id,
            ):
                return _deny(
                    "add_memory",
                    f"cannot write memory scope '{target_scope}'",
                )
            memory = self.memory.add(
                content,
                importance,
                category,
                memory_type=memory_type,
                entity_type=entity_type,
                entity_key=entity_key,
                entity_value=entity_value,
                tags=tags,
                scope=target_scope,
                owner_id=principal.id,
                session_id=session_id,
                run_id=run_id,
                confidence=confidence,
            )
            if memory.get("status") == "candidate":
                _memory_audit(
                    "memory.candidate_created",
                    memory,
                    summary=content[:300],
                )
                return (
                    f"Memory saved as candidate (id={memory['id']}): " f"{content[:80]}"
                )
            _memory_audit(
                "memory.created",
                memory,
                summary=content[:300],
            )
            return f"Memory saved (id={memory['id']}): {content[:80]}"

        def _search_memory(query, scope=None, memory_type=None):
            scopes = _read_scopes(scope)
            if scopes is None:
                return _deny(
                    "search_memory",
                    f"cannot read memory scope '{scope}'",
                )
            return self.memory.format_relevant(
                query,
                scopes=scopes,
                memory_type=memory_type,
            )

        def _update_memory(
            memory_id,
            content=None,
            importance=None,
            category=None,
            memory_type=None,
            entity_type=None,
            entity_key=None,
            entity_value=None,
            tags=None,
            scope=None,
            confidence=None,
        ):
            current, error = _get_manageable(memory_id)
            if error:
                return _deny("update_memory", error)
            if scope is not None and not can_write_scope(
                principal,
                scope,
                owner_id=current.get("owner_id", ""),
                session_id=session_id,
            ):
                return _deny(
                    "update_memory",
                    f"cannot move memory to scope '{scope}'",
                )
            memory = self.memory.update(
                memory_id,
                content=content,
                importance=importance,
                category=category,
                memory_type=memory_type,
                entity_type=entity_type,
                entity_key=entity_key,
                entity_value=entity_value,
                tags=tags,
                scope=scope,
                confidence=confidence,
            )
            _memory_audit(
                "memory.updated",
                memory,
                summary=content[:300] if content else "",
            )
            return f"Memory updated: {memory['id']} (version={memory['version']})"

        def _archive_memory(memory_id):
            _, error = _get_manageable(memory_id)
            if error:
                return _deny("archive_memory", error)
            memory = self.memory.archive(memory_id)
            _memory_audit("memory.archived", memory)
            return f"Memory archived: {memory['id']}"

        def _delete_memory(memory_id):
            _, error = _get_manageable(memory_id)
            if error:
                return _deny("delete_memory", error)
            memory = self.memory.delete(memory_id)
            _memory_audit("memory.deleted", memory)
            return f"Memory soft-deleted: {memory['id']}"

        def _restore_memory(memory_id):
            _, error = _get_manageable(memory_id)
            if error:
                return _deny("restore_memory", error)
            memory = self.memory.restore(memory_id)
            _memory_audit("memory.restored", memory)
            return f"Memory restored: {memory['id']}"

        def _approve_memory(memory_id):
            current, error = _get_manageable(memory_id)
            if error:
                return _deny("approve_memory", error)
            if current.get("status") != "candidate":
                return f"Error: memory {memory_id} is not a candidate"
            memory = self.memory.approve(memory_id)
            _memory_audit("memory.approved", memory)
            return f"Memory approved: {memory['id']}"

        handlers = {
            "add_memory": _add_memory,
            "search_memory": _search_memory,
            "update_memory": _update_memory,
            "archive_memory": _archive_memory,
            "delete_memory": _delete_memory,
            "restore_memory": _restore_memory,
            "approve_memory": _approve_memory,
        }
        self.tool_registry.register_many(tools, handlers)

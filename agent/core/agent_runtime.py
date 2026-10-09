"""Composed Agent runtime mixins."""

from agent.core.persistence import RuntimePersistenceMixin
from agent.core.pipeline import AgentPipelineMixin
from agent.core.tool_loop import ToolLoopMixin


class AgentRuntimeMixin(
    RuntimePersistenceMixin,
    ToolLoopMixin,
    AgentPipelineMixin,
):
    pass


__all__ = ["AgentRuntimeMixin"]

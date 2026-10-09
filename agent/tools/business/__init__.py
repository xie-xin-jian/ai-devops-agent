"""Business tool mixins grouped by domain."""

from agent.tools.business.automation import AutomationToolsMixin
from agent.tools.business.base import BusinessRegistrationMixin
from agent.tools.business.integrations import IntegrationToolsMixin
from agent.tools.business.knowledge import KnowledgeToolsMixin
from agent.tools.business.memory import MemoryToolsMixin
from agent.tools.business.tasks import TaskToolsMixin


class BusinessToolsMixin(
    TaskToolsMixin,
    KnowledgeToolsMixin,
    MemoryToolsMixin,
    AutomationToolsMixin,
    IntegrationToolsMixin,
    BusinessRegistrationMixin,
):
    pass


__all__ = ["BusinessToolsMixin"]

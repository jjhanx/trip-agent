"""Base A2A Agent Executor template."""

from abc import ABC, abstractmethod

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue


class BaseAgentExecutor(AgentExecutor, ABC):
    """Base class for all trip-agent A2A agents.

    Subclasses implement execute() and optionally cancel().
    """

    @abstractmethod
    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Process the incoming request and send results via event_queue."""
        pass

    async def cancel(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        """Handle task cancellation. Override if supported."""
        raise NotImplementedError("cancel not supported")

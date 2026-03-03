"""Booking Orchestrator Agent A2A Server."""

import uvicorn

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from agents.booking.executor import BookingOrchestratorExecutor


def main():
    card = AgentCard(
        name="Booking Orchestrator Agent",
        description="일정 확정 및 예약 안내",
        url="http://localhost:9006/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[AgentSkill(id="confirm_booking", name="Confirm booking", tags=["booking"])],
    )
    request_handler = DefaultRequestHandler(
        agent_executor=BookingOrchestratorExecutor(),
        task_store=InMemoryTaskStore(),
    )
    server = A2AStarletteApplication(agent_card=card, http_handler=request_handler)
    uvicorn.run(server.build(), host="0.0.0.0", port=9006)


if __name__ == "__main__":
    main()

"""Accommodation Agent A2A Server."""

import uvicorn

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from agents.accommodation.executor import AccommodationExecutor


def main():
    card = AgentCard(
        name="Accommodation Agent",
        description="숙소 검색 및 5개 후보 제시",
        url="http://localhost:9003/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[AgentSkill(id="search_hotels", name="Search hotels", tags=["hotel"])],
    )
    request_handler = DefaultRequestHandler(
        agent_executor=AccommodationExecutor(),
        task_store=InMemoryTaskStore(),
    )
    server = A2AStarletteApplication(agent_card=card, http_handler=request_handler)
    uvicorn.run(server.build(), host="0.0.0.0", port=9003)


if __name__ == "__main__":
    main()

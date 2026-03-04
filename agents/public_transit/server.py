"""Public Transit Agent A2A Server."""

import uvicorn

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from agents.public_transit.executor import PublicTransitExecutor


def main():
    card = AgentCard(
        name="Public Transit Agent",
        description="대중교통 검색",
        url="http://localhost:9005/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[
            AgentSkill(
                id="search_routes",
                name="Search transit routes",
                description="Search public transit routes and passes",
                tags=["transit"],
            )
        ],
    )
    request_handler = DefaultRequestHandler(
        agent_executor=PublicTransitExecutor(),
        task_store=InMemoryTaskStore(),
    )
    server = A2AStarletteApplication(agent_card=card, http_handler=request_handler)
    uvicorn.run(server.build(), host="0.0.0.0", port=9005)


if __name__ == "__main__":
    main()

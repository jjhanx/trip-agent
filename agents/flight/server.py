"""Flight Search Agent A2A Server."""

import uvicorn

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from agents.flight.executor import FlightSearchExecutor


def create_flight_agent_card(url: str = "http://localhost:9001/") -> AgentCard:
    return AgentCard(
        name="Flight Search Agent",
        description="항공편 검색 및 가격/마일리지순 정렬",
        url=url,
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[
            AgentSkill(
                id="search_flights",
                name="Search flights",
                description="Search flights by origin, destination, dates; returns sorted by price or miles",
                tags=["flight", "search", "travel"],
                examples=["Search flights ICN to KIX"],
            ),
        ],
    )


def main():
    request_handler = DefaultRequestHandler(
        agent_executor=FlightSearchExecutor(),
        task_store=InMemoryTaskStore(),
    )
    server = A2AStarletteApplication(
        agent_card=create_flight_agent_card(),
        http_handler=request_handler,
    )
    uvicorn.run(server.build(), host="0.0.0.0", port=9001)


if __name__ == "__main__":
    main()

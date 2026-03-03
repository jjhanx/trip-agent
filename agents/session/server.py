"""Session & Input Agent A2A Server - main entry point."""

import uvicorn

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from agents.session.executor import SessionExecutor


def create_session_agent_card(url: str = "http://localhost:9000/") -> AgentCard:
    return AgentCard(
        name="Trip Session Agent",
        description="여행 일정 설계 오케스트레이터 - 항공, 일정, 숙소, 현지 이동 통합",
        url=url,
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[
            AgentSkill(
                id="travel_planning",
                name="Travel planning",
                description="Full travel planning: flights, itinerary, accommodation, local transport",
                tags=["travel", "flight", "hotel", "itinerary"],
            ),
        ],
    )


def main():
    request_handler = DefaultRequestHandler(
        agent_executor=SessionExecutor(),
        task_store=InMemoryTaskStore(),
    )
    server = A2AStarletteApplication(
        agent_card=create_session_agent_card(),
        http_handler=request_handler,
    )
    uvicorn.run(server.build(), host="0.0.0.0", port=9000)


if __name__ == "__main__":
    main()

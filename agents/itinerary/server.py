"""Itinerary Planner Agent A2A Server."""

import uvicorn

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from agents.itinerary.executor import ItineraryPlannerExecutor


def main():
    card = AgentCard(
        name="Itinerary Planner Agent",
        description="일정 3안 설계",
        url="http://localhost:9002/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[
            AgentSkill(
                id="design_itinerary",
                name="Design itinerary",
                description="Design travel itineraries based on flight selection and preferences",
                tags=["itinerary"],
            )
        ],
    )
    request_handler = DefaultRequestHandler(
        agent_executor=ItineraryPlannerExecutor(),
        task_store=InMemoryTaskStore(),
    )
    server = A2AStarletteApplication(agent_card=card, http_handler=request_handler)
    uvicorn.run(server.build(), host="0.0.0.0", port=9002)


if __name__ == "__main__":
    main()

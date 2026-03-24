"""Rental Car Agent A2A Server."""

import uvicorn

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from agents.rental_car.executor import RentalCarExecutor


def main():
    card = AgentCard(
        name="Rental Car Agent",
        description="렌트카 검색",
        url="http://localhost:9004/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[
            AgentSkill(
                id="search_rentals",
                name="Search rentals",
                description="Rental step: Amadeus transfer quotes (airport↔city) when keys set; self-drive via EconomyBookings link; pickup/dropoff datetimes optional",
                tags=["rental"],
            )
        ],
    )
    request_handler = DefaultRequestHandler(
        agent_executor=RentalCarExecutor(),
        task_store=InMemoryTaskStore(),
    )
    server = A2AStarletteApplication(agent_card=card, http_handler=request_handler)
    uvicorn.run(server.build(), host="0.0.0.0", port=9004)


if __name__ == "__main__":
    main()

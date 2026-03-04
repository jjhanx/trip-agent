"""Unified server: Session Agent (A2A) + static frontend."""

import uvicorn
from pathlib import Path

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

from agents.session.executor import SessionExecutor


def create_app():
    card = AgentCard(
        name="Trip Session Agent",
        description="여행 일정 설계 오케스트레이터",
        url="http://localhost:9000/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[
            AgentSkill(
                id="travel_planning",
                name="Travel planning",
                description="Full travel planning: flights, itinerary, accommodation, local transport",
                tags=["travel"],
            )
        ],
    )
    request_handler = DefaultRequestHandler(
        agent_executor=SessionExecutor(),
        task_store=InMemoryTaskStore(),
    )
    a2a_app = A2AStarletteApplication(agent_card=card, http_handler=request_handler)
    a2a_built = a2a_app.build()
    frontend = Path(__file__).parent / "frontend"
    routes = [Mount("/", a2a_built)]
    if frontend.exists():
        routes = [
            Mount("/a2a", a2a_built),
            Mount("/", StaticFiles(directory=str(frontend), html=True)),
        ]
    else:
        routes = [Mount("/", a2a_built)]
    app = Starlette(routes=routes)
    return app


if __name__ == "__main__":
    uvicorn.run(create_app(), host="0.0.0.0", port=9000)

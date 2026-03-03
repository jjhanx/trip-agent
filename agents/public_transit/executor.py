"""Public Transit Agent - 대중교통 검색."""

import json

from a2a.server.agent_execution import RequestContext
from a2a.server.events import EventQueue

from agents.base_agent import BaseAgentExecutor
from config import Settings
from shared.utils import MCPClient

try:
    from a2a.server.events.event_factory import new_agent_text_message
except ImportError:
    from a2a.types import Message, MessagePart

    def new_agent_text_message(text: str) -> Message:
        return Message(role="agent", parts=[MessagePart(type="text", text=text)])


class PublicTransitExecutor(BaseAgentExecutor):
    """Public Transit Agent - calls Transit MCP."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.mcp = MCPClient(self.settings.transit_mcp_url)

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        user_input = context.get_user_input()
        if not user_input:
            await event_queue.enqueue_event(new_agent_text_message("입력이 없습니다."))
            return
        try:
            data = json.loads(user_input)
            origin = data.get("origin", "")
            destination = data.get("destination", "")
            date_time = data.get("date_time", "")
        except Exception as e:
            await event_queue.enqueue_event(new_agent_text_message(f"입력 오류: {e}"))
            return
        try:
            result = await self.mcp.call_tool(
                "search_routes",
                {
                    "origin": origin,
                    "destination": destination,
                    "date_time": date_time,
                },
            )
            text = result.get("text", json.dumps(result))
            routes = json.loads(text) if isinstance(text, str) else text
        except Exception:
            routes = [
                {
                    "route_id": "TR001",
                    "description": "Metro Line 1 -> Bus 101",
                    "duration_minutes": 35,
                },
                {
                    "route_id": "TR002",
                    "description": "Direct bus",
                    "duration_minutes": 50,
                    "pass_name": "City Pass 1-day",
                    "pass_price_krw": 15000,
                },
            ]
        await event_queue.enqueue_event(
            new_agent_text_message(json.dumps(routes, ensure_ascii=False))
        )

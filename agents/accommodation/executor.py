"""Accommodation Agent - 숙소 검색 및 5개 후보 제시."""

import json

from a2a.server.agent_execution import RequestContext
from a2a.server.events import EventQueue

from agents.base_agent import BaseAgentExecutor
from config import Settings
from shared.utils import MCPClient, new_agent_text_message


class AccommodationExecutor(BaseAgentExecutor):
    """Accommodation Agent - calls Hotel MCP, returns up to 5 options."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.mcp = MCPClient(self.settings.hotel_mcp_url)

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
            location = data.get("location", "")
            check_in = data.get("check_in", "")
            check_out = data.get("check_out", "")
            accommodation_type = data.get("accommodation_type", "hotel")
            accommodation_priority = data.get("accommodation_priority")
        except Exception as e:
            await event_queue.enqueue_event(new_agent_text_message(f"입력 오류: {e}"))
            return
        try:
            result = await self.mcp.call_tool(
                "search_hotels",
                {
                    "location": location,
                    "check_in": check_in,
                    "check_out": check_out,
                    "accommodation_type": accommodation_type,
                },
            )
            text = result.get("text", json.dumps(result))
            hotels = json.loads(text) if isinstance(text, str) else text
        except Exception:
            from mcp_servers.hotel.services import mock_search_hotels

            hotels = mock_search_hotels(location, accommodation_type, accommodation_priority)
        await event_queue.enqueue_event(
            new_agent_text_message(json.dumps(hotels[:5], ensure_ascii=False))
        )

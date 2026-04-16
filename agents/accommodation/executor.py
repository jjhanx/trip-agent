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
            travelers_total = data.get("travelers_total")
            selected_itinerary = data.get("selected_itinerary")
            itinerary_attraction_catalog = data.get("itinerary_attraction_catalog")
        except Exception as e:
            await event_queue.enqueue_event(new_agent_text_message(f"입력 오류: {e}"))
            return
        try:
            mcp_args = {
                "location": location,
                "check_in": check_in,
                "check_out": check_out,
                "accommodation_type": accommodation_type,
            }
            if accommodation_priority is not None:
                mcp_args["accommodation_priority_json"] = json.dumps(
                    accommodation_priority, ensure_ascii=False
                )
            if travelers_total is not None:
                mcp_args["travelers_total"] = travelers_total
            if selected_itinerary is not None:
                mcp_args["selected_itinerary_json"] = json.dumps(
                    selected_itinerary, ensure_ascii=False
                )
            if itinerary_attraction_catalog is not None:
                mcp_args["itinerary_attraction_catalog_json"] = json.dumps(
                    itinerary_attraction_catalog, ensure_ascii=False
                )
            result = await self.mcp.call_tool("search_hotels", mcp_args)
            text = result.get("text", json.dumps(result))
            hotels = json.loads(text) if isinstance(text, str) else text
        except Exception:
            from mcp_servers.hotel.services import run_hotel_search

            hotels = run_hotel_search(
                location,
                accommodation_type,
                accommodation_priority,
                travelers_total,
                selected_itinerary if isinstance(selected_itinerary, dict) else None,
                itinerary_attraction_catalog
                if isinstance(itinerary_attraction_catalog, list)
                else None,
                check_in,
                check_out,
                (self.settings.google_places_api_key or "").strip() or None,
                (self.settings.travelpayouts_api_token or "").strip() or None,
            )
        await event_queue.enqueue_event(
            new_agent_text_message(json.dumps(hotels[:5], ensure_ascii=False))
        )

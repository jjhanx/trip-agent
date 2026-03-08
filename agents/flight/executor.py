"""Flight Search Agent - 항공편 검색 및 가격순 정렬."""

import json

from a2a.server.agent_execution import RequestContext
from a2a.server.events import EventQueue

from agents.base_agent import BaseAgentExecutor
from shared.utils import new_agent_text_message
from config import Settings
from shared.models import TravelInput
from shared.utils import MCPClient


class FlightSearchExecutor(BaseAgentExecutor):
    """Flight Search Agent - calls Flight MCP and returns sorted results."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.mcp = MCPClient(self.settings.flight_mcp_url)

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
            travel = TravelInput.model_validate(data)
        except Exception as e:
            await event_queue.enqueue_event(new_agent_text_message(f"입력 오류: {e}"))
            return
        try:
            origin = travel.origin_airport_code or travel.origin
            dest = travel.destination_airport_code or travel.destination
            result = await self.mcp.call_tool(
                "search_flights",
                {
                    "origin": origin,
                    "destination": dest,
                    "start_date": travel.start_date.isoformat(),
                    "end_date": travel.end_date.isoformat(),
                    "seat_class": travel.seat_class.value,
                    "use_miles": travel.use_miles,
                },
            )
            text = result.get("text", json.dumps(result))
            parsed = json.loads(text) if isinstance(text, str) else text
            if isinstance(parsed, dict):
                flights = parsed.get("flights", parsed)
                warnings = parsed.get("warnings", [])
            else:
                flights = parsed if isinstance(parsed, list) else []
                warnings = []
            if isinstance(flights, list):
                if travel.use_miles:
                    flights.sort(key=lambda x: x.get("miles_required") or 999999)
                else:
                    flights.sort(key=lambda x: x.get("price_krw") or 999999)
            out = {"flights": flights, "warnings": warnings}
            await event_queue.enqueue_event(
                new_agent_text_message(json.dumps(out, ensure_ascii=False))
            )
        except Exception:
            # Fallback: multi_source or mock when MCP unavailable
            from config import Settings
            from mcp_servers.flight.services import multi_source_search_flights, mock_search_flights

            s = Settings()
            flights, warnings = multi_source_search_flights(
                travel.origin_airport_code or travel.origin,
                travel.destination_airport_code or travel.destination,
                travel.start_date.isoformat(),
                travel.end_date.isoformat(),
                travel.seat_class.value,
                travel.use_miles,
                amadeus_client_id=s.amadeus_client_id,
                amadeus_client_secret=s.amadeus_client_secret,
                amadeus_base_url=s.amadeus_base_url,
                kiwi_api_key=s.kiwi_api_key,
                rapidapi_key=s.rapidapi_key,
            )
            if travel.use_miles:
                flights.sort(key=lambda x: x.get("miles_required") or 999999)
            else:
                flights.sort(key=lambda x: x.get("price_krw") or 999999)
            out = {"flights": flights, "warnings": warnings}
            await event_queue.enqueue_event(
                new_agent_text_message(json.dumps(out, ensure_ascii=False))
            )

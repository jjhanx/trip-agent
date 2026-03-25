"""Rental Car Agent - 렌트카 검색."""

import json

from a2a.server.agent_execution import RequestContext
from a2a.server.events import EventQueue

from agents.base_agent import BaseAgentExecutor
from config import Settings
from shared.utils import MCPClient, new_agent_text_message


class RentalCarExecutor(BaseAgentExecutor):
    """Rental Car Agent - calls Rental Car MCP."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.mcp = MCPClient(self.settings.rental_car_mcp_url)

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
            pickup = data.get("pickup", "")
            dropoff = data.get("dropoff", "")
            start_date = data.get("start_date", "")
            end_date = data.get("end_date", "")
            car_type = data.get("car_type", "compact")
            passengers = data.get("passengers")
            pickup_datetime = data.get("pickup_datetime")
            dropoff_datetime = data.get("dropoff_datetime")
            pickup_airport_iata = data.get("pickup_airport_iata")
        except Exception as e:
            await event_queue.enqueue_event(new_agent_text_message(f"입력 오류: {e}"))
            return
        mcp_args = {
            "pickup": pickup,
            "dropoff": dropoff,
            "start_date": start_date,
            "end_date": end_date,
            "car_type": car_type,
        }
        if passengers is not None:
            mcp_args["passengers"] = passengers
        if pickup_datetime:
            mcp_args["pickup_datetime"] = pickup_datetime
        if dropoff_datetime:
            mcp_args["dropoff_datetime"] = dropoff_datetime
        if pickup_airport_iata:
            mcp_args["pickup_airport_iata"] = pickup_airport_iata
        try:
            result = await self.mcp.call_tool("search_rentals", mcp_args)
            text = result.get("text", json.dumps(result))
            if isinstance(text, str):
                text = text.strip()
                if text.startswith("\ufeff"):
                    text = text[1:].lstrip()
            rentals = json.loads(text) if isinstance(text, str) else text
        except Exception:
            from datetime import datetime

            from mcp_servers.rental_car.services import search_rentals_combined

            d1 = datetime.strptime(start_date, "%Y-%m-%d")
            d2 = datetime.strptime(end_date, "%Y-%m-%d")
            days = max(1, (d2 - d1).days)
            rentals = search_rentals_combined(
                pickup=pickup,
                dropoff=dropoff,
                car_type=car_type,
                days=days,
                passengers=passengers,
                start_date=start_date,
                end_date=end_date,
                travelpayouts_rental_booking_url=(
                    (self.settings.travelpayouts_rental_booking_url or "").strip() or None
                ),
                pickup_datetime=pickup_datetime if isinstance(pickup_datetime, str) else None,
                dropoff_datetime=dropoff_datetime if isinstance(dropoff_datetime, str) else None,
                pickup_airport_iata=pickup_airport_iata if isinstance(pickup_airport_iata, str) else None,
                amadeus_client_id=(self.settings.amadeus_client_id or "").strip() or None,
                amadeus_client_secret=(self.settings.amadeus_client_secret or "").strip() or None,
                serpapi_api_key=(self.settings.serpapi_api_key or "").strip() or None,
            )
        await event_queue.enqueue_event(
            new_agent_text_message(json.dumps(rentals, ensure_ascii=False))
        )

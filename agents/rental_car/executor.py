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
        try:
            result = await self.mcp.call_tool("search_rentals", mcp_args)
            text = result.get("text", json.dumps(result))
            rentals = json.loads(text) if isinstance(text, str) else text
        except Exception:
            from datetime import datetime

            from mcp_servers.rental_car.services import mock_search_rentals

            d1 = datetime.strptime(start_date, "%Y-%m-%d")
            d2 = datetime.strptime(end_date, "%Y-%m-%d")
            days = max(1, (d2 - d1).days)
            kwargs = {"pickup": pickup, "dropoff": dropoff, "car_type": car_type, "days": days}
            if passengers is not None:
                kwargs["passengers"] = passengers
            rentals = mock_search_rentals(**kwargs)
        await event_queue.enqueue_event(
            new_agent_text_message(json.dumps(rentals, ensure_ascii=False))
        )

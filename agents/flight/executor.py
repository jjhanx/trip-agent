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
            flight_leg = data.get("flight_leg")  # "outbound" | "return" | "multi_city_0", ...
            trip_type = data.get("trip_type", "round_trip")
            multi_cities = travel.multi_cities or data.get("multi_cities") or []

            if isinstance(flight_leg, str) and flight_leg.startswith("multi_city_"):
                # 다구간 i번째 구간
                try:
                    leg_idx = int(flight_leg.split("_")[-1])
                except (ValueError, IndexError):
                    leg_idx = 0
                if leg_idx < len(multi_cities):
                    leg = multi_cities[leg_idx]
                    origin = leg.get("origin", travel.origin)
                    dest = leg.get("destination", travel.destination)
                    leg_date = leg.get("date", travel.start_date.isoformat() if hasattr(travel.start_date, "isoformat") else str(travel.start_date))
                    start_date = end_date = leg_date
                    one_way = True
                else:
                    origin = travel.origin_airport_code or travel.origin
                    dest = travel.destination_airport_code or travel.destination
                    start_date = travel.start_date.isoformat()
                    end_date = travel.end_date.isoformat()
                    one_way = True
            elif flight_leg == "return" and trip_type != "round_trip":
                # 귀국편 (편도·다구간만: 왕복은 한 번에 검색)
                origin = travel.destination_airport_code or travel.destination
                dest = travel.origin_airport_code or travel.origin
                start_date = travel.end_date.isoformat()
                end_date = travel.end_date.isoformat()
                one_way = True
            else:
                # 가는 편, 편도, 또는 왕복(한 번에 검색)
                origin = travel.origin_airport_code or travel.origin
                dest = travel.destination_airport_code or travel.destination
                start_date = travel.start_date.isoformat()
                end_date = travel.end_date.isoformat()
                # 왕복: one_way=False → SerpApi가 출발+귀환 포함 총 왕복 가격 반환
                one_way = trip_type != "round_trip"

            params = {
                "origin": origin,
                "destination": dest,
                "start_date": start_date,
                "end_date": end_date,
                "seat_class": travel.seat_class.value,
                "use_miles": travel.use_miles,
                "one_way": one_way,
            }
            if travel.mileage_program:
                params["mileage_program"] = travel.mileage_program
            if travel.destination_airports and flight_leg != "return" and not (isinstance(flight_leg, str) and flight_leg.startswith("multi_city_")):
                params["destination_airports"] = travel.destination_airports
            if travel.date_flexibility_days and travel.date_flexibility_days > 0:
                params["date_flexibility_days"] = travel.date_flexibility_days
            result = await self.mcp.call_tool("search_flights", params)
            text = result.get("text", json.dumps(result))
            parsed = json.loads(text) if isinstance(text, str) else text
            if isinstance(parsed, dict):
                flights = parsed.get("flights", parsed)
                warnings = parsed.get("warnings", [])
                flight_search_api = parsed.get("flight_search_api") or ""
            else:
                flights = parsed if isinstance(parsed, list) else []
                warnings = []
                flight_search_api = ""
            # MCP가 추천순(선호 직항→선호 경유→나머지 직항→나머지 경유)으로 이미 정렬 반환
            out = {
                "flights": flights or [],
                "warnings": warnings or [],
                "flight_search_api": flight_search_api,
            }
            await event_queue.enqueue_event(
                new_agent_text_message(json.dumps(out, ensure_ascii=False))
            )
        except Exception:
            # Fallback: multi_source or mock when MCP unavailable
            from config import Settings
            from mcp_servers.flight.services import (
                multi_source_search_flights,
                multi_source_search_flights_multi_dest,
            )

            s = Settings()
            flex = travel.date_flexibility_days if travel.date_flexibility_days and travel.date_flexibility_days > 0 else None
            mc = travel.multi_cities or data.get("multi_cities") or []
            if isinstance(flight_leg, str) and flight_leg.startswith("multi_city_"):
                try:
                    leg_idx = int(flight_leg.split("_")[-1])
                except (ValueError, IndexError):
                    leg_idx = 0
                if leg_idx < len(mc):
                    leg = mc[leg_idx]
                    origin = leg.get("origin", travel.origin)
                    dest = leg.get("destination", travel.destination)
                    ld = leg.get("date", travel.start_date.isoformat())
                    start_d = end_d = ld
                    one_way = True
                else:
                    origin = travel.origin_airport_code or travel.origin
                    dest = travel.destination_airport_code or travel.destination
                    start_d, end_d = travel.start_date.isoformat(), travel.end_date.isoformat()
                    one_way = True
            elif flight_leg == "return" and data.get("trip_type") != "round_trip":
                origin = travel.destination_airport_code or travel.destination
                dest = travel.origin_airport_code or travel.origin
                start_d, end_d = travel.end_date.isoformat(), travel.end_date.isoformat()
                one_way = True
            else:
                origin = travel.origin_airport_code or travel.origin
                dest = travel.destination_airport_code or travel.destination
                start_d, end_d = travel.start_date.isoformat(), travel.end_date.isoformat()
                one_way = data.get("trip_type") != "round_trip"

            if travel.destination_airports and flight_leg != "return" and not (isinstance(flight_leg, str) and flight_leg.startswith("multi_city_")):
                flights, warnings, flight_search_api = multi_source_search_flights_multi_dest(
                    origin,
                    travel.destination_airports[:4],
                    start_d,
                    end_d,
                    travel.seat_class.value,
                    travel.use_miles,
                    mileage_program=travel.mileage_program,
                    travelpayouts_api_token=s.travelpayouts_api_token,
                    travelpayouts_marker=s.travelpayouts_marker,
                    serpapi_api_key=s.serpapi_api_key,
                    amadeus_client_id=s.amadeus_client_id,
                    amadeus_client_secret=s.amadeus_client_secret,
                    date_flexibility_days=flex,
                    one_way=one_way,
                )
            else:
                flights, warnings, flight_search_api = multi_source_search_flights(
                    origin,
                    dest,
                    start_d,
                    end_d,
                    travel.seat_class.value,
                    travel.use_miles,
                    mileage_program=travel.mileage_program,
                    travelpayouts_api_token=s.travelpayouts_api_token,
                    travelpayouts_marker=s.travelpayouts_marker,
                    serpapi_api_key=s.serpapi_api_key,
                    amadeus_client_id=s.amadeus_client_id,
                    amadeus_client_secret=s.amadeus_client_secret,
                    date_flexibility_days=flex,
                    one_way=one_way,
                )
            # multi_source_search가 추천순으로 이미 정렬 반환
            out = {"flights": flights, "warnings": warnings, "flight_search_api": flight_search_api}
            await event_queue.enqueue_event(
                new_agent_text_message(json.dumps(out, ensure_ascii=False))
            )

"""Session & Input Agent - 오케스트레이터.

사용자 입력 검증 후 Flight, Itinerary, Accommodation, Rental/Transit, Booking Agent를 호출.
"""

import json

from a2a.server.agent_execution import RequestContext
from a2a.server.events import EventQueue

from agents.base_agent import BaseAgentExecutor
from config import Settings
from shared.models import TravelInput, LocalTransportType
from shared.utils import A2AClient, new_agent_text_message


def _extract_rental_dates_from_flight(selected_flight: dict | None, fallback_start: str, fallback_end: str) -> tuple[str, str]:
    """선택한 항공편의 현지 도착일·출발일을 렌트카 시작일·반납일로 추출.

    - 왕복: outbound.arrival → start_date, return.departure → end_date
    - 편도: outbound.arrival → start_date, fallback_end → end_date
    - 다구간: 첫 leg 도착 → start_date, 마지막 leg 출발 → end_date
    """
    if not selected_flight or not isinstance(selected_flight, dict):
        return fallback_start, fallback_end

    def _date_only(s: str | None) -> str | None:
        if not s or not isinstance(s, str):
            return None
        if len(s) >= 10 and s[4] == "-" and s[7] == "-":
            return s[:10]
        return None

    trip_type = selected_flight.get("_trip_type") or "round_trip"
    legs = selected_flight.get("legs")  # multi_city

    if legs and isinstance(legs, list) and len(legs) > 0:
        first = legs[0]
        last = legs[-1]
        start = _date_only((first.get("arrival") or first.get("departure")) if isinstance(first, dict) else None)
        end = _date_only((last.get("departure") or last.get("arrival")) if isinstance(last, dict) else None)
        return start or fallback_start, end or fallback_end

    outbound = selected_flight.get("outbound")
    ret = selected_flight.get("return")
    if not outbound:
        return fallback_start, fallback_end
    start = _date_only(outbound.get("arrival") if isinstance(outbound, dict) else None) or fallback_start
    if ret and isinstance(ret, dict):
        end = _date_only(ret.get("departure")) or fallback_end
    else:
        end = fallback_end
    return start, end


def _total_passengers(travel) -> int:
    """일행 총 인원 (성인 남·여 + 아동)."""
    t = getattr(travel, "travelers", None)
    if not t:
        return 1
    return max(1, (getattr(t, "male", 0) or 0) + (getattr(t, "female", 0) or 0) + (getattr(t, "children", 0) or 0))


class SessionExecutor(BaseAgentExecutor):
    """Session Agent - orchestrates Flight, Itinerary, Accommodation, Local Transport, Booking."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.clients = {
            "flight": A2AClient(self.settings.flight_agent_url),
            "itinerary": A2AClient(self.settings.itinerary_agent_url),
            "accommodation": A2AClient(self.settings.accommodation_agent_url),
            "rental_car": A2AClient(self.settings.rental_car_agent_url),
            "transit": A2AClient(self.settings.transit_agent_url),
            "booking": A2AClient(self.settings.booking_agent_url),
        }

    async def _call_agent(self, name: str, payload: dict) -> str | None:
        try:
            return await self.clients[name].send_message(json.dumps(payload, default=str))
        except Exception:
            return None

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        try:
            await self._execute(context, event_queue)
        except Exception as e:
            await event_queue.enqueue_event(
                new_agent_text_message(json.dumps({"error": str(e)}, ensure_ascii=False))
            )

    async def _execute(
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

        base = travel.model_dump(mode="json")
        base["start_date"] = travel.start_date.isoformat()
        base["end_date"] = travel.end_date.isoformat()
        base["preference"] = travel.preference.model_dump()
        selected_flight = data.get("selected_flight")
        selected_itinerary = data.get("selected_itinerary")
        selected_accommodation = data.get("selected_accommodation")
        selected_local_transport = data.get("selected_local_transport")
        flight_leg = data.get("flight_leg")  # "outbound" | "return" | "multi_city_0", ...
        selected_outbound_flight = data.get("selected_outbound_flight")
        selected_multi_city_flights = data.get("selected_multi_city_flights") or []
        multi_cities = getattr(travel, "multi_cities", None) or data.get("multi_cities") or []

        def _is_flight_complete(sf) -> bool:
            if not sf:
                return False
            if travel.trip_type == "one_way":
                return bool(sf.get("outbound") if isinstance(sf, dict) else sf)
            if travel.trip_type == "round_trip":
                return bool(sf.get("outbound")) and bool(sf.get("return"))
            if travel.trip_type == "multi_city":
                legs = sf.get("legs") if isinstance(sf, dict) else []
                return len(legs) >= len(multi_cities) if multi_cities else bool(legs)
            return bool(sf)

        flight_complete = _is_flight_complete(selected_flight)

        if selected_flight and selected_itinerary and selected_accommodation:
            resp = await self._call_agent(
                "booking",
                {
                    "confirmed_itinerary": selected_itinerary,
                    "selected_flight": selected_flight,
                    "selected_accommodation": selected_accommodation,
                },
            )
            if resp:
                await event_queue.enqueue_event(new_agent_text_message(resp))
            else:
                guidance = {
                    "status": "confirmed",
                    "summary": "일정이 확정되었습니다.",
                    "steps": [
                        {"order": 1, "item": "항공편", "details": selected_flight},
                        {"order": 2, "item": "숙소", "details": selected_accommodation},
                        {"order": 3, "item": "일정", "details": selected_itinerary},
                    ],
                }
                await event_queue.enqueue_event(
                    new_agent_text_message(json.dumps(guidance, ensure_ascii=False))
                )
            return

        if selected_flight and selected_itinerary and not selected_accommodation:
            acc_priority = [t.value for t in travel.accommodation_priority] if travel.accommodation_priority else [travel.accommodation_type.value]
            acc_payload = {
                "location": travel.destination,
                "check_in": travel.start_date.isoformat(),
                "check_out": travel.end_date.isoformat(),
                "accommodation_type": travel.accommodation_type.value,
                "accommodation_priority": acc_priority,
            }
            acc_resp = await self._call_agent("accommodation", acc_payload)
            if not acc_resp:
                from mcp_servers.hotel.services import mock_search_hotels

                acc_resp = json.dumps(
                    mock_search_hotels(travel.destination, travel.accommodation_type.value)
                )
            start_d, end_d = _extract_rental_dates_from_flight(
                selected_flight, travel.start_date.isoformat(), travel.end_date.isoformat()
            )
            lt_payload = {
                "pickup": travel.destination,
                "dropoff": travel.destination,
                "start_date": start_d,
                "end_date": end_d,
                "origin": travel.origin,
                "destination": travel.destination,
                "date_time": start_d,
                "passengers": _total_passengers(travel),
            }
            if travel.local_transport == LocalTransportType.RENTAL_CAR:
                lt_resp = await self._call_agent("rental_car", lt_payload)
                if not lt_resp:
                    from mcp_servers.rental_car.services import mock_search_rentals
                    from datetime import datetime

                    d1 = datetime.strptime(lt_payload["start_date"], "%Y-%m-%d")
                    d2 = datetime.strptime(lt_payload["end_date"], "%Y-%m-%d")
                    days = max(1, (d2 - d1).days)
                    lt_resp = json.dumps(
                        mock_search_rentals(
                            lt_payload["pickup"],
                            lt_payload["dropoff"],
                            "compact",
                            days,
                            passengers=lt_payload["passengers"],
                        )
                    )
            else:
                lt_resp = await self._call_agent("transit", lt_payload)
                if not lt_resp:
                    lt_resp = json.dumps([
                        {"route_id": "TR001", "description": "Metro + Bus", "duration_minutes": 40},
                        {"route_id": "TR002", "description": "City Pass", "pass_price_krw": 15000},
                    ])
            result = {
                "step": "accommodation_and_transport",
                "accommodations": json.loads(acc_resp) if acc_resp and acc_resp.startswith("[") else acc_resp or [],
                "local_transport": json.loads(lt_resp) if lt_resp and lt_resp.startswith("[") else lt_resp or [],
            }
            await event_queue.enqueue_event(
                new_agent_text_message(json.dumps(result, ensure_ascii=False))
            )
            return

        if flight_complete and selected_local_transport and not selected_itinerary:
            it_payload = {
                "destination": travel.destination,
                "start_date": travel.start_date.isoformat(),
                "end_date": travel.end_date.isoformat(),
                "preference": travel.preference.model_dump(),
                "selected_flight": selected_flight,
            }
            resp = await self._call_agent("itinerary", it_payload)
            if resp:
                await event_queue.enqueue_event(new_agent_text_message(resp))
            else:
                from agents.itinerary.executor import _mock_itineraries
                from datetime import datetime

                d1 = datetime.strptime(travel.start_date.isoformat(), "%Y-%m-%d")
                d2 = datetime.strptime(travel.end_date.isoformat(), "%Y-%m-%d")
                days = max(1, (d2 - d1).days)
                itineraries = _mock_itineraries(
                    travel.destination, days, travel.preference.model_dump()
                )
                await event_queue.enqueue_event(
                    new_agent_text_message(json.dumps(itineraries, ensure_ascii=False))
                )
            return

        if flight_complete and not selected_local_transport:
            start_d, end_d = _extract_rental_dates_from_flight(
                selected_flight, travel.start_date.isoformat(), travel.end_date.isoformat()
            )
            lt_payload = {
                "pickup": travel.destination,
                "dropoff": travel.destination,
                "start_date": start_d,
                "end_date": end_d,
                "origin": travel.origin,
                "destination": travel.destination,
                "date_time": start_d,
                "passengers": _total_passengers(travel),
            }
            if travel.local_transport == LocalTransportType.RENTAL_CAR:
                lt_resp = await self._call_agent("rental_car", lt_payload)
                if not lt_resp:
                    from mcp_servers.rental_car.services import mock_search_rentals
                    from datetime import datetime

                    d1 = datetime.strptime(lt_payload["start_date"], "%Y-%m-%d")
                    d2 = datetime.strptime(lt_payload["end_date"], "%Y-%m-%d")
                    days = max(1, (d2 - d1).days)
                    lt_resp = json.dumps(
                        mock_search_rentals(
                            lt_payload["pickup"],
                            lt_payload["dropoff"],
                            "compact",
                            days,
                            passengers=lt_payload["passengers"],
                        )
                    )
            else:
                lt_resp = await self._call_agent("transit", lt_payload)
                if not lt_resp:
                    lt_resp = json.dumps([
                        {"route_id": "TR001", "description": "Metro + Bus", "duration_minutes": 40},
                        {"route_id": "TR002", "description": "City Pass", "pass_price_krw": 15000},
                    ])
            result = {
                "step": "rental",
                "local_transport": json.loads(lt_resp) if lt_resp and lt_resp.startswith("[") else lt_resp or [],
            }
            await event_queue.enqueue_event(
                new_agent_text_message(json.dumps(result, ensure_ascii=False))
            )
            return

        flight_payload = dict(base)
        if "multi_cities" not in flight_payload and multi_cities:
            flight_payload["multi_cities"] = multi_cities
        if flight_leg:
            flight_payload["flight_leg"] = flight_leg
        if selected_outbound_flight:
            flight_payload["selected_outbound_flight"] = selected_outbound_flight
        if selected_multi_city_flights:
            flight_payload["selected_multi_city_flights"] = selected_multi_city_flights
        if travel.trip_type == "round_trip" and not flight_complete and not flight_leg:
            flight_payload["flight_leg"] = "outbound"
        if travel.trip_type == "one_way" and not flight_complete:
            flight_payload["flight_leg"] = "outbound"
        if travel.trip_type == "multi_city" and multi_cities and not flight_leg:
            flight_payload["flight_leg"] = "multi_city_0"

        flight_resp = await self._call_agent("flight", flight_payload)
        if flight_resp:
            await event_queue.enqueue_event(new_agent_text_message(flight_resp))
        else:
            from config import Settings
            from mcp_servers.flight.services import (
                multi_source_search_flights,
                multi_source_search_flights_multi_dest,
            )

            s = Settings()
            flex = travel.date_flexibility_days if travel.date_flexibility_days and travel.date_flexibility_days > 0 else None
            leg = flight_payload.get("flight_leg")

            if leg == "return":
                origin = travel.destination_airport_code or travel.destination
                dest = travel.origin_airport_code or travel.origin
                start_d = end_d = travel.end_date.isoformat()
                one_way = True
            elif isinstance(leg, str) and leg.startswith("multi_city_"):
                try:
                    idx = int(leg.split("_")[-1])
                except (ValueError, IndexError):
                    idx = 0
                mc = multi_cities or []
                if idx < len(mc):
                    lg = mc[idx]
                    origin = lg.get("origin", travel.origin)
                    dest = lg.get("destination", travel.destination)
                    start_d = end_d = lg.get("date", travel.start_date.isoformat())
                    one_way = True
                else:
                    origin = travel.origin_airport_code or travel.origin
                    dest = travel.destination_airport_code or travel.destination
                    start_d, end_d = travel.start_date.isoformat(), travel.end_date.isoformat()
                    one_way = True
            else:
                origin = travel.origin_airport_code or travel.origin
                dest = travel.destination_airport_code or travel.destination
                start_d, end_d = travel.start_date.isoformat(), travel.end_date.isoformat()
                one_way = travel.trip_type == "one_way" or leg == "outbound"

            if travel.destination_airports and leg != "return" and not (isinstance(leg, str) and leg.startswith("multi_city_")):
                flights, warnings = multi_source_search_flights_multi_dest(
                    origin,
                    travel.destination_airports[:4],
                    start_d,
                    end_d,
                    travel.seat_class.value,
                    travel.use_miles,
                    mileage_program=travel.mileage_program,
                    serpapi_api_key=s.serpapi_api_key,
                    amadeus_client_id=s.amadeus_client_id,
                    amadeus_client_secret=s.amadeus_client_secret,
                    date_flexibility_days=flex,
                    one_way=one_way,
                )
            else:
                flights, warnings = multi_source_search_flights(
                    origin,
                    dest,
                    start_d,
                    end_d,
                    travel.seat_class.value,
                    travel.use_miles,
                    mileage_program=travel.mileage_program,
                    serpapi_api_key=s.serpapi_api_key,
                    amadeus_client_id=s.amadeus_client_id,
                    amadeus_client_secret=s.amadeus_client_secret,
                    date_flexibility_days=flex,
                    one_way=one_way,
                )
            out = {"flights": flights, "warnings": warnings}
            await event_queue.enqueue_event(
                new_agent_text_message(json.dumps(out, ensure_ascii=False))
            )

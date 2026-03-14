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

        if selected_flight and selected_itinerary:
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
            lt_payload = {
                "pickup": travel.destination,
                "dropoff": travel.destination,
                "start_date": travel.start_date.isoformat(),
                "end_date": travel.end_date.isoformat(),
                "origin": travel.origin,
                "destination": travel.destination,
                "date_time": travel.start_date.isoformat(),
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

        if selected_flight:
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

        flight_resp = await self._call_agent("flight", base)
        if flight_resp:
            await event_queue.enqueue_event(new_agent_text_message(flight_resp))
        else:
            from config import Settings
            from mcp_servers.flight.services import (
                multi_source_search_flights,
                multi_source_search_flights_multi_dest,
            )

            s = Settings()
            origin = travel.origin_airport_code or travel.origin
            if travel.destination_airports:
                flights, warnings = multi_source_search_flights_multi_dest(
                    origin,
                    travel.destination_airports[:4],
                    travel.start_date.isoformat(),
                    travel.end_date.isoformat(),
                    travel.seat_class.value,
                    travel.use_miles,
                    mileage_program=travel.mileage_program,
                    serpapi_api_key=s.serpapi_api_key,
                )
            else:
                destination = travel.destination_airport_code or travel.destination
                flights, warnings = multi_source_search_flights(
                    origin,
                    destination,
                    travel.start_date.isoformat(),
                    travel.end_date.isoformat(),
                    travel.seat_class.value,
                    travel.use_miles,
                    mileage_program=travel.mileage_program,
                    serpapi_api_key=s.serpapi_api_key,
                )
            # multi_source_search가 추천순으로 이미 정렬 반환
            out = {"flights": flights, "warnings": warnings}
            await event_queue.enqueue_event(
                new_agent_text_message(json.dumps(out, ensure_ascii=False))
            )

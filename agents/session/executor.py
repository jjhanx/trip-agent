"""Session & Input Agent - 오케스트레이터.

사용자 입력 검증 후 Flight, Itinerary, Accommodation, Rental/Transit, Booking Agent를 호출.
"""

import json
import logging
import re
from datetime import datetime, timedelta

from a2a.server.agent_execution import RequestContext
from a2a.server.events import EventQueue

from agents.base_agent import BaseAgentExecutor
from config import Settings
from shared.models import TravelInput, LocalTransportType
from shared.utils import A2AClient, new_agent_text_message

logger = logging.getLogger(__name__)


def _carrier_code_from_outbound_flight(f: dict | None) -> str | None:
    if not f or not isinstance(f, dict):
        return None
    fn = (f.get("flight_number") or "").strip().upper().replace(" ", "")
    m = re.match(r"^([A-Z]{2,3})\d", fn)
    return m.group(1)[:2] if m else None


def _parse_agent_json_array(raw: str | list | None) -> list:
    """MCP/A2A 텍스트에 선행 공백·BOM·짧은 머리말·마크다운 코드펜스가 있어도 JSON 배열로 파싱.

    `startswith('[')` 만으로는 실패하는 경우(UTF-8 BOM, \\n 접두)에도 목록이 비지 않게 합니다.
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if not isinstance(raw, str):
        return []
    s = raw.strip()
    if s.startswith("\ufeff"):
        s = s[1:].lstrip()
    if not s:
        return []
    if "```" in s:
        for ch in s.split("```"):
            t = ch.strip()
            if t.lower().startswith("json"):
                t = t[4:].lstrip()
            if t.startswith("["):
                s = t
                break
    if s.startswith("["):
        try:
            out = json.loads(s)
            return out if isinstance(out, list) else []
        except json.JSONDecodeError:
            pass
    i = s.find("[")
    if i >= 0:
        try:
            out = json.loads(s[i:])
            return out if isinstance(out, list) else []
        except json.JSONDecodeError:
            pass
    return []


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


def _transit_trip_days(start_d: str, end_d: str) -> int:
    """현지 체류 일수(시작일·종료일 포함) — 교통패스 조회용."""
    try:
        a = datetime.strptime((start_d or "")[:10], "%Y-%m-%d").date()
        b = datetime.strptime((end_d or "")[:10], "%Y-%m-%d").date()
        return max(1, (b - a).days + 1)
    except (ValueError, TypeError):
        return 1


def _parse_local_dt(s: str) -> datetime | None:
    """항공 응답의 'YYYY-MM-DDTHH:MM(:SS)?' 로컬 시각 파싱."""
    if not s or not isinstance(s, str) or len(s) < 16:
        return None
    t = s.strip().replace(" ", "T")
    if len(t) >= 19:
        try:
            return datetime.strptime(t[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            pass
    try:
        return datetime.strptime(t[:16], "%Y-%m-%dT%H:%M")
    except ValueError:
        return None


def _rental_pickup_after_arrival(arrival_str: str | None) -> str | None:
    """도착 시각 + 1시간 → 렌트 픽업."""
    dt = _parse_local_dt(arrival_str or "")
    if dt is None:
        return None
    return (dt + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")


def _rental_dropoff_before_departure(departure_str: str | None) -> str | None:
    """출발 시각 - 2시간 → 렌트 반납(공항 이동 여유)."""
    dt = _parse_local_dt(departure_str or "")
    if dt is None:
        return None
    return (dt - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")


def _normalize_rental_datetime(s: str | None) -> str | None:
    """datetime-local / ISO 혼용 → YYYY-MM-DDTHH:MM:SS."""
    if not s or not isinstance(s, str):
        return None
    t = s.strip().replace(" ", "T")
    if len(t) == 16 and t[10] == "T":
        return t + ":00"
    if len(t) >= 19:
        return t[:19]
    if len(t) >= 10:
        return t[:10] + "T12:00:00"
    return None


def _merge_rental_search(lt: dict, rs: dict | None) -> dict:
    """프론트 rental_search로 픽업·반납 일시·공항·날짜 덮어쓰기."""
    if not rs or not isinstance(rs, dict):
        return lt
    out = {**lt}
    pdt = _normalize_rental_datetime(rs.get("pickup_datetime"))
    ddt = _normalize_rental_datetime(rs.get("dropoff_datetime"))
    if pdt:
        out["pickup_datetime"] = pdt
        out["date_time"] = pdt
        out["start_date"] = pdt[:10]
    if ddt:
        out["dropoff_datetime"] = ddt
        out["end_date"] = ddt[:10]
    pi = (rs.get("pickup_iata") or rs.get("pickup_airport_iata") or "").strip().upper()[:3]
    if len(pi) == 3:
        out["pickup"] = pi
        out["dropoff"] = pi
        out["pickup_airport_iata"] = pi
        out["dropoff_airport_iata"] = pi
    return out


def _build_local_transport_payload(
    selected_flight: dict | None,
    travel: TravelInput,
    start_d: str,
    end_d: str,
) -> dict:
    """렌트카·대중교통 MCP: 항공 도착/출발·공항 코드 반영.

    렌트 픽업/반납 시각: 도착 +1시간, 귀국(또는 마지막 구간) 출발 -2시간.
    date_time(대중교통 등)은 여전히 실제 도착 시각 기준.
    """
    passengers = _total_passengers(travel)
    dac = (travel.destination_airport_code or "").strip().upper()[:3] or None
    if len(dac or "") != 3:
        dac = None
    oac = (travel.origin_airport_code or "").strip().upper()[:3] or None
    if len(oac or "") != 3:
        oac = None
    city = (travel.destination or "").strip()
    date_time = (start_d or "")[:10] if len(start_d or "") >= 10 else start_d
    pickup_dt: str | None = None
    dropoff_dt: str | None = None

    if selected_flight and isinstance(selected_flight, dict):
        ob = selected_flight.get("outbound")
        legs = selected_flight.get("legs")
        ret = selected_flight.get("return")
        if isinstance(legs, list) and len(legs) > 0 and isinstance(legs[0], dict):
            first = legs[0]
            leg_dest = (first.get("destination") or "").strip().upper()[:3]
            if len(leg_dest) == 3:
                dac = dac or leg_dest
            arr = first.get("arrival") or first.get("departure")
            if isinstance(arr, str) and len(arr) >= 16:
                date_time = arr[:19]
                pickup_dt = _rental_pickup_after_arrival(arr)
            last = legs[-1] if len(legs) > 1 else first
            if isinstance(last, dict):
                dep = last.get("departure") or last.get("arrival")
                if isinstance(dep, str) and len(dep) >= 16:
                    dropoff_dt = _rental_dropoff_before_departure(dep)
        elif isinstance(ob, dict):
            leg_dest = (ob.get("destination") or "").strip().upper()[:3]
            if len(leg_dest) == 3:
                dac = dac or leg_dest
            arr = ob.get("arrival")
            if isinstance(arr, str) and len(arr) >= 16:
                date_time = arr[:19]
                pickup_dt = _rental_pickup_after_arrival(arr)
            if isinstance(ret, dict):
                dep = ret.get("departure")
                if isinstance(dep, str) and len(dep) >= 16:
                    dropoff_dt = _rental_dropoff_before_departure(dep)

    # 일시 미확보 시: 도착 12:00·출발 10:00 가정 후 동일 오프셋 적용
    if not pickup_dt and len(start_d or "") >= 10:
        base = datetime.strptime(start_d[:10], "%Y-%m-%d") + timedelta(hours=12)
        pickup_dt = (base + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
    if not dropoff_dt and len(end_d or "") >= 10:
        dep_guess = datetime.strptime(end_d[:10], "%Y-%m-%d") + timedelta(hours=10)
        dropoff_dt = (dep_guess - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")

    pickup_drop = dac if dac else city
    trip_days = _transit_trip_days(start_d, end_d)
    transit_origin = f"{dac} 공항" if dac else (city or travel.destination or "목적지")
    transit_destination = city or travel.destination or (dac or "")

    return {
        "pickup": pickup_drop,
        "dropoff": pickup_drop,
        "start_date": start_d,
        "end_date": end_d,
        "origin": travel.origin,
        "destination": travel.destination,
        "date_time": date_time,
        "pickup_datetime": pickup_dt,
        "dropoff_datetime": dropoff_dt,
        "passengers": passengers,
        "pickup_airport_iata": dac,
        "dropoff_airport_iata": dac,
        "origin_airport_iata": oac,
        "transit_origin": transit_origin,
        "transit_destination": transit_destination,
        "trip_days": trip_days,
        "duration_days": trip_days,
    }


class SessionExecutor(BaseAgentExecutor):
    """Session Agent - orchestrates Flight, Itinerary, Accommodation, Local Transport, Booking."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        t = self.settings.a2a_timeout_seconds
        tit = self.settings.a2a_itinerary_timeout_seconds
        self.clients = {
            "flight": A2AClient(self.settings.flight_agent_url, timeout=t),
            "itinerary": A2AClient(self.settings.itinerary_agent_url, timeout=tit),
            "accommodation": A2AClient(self.settings.accommodation_agent_url, timeout=t),
            "rental_car": A2AClient(self.settings.rental_car_agent_url, timeout=t),
            "transit": A2AClient(self.settings.transit_agent_url, timeout=t),
            "booking": A2AClient(self.settings.booking_agent_url, timeout=t),
        }

    async def _call_agent(self, name: str, payload: dict) -> str | None:
        try:
            return await self.clients[name].send_message(json.dumps(payload, default=str))
        except Exception as e:
            logger.warning("A2A %s 호출 실패(폴백 가능): %s", name, e)
            return None

    def _rental_car_fallback_json(self, lt_payload: dict) -> str:
        from datetime import datetime

        from mcp_servers.rental_car.services import search_rentals_combined

        sd = (lt_payload.get("start_date") or "")[:10]
        ed = (lt_payload.get("end_date") or sd)[:10]
        try:
            d1 = datetime.strptime(sd, "%Y-%m-%d")
            d2 = datetime.strptime(ed, "%Y-%m-%d")
            days = max(1, (d2 - d1).days)
        except ValueError:
            days = 1
        arr = search_rentals_combined(
            pickup=lt_payload.get("pickup") or "",
            dropoff=lt_payload.get("dropoff") or "",
            car_type="compact",
            days=days,
            passengers=lt_payload.get("passengers"),
            start_date=sd,
            end_date=ed,
            travelpayouts_rental_booking_url=(
                (self.settings.travelpayouts_rental_booking_url or "").strip() or None
            ),
            pickup_datetime=lt_payload.get("pickup_datetime"),
            dropoff_datetime=lt_payload.get("dropoff_datetime"),
            pickup_airport_iata=lt_payload.get("pickup_airport_iata"),
            amadeus_client_id=(self.settings.amadeus_client_id or "").strip() or None,
            amadeus_client_secret=(self.settings.amadeus_client_secret or "").strip() or None,
            serpapi_api_key=(self.settings.serpapi_api_key or "").strip() or None,
        )
        return json.dumps(arr, ensure_ascii=False)

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
        rental_search = data.get("rental_search")
        if not isinstance(rental_search, dict):
            rental_search = None
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
        flight_skipped = bool(data.get("flight_skipped"))
        rental_skipped = bool(data.get("rental_skipped"))

        if (
            flight_complete
            and rental_search
            and travel.local_transport == LocalTransportType.RENTAL_CAR
        ):
            start_d, end_d = _extract_rental_dates_from_flight(
                selected_flight, travel.start_date.isoformat(), travel.end_date.isoformat()
            )
            lt_payload = _merge_rental_search(
                _build_local_transport_payload(selected_flight, travel, start_d, end_d),
                rental_search,
            )
            lt_resp = await self._call_agent("rental_car", lt_payload)
            if not lt_resp:
                lt_resp = self._rental_car_fallback_json(lt_payload)
            parsed_lt = _parse_agent_json_array(lt_resp)
            payload = {"step": "rental", "local_transport": parsed_lt}
            await event_queue.enqueue_event(
                new_agent_text_message(json.dumps(payload, ensure_ascii=False))
            )
            return

        if (selected_flight or flight_skipped) and selected_itinerary and selected_accommodation:
            resp = await self._call_agent(
                "booking",
                {
                    "confirmed_itinerary": selected_itinerary,
                    "selected_flight": selected_flight,
                    "selected_accommodation": selected_accommodation,
                    "flight_skipped": flight_skipped,
                },
            )
            if resp:
                await event_queue.enqueue_event(new_agent_text_message(resp))
            else:
                guidance = {
                    "status": "confirmed",
                    "summary": "일정이 확정되었습니다.",
                    "steps": [
                        {
                            "order": 1,
                            "item": "항공편",
                            "details": selected_flight or ("건너뜀" if flight_skipped else None),
                        },
                        {"order": 2, "item": "숙소", "details": selected_accommodation},
                        {"order": 3, "item": "일정", "details": selected_itinerary},
                    ],
                }
                await event_queue.enqueue_event(
                    new_agent_text_message(json.dumps(guidance, ensure_ascii=False))
                )
            return

        if (selected_flight or flight_skipped) and selected_itinerary and not selected_accommodation:
            acc_priority = [t.value for t in travel.accommodation_priority] if travel.accommodation_priority else [travel.accommodation_type.value]
            acc_payload = {
                "location": travel.destination,
                "check_in": travel.start_date.isoformat(),
                "check_out": travel.end_date.isoformat(),
                "accommodation_type": travel.accommodation_type.value,
                "accommodation_priority": acc_priority,
                "travelers_total": _total_passengers(travel),
                "selected_itinerary": selected_itinerary
                if isinstance(selected_itinerary, dict)
                else None,
            }
            acc_resp = await self._call_agent("accommodation", acc_payload)
            if not acc_resp:
                from mcp_servers.hotel.services import mock_search_hotels

                acc_resp = json.dumps(
                    mock_search_hotels(
                        travel.destination,
                        travel.accommodation_type.value,
                        acc_priority,
                        _total_passengers(travel),
                        selected_itinerary if isinstance(selected_itinerary, dict) else None,
                        travel.start_date.isoformat(),
                        travel.end_date.isoformat(),
                    ),
                    ensure_ascii=False,
                )
            sf_acc = selected_flight if selected_flight else None
            start_d, end_d = _extract_rental_dates_from_flight(
                sf_acc, travel.start_date.isoformat(), travel.end_date.isoformat()
            )
            lt_payload = _merge_rental_search(
                _build_local_transport_payload(sf_acc, travel, start_d, end_d),
                rental_search,
            )
            if travel.local_transport == LocalTransportType.RENTAL_CAR:
                lt_resp = await self._call_agent("rental_car", lt_payload)
                if not lt_resp:
                    lt_resp = self._rental_car_fallback_json(lt_payload)
            else:
                lt_resp = await self._call_agent("transit", lt_payload)
                if not lt_resp:
                    lt_resp = json.dumps([
                        {"route_id": "TR001", "description": "Metro + Bus", "duration_minutes": 40},
                        {"route_id": "TR002", "description": "City Pass", "pass_price_krw": 15000},
                    ])
            result = {
                "step": "accommodation_and_transport",
                "accommodations": _parse_agent_json_array(acc_resp),
                "local_transport": _parse_agent_json_array(lt_resp),
            }
            await event_queue.enqueue_event(
                new_agent_text_message(json.dumps(result, ensure_ascii=False))
            )
            return

        if (
            (flight_complete or flight_skipped)
            and (selected_local_transport or rental_skipped)
            and not selected_itinerary
        ):
            sf_eff = selected_flight if flight_complete else None
            start_d, end_d = _extract_rental_dates_from_flight(
                sf_eff, travel.start_date.isoformat(), travel.end_date.isoformat()
            )
            lt_payload = _build_local_transport_payload(sf_eff, travel, start_d, end_d)
            route_origin = lt_payload.get("transit_origin") or travel.origin

            # 일정·명소 일수는 폼이 아니라 선택 항공의 도착·귀국 출발일을 우선(유연일·초기 폼과 불일치 방지).
            it_start, it_end = start_d, end_d

            it_payload = {
                "destination": travel.destination,
                "origin": route_origin,
                "local_transport": travel.local_transport.value,
                "multi_cities": multi_cities,
                "start_date": it_start,
                "end_date": it_end,
                "preference": travel.preference.model_dump(),
                "selected_flight": sf_eff,
            }
            phase = (data.get("itinerary_phase") or "attractions").strip().lower()
            it_payload["itinerary_phase"] = phase
            if phase == "route_restaurants":
                it_payload["selected_attraction_ids"] = data.get("selected_attraction_ids") or []
                cat = data.get("itinerary_attraction_catalog")
                it_payload["itinerary_attraction_catalog"] = cat if isinstance(cat, list) else []
            elif phase == "finalize":
                it_payload["meal_choices"] = data.get("meal_choices") or {}
                bundle = data.get("route_plan_bundle")
                it_payload["route_plan_bundle"] = bundle if isinstance(bundle, dict) else {}
            resp = await self._call_agent("itinerary", it_payload)
            if resp and str(resp).strip():
                await event_queue.enqueue_event(new_agent_text_message(resp))
            else:
                if not resp or not str(resp).strip():
                    logger.warning(
                        "일정 에이전트(itinerary) 응답 없음 또는 빈 문자열 — "
                        "목(mock) 명소로 폴백합니다. ITINERARY_AGENT_URL·itinerary 컨테이너·네트워크를 확인하세요."
                    )
                from agents.itinerary.executor import (
                    _attraction_target_count,
                    _mock_attractions,
                    _trip_inclusive_days,
                    postprocess_attraction_list_for_catalog,
                )

                trip_days = _trip_inclusive_days(it_start, it_end)
                fallback = _mock_attractions(
                    travel.destination, trip_days, travel.preference.model_dump()
                )
                if phase == "attractions":
                    atts_fb = fallback.get("attractions")
                    if isinstance(atts_fb, list) and atts_fb:
                        n_attr = _attraction_target_count(trip_days)
                        fallback["attractions"] = await postprocess_attraction_list_for_catalog(
                            atts_fb,
                            settings=self.settings,
                            destination=travel.destination,
                            start_date=it_start,
                            end_date=it_end,
                            merged_pre_llm=None,
                            location_bias=None,
                            response_out=fallback,
                            target_count=n_attr,
                        )
                await event_queue.enqueue_event(
                    new_agent_text_message(json.dumps(fallback, ensure_ascii=False))
                )
            return

        if (flight_complete or flight_skipped) and not selected_local_transport and not rental_skipped:
            sf_eff = selected_flight if flight_complete else None
            start_d, end_d = _extract_rental_dates_from_flight(
                sf_eff, travel.start_date.isoformat(), travel.end_date.isoformat()
            )
            lt_payload = _merge_rental_search(
                _build_local_transport_payload(sf_eff, travel, start_d, end_d),
                rental_search,
            )
            if travel.local_transport == LocalTransportType.RENTAL_CAR:
                lt_resp = await self._call_agent("rental_car", lt_payload)
                if not lt_resp:
                    lt_resp = self._rental_car_fallback_json(lt_payload)
            else:
                lt_resp = await self._call_agent("transit", lt_payload)
                if not lt_resp:
                    lt_resp = json.dumps([
                        {"route_id": "TR001", "description": "Metro + Bus", "duration_minutes": 40},
                        {"route_id": "TR002", "description": "City Pass", "pass_price_krw": 15000},
                    ])
            result = {
                "step": "rental",
                "local_transport": _parse_agent_json_array(lt_resp),
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
            pref_ret = (
                _carrier_code_from_outbound_flight(selected_outbound_flight)
                if leg == "return" and selected_outbound_flight
                else None
            )

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
                    preferred_return_airline_code=pref_ret,
                )
            out = {"flights": flights, "warnings": warnings, "flight_search_api": flight_search_api}
            await event_queue.enqueue_event(
                new_agent_text_message(json.dumps(out, ensure_ascii=False))
            )

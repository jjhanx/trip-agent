"""SerpApi (Google Flights) 항공편 검색 클라이언트.

SerpApi를 통해 Google Flights 결과를 조회. 대한항공·아시아나 포함 전 세계 항공사 실시간 데이터.
https://serpapi.com/google-flights-api
"""

import re
from typing import Any

import httpx

# 디버깅: True 시 검색 요청/응답 요약을 터미널에 출력
DEBUG_SERPAPI = False


def _normalize_flight(
    airline: str,
    flight_number: str,
    departure: str,
    arrival: str,
    origin: str,
    destination: str,
    price_krw: int | None,
    miles_required: int | None,
    duration_hours: float | None = None,
    flight_id: str | None = None,
    seat_class: str = "economy",
    is_direct: bool = True,
    segments: list | None = None,
    layovers: list | None = None,
) -> dict:
    """통일된 항공편 형식으로 변환."""
    out: dict = {
        "flight_id": flight_id or f"{airline}_{flight_number}_{departure}",
        "airline": airline,
        "flight_number": flight_number,
        "departure": departure,
        "arrival": arrival,
        "origin": origin,
        "destination": destination,
        "price_krw": price_krw,
        "miles_required": miles_required,
        "duration_hours": duration_hours,
        "seat_class": seat_class,
        "source": "api",
        "is_direct": is_direct,
    }
    if segments is not None:
        out["segments"] = segments
    if layovers is not None:
        out["layovers"] = layovers
    return out


def _parse_serpapi_time(t: str) -> str:
    """2023-10-03 15:10 -> 2023-10-03T15:10:00 형식."""
    if not t:
        return ""
    # YYYY-MM-DD HH:MM 또는 YYYY-MM-DD
    t = str(t).strip()
    if " " in t:
        date_part, time_part = t.split(" ", 1)
        if len(time_part) == 5:  # HH:MM
            return f"{date_part}T{time_part}:00"
    elif len(t) == 10:
        return f"{t}T00:00:00"
    return t


def _segments_to_leg(segs: list, o: str, d: str) -> dict | None:
    """세그먼트 리스트 → 출발/도착/항공사 등 하나의 leg 정보."""
    if not segs:
        return None
    s0, s_last = segs[0], segs[-1]
    dep = s0.get("departure_airport") or {}
    arr = s_last.get("arrival_airport") or {}
    dur_min = sum(s.get("duration") or 0 for s in segs)
    dur_h = round(dur_min / 60, 1) if dur_min else None
    segs_ui = [
        {
            "departure_airport": {"id": (x.get("departure_airport") or {}).get("id"), "name": (x.get("departure_airport") or {}).get("name"), "time": (x.get("departure_airport") or {}).get("time")},
            "arrival_airport": {"id": (x.get("arrival_airport") or {}).get("id"), "name": (x.get("arrival_airport") or {}).get("name"), "time": (x.get("arrival_airport") or {}).get("time")},
            "duration": x.get("duration"),
            "airline": x.get("airline"),
            "flight_number": x.get("flight_number"),
        }
        for x in segs
    ]
    return {
        "airline": s0.get("airline", ""),
        "flight_number": s0.get("flight_number", ""),
        "departure": _parse_serpapi_time(dep.get("time", "")),
        "arrival": _parse_serpapi_time(arr.get("time", "")),
        "origin": dep.get("id", o) or o,
        "destination": arr.get("id", d) or d,
        "duration_hours": dur_h,
        "is_direct": len(segs) == 1,
        "segments": segs_ui,
    }


def _trip_to_round_trip(trip: dict, origin: str, destination: str) -> dict | None:
    """SerpApi 왕복 trip → round_trip 구조 (outbound + return + 총가격)."""
    flights = trip.get("flights", [])
    if not flights:
        return None

    dest_upper = destination.upper()[:3]
    orig_upper = origin.upper()[:3]

    outbound_segs: list = []
    return_segs: list = []
    in_return = False
    for seg in flights:
        dep_id = (seg.get("departure_airport") or {}).get("id", "")
        arr_id = (seg.get("arrival_airport") or {}).get("id", "")
        dep_3 = str(dep_id).upper()[:3] if dep_id else ""
        arr_3 = str(arr_id).upper()[:3] if arr_id else ""
        if not in_return:
            outbound_segs.append(seg)
            if arr_3 == dest_upper:
                in_return = True
        else:
            return_segs.append(seg)

    ob = _segments_to_leg(outbound_segs, origin, destination)
    ret = _segments_to_leg(return_segs, destination, origin)
    if not ob or not ret:
        return None

    price = trip.get("price")
    try:
        price_krw = int(price) if price is not None else None
    except (TypeError, ValueError):
        price_krw = None

    return {
        "round_trip": True,
        "price_krw": price_krw,
        "miles_required": None,
        "outbound": {**ob, "flight_id": trip.get("departure_token")},
        "return": ret,
        "flight_id": trip.get("departure_token"),
        "layovers": trip.get("layovers") or [],
    }


def _trip_to_flight(
    trip: dict,
    origin: str,
    destination: str,
) -> dict | None:
    """SerpApi trip(best_flights/other_flights 항목) → 통일된 flight dict (편도)."""
    flights = trip.get("flights", [])
    if not flights:
        return None

    # 가는 편만 사용 (첫 번째 구간부터 목적지 도달까지). 왕복이면 return 구간 직전까지
    outbound: list = []
    dest_upper = destination.upper()[:3]
    for seg in flights:
        outbound.append(seg)
        arr_id = (seg.get("arrival_airport") or {}).get("id", "")
        if isinstance(arr_id, str) and arr_id.upper()[:3] == dest_upper:
            break

    if not outbound:
        return None

    seg0 = outbound[0]
    seg_last = outbound[-1]
    dep_airport = seg0.get("departure_airport") or {}
    arr_airport = seg_last.get("arrival_airport") or {}

    dep_time = dep_airport.get("time", "")
    arr_time = arr_airport.get("time", "")
    origin_code = dep_airport.get("id", origin) or origin
    dest_code = arr_airport.get("id", destination) or destination

    # 비행시간 (가는 편만, 분 단위 합)
    dur_min = sum(s.get("duration") or 0 for s in outbound)
    dur_h = round(dur_min / 60, 1) if dur_min else None

    is_direct = len(outbound) == 1

    # segments: 프론트엔드 상세 표시용 (SerpApi 형식 유지)
    segs_for_ui = []
    for s in flights:
        da = s.get("departure_airport") or {}
        aa = s.get("arrival_airport") or {}
        segs_for_ui.append({
            "departure_airport": {"id": da.get("id"), "name": da.get("name"), "time": da.get("time")},
            "arrival_airport": {"id": aa.get("id"), "name": aa.get("name"), "time": aa.get("time")},
            "duration": s.get("duration"),
            "airline": s.get("airline"),
            "flight_number": s.get("flight_number"),
        })

    layovers_list = trip.get("layovers") or []

    price = trip.get("price")
    if price is None:
        price_krw = None
    else:
        try:
            price_krw = int(price)
        except (TypeError, ValueError):
            price_krw = None

    airline = seg0.get("airline", "")
    fn = seg0.get("flight_number", "")
    if not airline and len(outbound) > 1:
        airline = "멀티"
    if not fn:
        fn = ""

    return _normalize_flight(
        airline=airline,
        flight_number=fn,
        departure=_parse_serpapi_time(dep_time),
        arrival=_parse_serpapi_time(arr_time),
        origin=origin_code,
        destination=dest_code,
        price_krw=price_krw,
        miles_required=None,
        duration_hours=dur_h,
        flight_id=trip.get("departure_token"),
        seat_class="economy",
        is_direct=is_direct,
        segments=segs_for_ui,
        layovers=layovers_list,
    )


async def search_serpapi(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    api_key: str,
    seat_class: str = "economy",
    one_way: bool = False,
) -> tuple[list[dict], list[str]]:
    """
    SerpApi Google Flights 검색. 대한항공·아시아나 포함.
    one_way=True 시 편도만 검색 (type=2).
    Returns (flights, warnings)
    """
    if not api_key:
        return [], ["SerpApi API 키가 설정되지 않았습니다. .env에 SERPAPI_API_KEY 추가."]

    warnings: list[str] = []
    o, d = origin.upper()[:3], destination.upper()[:3]

    params = {
        "engine": "google_flights",
        "hl": "ko",
        "gl": "kr",
        "currency": "KRW",
        "departure_id": o,
        "arrival_id": d,
        "outbound_date": start_date,
        "type": "2" if one_way else "1",
        "api_key": api_key,
        "no_cache": "true",  # SerpApi 빈 결과 버그 완화 (GitHub #2188 등)
    }
    if not one_way:
        params["return_date"] = end_date

    if DEBUG_SERPAPI:
        print(f"[SerpApi] Request: {o} -> {d}, {start_date}" + (f" ~ {end_date}" if not one_way else " (편도)"))

    url = "https://serpapi.com/search.json"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, params=params)

    if resp.status_code != 200:
        err = resp.text[:200]
        return [], [f"SerpApi 검색 실패: {resp.status_code} - {err}"]

    try:
        data = resp.json()
    except Exception:
        return [], ["SerpApi 응답 파싱 실패"]

    err_msg = data.get("error")
    if err_msg:
        return [], [f"SerpApi 오류: {err_msg}"]

    best = data.get("best_flights") or []
    other = data.get("other_flights") or []
    all_trips = best + other

    if DEBUG_SERPAPI:
        print(f"[SerpApi] best={len(best)}, other={len(other)}")

    flights = []
    for trip in all_trips[:25]:
        if one_way:
            f = _trip_to_flight(trip, o, d)
        else:
            f = _trip_to_round_trip(trip, o, d)
        if f:
            flights.append(f)

    return flights, warnings

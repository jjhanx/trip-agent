"""Amadeus Flight Offers Search API 클라이언트.

SerpAPI 한도 초과(429) 시 fallback으로 사용.
https://developers.amadeus.com/self-service/category/air/api-doc/flight-offers-search
"""

import asyncio
import re
from typing import Any

import httpx

AMADEUS_TOKEN_URL = "https://test.api.amadeus.com/v1/security/oauth2/token"
AMADEUS_FLIGHT_OFFERS_URL = "https://test.api.amadeus.com/v2/shopping/flight-offers"


def _parse_iso_duration(dur: str) -> float | None:
    """ISO 8601 duration (PT2H10M) → hours float."""
    if not dur or not isinstance(dur, str):
        return None
    total_min = 0
    if "H" in dur.upper():
        m = re.search(r"(\d+)H", dur, re.I)
        if m:
            total_min += int(m.group(1)) * 60
    if "M" in dur.upper():
        m = re.search(r"(\d+)M", dur, re.I)
        if m:
            total_min += int(m.group(1))
    if "S" in dur.upper():
        m = re.search(r"(\d+)S", dur, re.I)
        if m:
            total_min += int(m.group(1)) / 60
    return round(total_min / 60, 1) if total_min else None


def _amadeus_segments_to_leg(
    segments: list[dict],
    origin: str,
    destination: str,
    carriers: dict[str, str],
) -> dict | None:
    """Amadeus segments → outbound/return leg (SerpApi 호환)."""
    if not segments:
        return None
    s0 = segments[0]
    s_last = segments[-1]
    dep = s0.get("departure") or {}
    arr = s_last.get("arrival") or {}
    dep_at = dep.get("at", "")
    arr_at = arr.get("at", "")
    dep_iata = (dep.get("iataCode") or origin).upper()[:3]
    arr_iata = (arr.get("iataCode") or destination).upper()[:3]
    carrier = s0.get("carrierCode", "")
    airline = carriers.get(carrier, carrier) if carrier else ""
    fn = (carrier or "") + str(s0.get("number", "") or "")

    dur_min = 0
    for seg in segments:
        d = seg.get("duration") or ""
        if d:
            h = _parse_iso_duration(d)
            if h is not None:
                dur_min += h * 60
    dur_h = round(dur_min / 60, 1) if dur_min else None

    segs_ui = []
    for s in segments:
        dh = _parse_iso_duration(s.get("duration", ""))
        dur_min = int(dh * 60) if dh is not None else None
        dep = s.get("departure") or {}
        arr = s.get("arrival") or {}
        at_dep = dep.get("at", "")
        at_arr = arr.get("at", "")
        segs_ui.append({
            "departure_airport": {"id": dep.get("iataCode"), "name": None, "time": at_dep[:16].replace("T", " ") if at_dep else ""},
            "arrival_airport": {"id": arr.get("iataCode"), "name": None, "time": at_arr[:16].replace("T", " ") if at_arr else ""},
            "duration": dur_min,
            "airline": carriers.get(s.get("carrierCode", ""), s.get("carrierCode", "")),
            "flight_number": (s.get("carrierCode", "") or "") + str(s.get("number", "") or ""),
        })

    return {
        "airline": airline,
        "flight_number": fn or carrier,
        "departure": dep_at[:19] if dep_at else "",
        "arrival": arr_at[:19] if arr_at else "",
        "origin": dep_iata,
        "destination": arr_iata,
        "duration_hours": dur_h,
        "is_direct": len(segments) == 1,
        "segments": segs_ui,
    }


async def _get_amadeus_token(client_id: str, client_secret: str) -> str | None:
    """OAuth2 토큰 발급."""
    if not client_id or not client_secret:
        return None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                AMADEUS_TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if resp.status_code != 200:
            return None
        data = resp.json()
        return data.get("access_token")
    except Exception:
        return None


def _mileage_program_to_airline_codes(mileage_program: str | None) -> list[str]:
    """마일리지 프로그램 → Amadeus includedAirlineCodes (IATA 2자)."""
    if not mileage_program or not str(mileage_program).strip():
        return []
    key = str(mileage_program).lower().replace(" ", "").replace("_", "")
    if "skypass" in key or "대한항공" in key:
        return ["KE"]
    if "asiana" in key or "아시아나" in key:
        return ["OZ"]
    return []


async def search_amadeus(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    client_id: str,
    client_secret: str,
    one_way: bool = False,
    seat_class: str = "economy",
    max_offers: int = 20,
    included_airline_codes: list[str] | None = None,
    non_stop: bool = False,
) -> tuple[list[dict], list[str]]:
    """
    Amadeus Flight Offers Search API 호출.
    SerpApi 한도 초과 시 fallback 용도.
    Returns (flights, warnings)
    """
    warnings: list[str] = []
    o = origin.upper()[:3]
    d = destination.upper()[:3]

    token = await _get_amadeus_token(client_id, client_secret)
    if not token:
        return [], ["Amadeus API 인증 실패. AMADEUS_CLIENT_ID, AMADEUS_CLIENT_SECRET 확인."]

    params: dict[str, Any] = {
        "originLocationCode": o,
        "destinationLocationCode": d,
        "departureDate": start_date,
        "adults": 1,
        "currencyCode": "KRW",
        "max": max_offers,
    }
    if not one_way:
        params["returnDate"] = end_date
    if included_airline_codes:
        params["includedAirlineCodes"] = ",".join(c.upper()[:2] for c in included_airline_codes if c)
    if non_stop:
        params["nonStop"] = "true"
    if seat_class:
        sc = str(seat_class).upper()
        if sc in ("ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST"):
            params["travelClass"] = sc

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                AMADEUS_FLIGHT_OFFERS_URL,
                params=params,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.amadeus+json",
                },
            )
    except Exception as e:
        return [], [f"Amadeus API 연결 실패: {e}"]

    if resp.status_code != 200:
        try:
            err = resp.json()
            errs = err.get("errors", [])
            msg = errs[0].get("detail", resp.text[:200]) if errs else resp.text[:200]
        except Exception:
            msg = resp.text[:200]
        return [], [f"Amadeus API 오류 ({resp.status_code}): {msg}"]

    try:
        data = resp.json()
    except Exception:
        return [], ["Amadeus 응답 파싱 실패"]

    carriers: dict[str, str] = {}
    meta = data.get("dictionaries") or {}
    carriers_raw = meta.get("carriers") or {}
    if isinstance(carriers_raw, dict):
        carriers = {k: str(v) for k, v in carriers_raw.items()}

    offers = data.get("data") or []
    flights: list[dict] = []

    for offer in offers[:max_offers]:
        itineraries = offer.get("itineraries") or []
        price_info = offer.get("price") or {}
        total_str = price_info.get("total") or price_info.get("grandTotal") or "0"
        curr = price_info.get("currency", "KRW")
        try:
            price_val = float(total_str)
            price_krw = int(price_val) if curr == "KRW" else int(price_val * 1400)
        except (ValueError, TypeError):
            price_krw = None

        if one_way:
            if not itineraries:
                continue
            it = itineraries[0]
            segs = it.get("segments") or []
            leg = _amadeus_segments_to_leg(segs, o, d, carriers)
            if not leg:
                continue
            flights.append({
                "round_trip": False,
                "airline": leg.get("airline", ""),
                "flight_number": leg.get("flight_number", ""),
                "departure": leg.get("departure", ""),
                "arrival": leg.get("arrival", ""),
                "origin": leg.get("origin", o),
                "destination": leg.get("destination", d),
                "price_krw": price_krw,
                "miles_required": None,
                "duration_hours": leg.get("duration_hours"),
                "seat_class": seat_class,
                "source": "amadeus",
                "is_direct": leg.get("is_direct", True),
                "segments": leg.get("segments", []),
                "flight_id": f"amadeus_{offer.get('id', '')}",
            })
        else:
            if len(itineraries) < 2:
                continue
            ob_it = itineraries[0]
            ret_it = itineraries[1]
            ob_segs = ob_it.get("segments") or []
            ret_segs = ret_it.get("segments") or []
            ob_leg = _amadeus_segments_to_leg(ob_segs, o, d, carriers)
            ret_leg = _amadeus_segments_to_leg(ret_segs, d, o, carriers)
            if not ob_leg or not ret_leg:
                continue
            flights.append({
                "round_trip": True,
                "price_krw": price_krw,
                "miles_required": None,
                "outbound": ob_leg,
                "return": ret_leg,
                "flight_id": f"amadeus_{offer.get('id', '')}",
                "layovers": [],
            })

    if flights:
        warnings.append("SerpApi 한도 초과로 Amadeus API로 조회했습니다.")
    return flights, list(dict.fromkeys(warnings))


async def search_amadeus_multi_pairs(
    origin: str,
    destination: str,
    date_pairs: list[tuple[str, str]],
    client_id: str,
    client_secret: str,
    one_way: bool = False,
    seat_class: str = "economy",
    max_offers_per_pair: int = 15,
    included_airline_codes: list[str] | None = None,
) -> tuple[list[dict], list[str]]:
    """
    날짜 유연성 적용: 여러 (출발일, 귀환일) 쌍에 대해 Amadeus 검색 후 병합.
    Returns (flights, warnings)
    """
    if not date_pairs:
        return [], []

    if len(date_pairs) == 1:
        ob_d, ret_d = date_pairs[0]
        return await search_amadeus(
            origin, destination, ob_d, ret_d, client_id, client_secret,
            one_way=one_way, seat_class=seat_class, max_offers=max_offers_per_pair,
            included_airline_codes=included_airline_codes,
        )

    tasks = [
        search_amadeus(
            origin, destination, ob_d, ret_d, client_id, client_secret,
            one_way=one_way, seat_class=seat_class, max_offers=max_offers_per_pair,
            included_airline_codes=included_airline_codes,
        )
        for ob_d, ret_d in date_pairs
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_flights: list[dict] = []
    all_warnings: list[str] = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            all_warnings.append(f"Amadeus 날짜쌍 검색 오류: {r}")
            continue
        fl, wa = r
        all_flights.extend(fl)
        all_warnings.extend(wa)

    seen: set = set()
    unique: list[dict] = []
    for f in all_flights:
        if f.get("round_trip"):
            ob = f.get("outbound") or {}
            ret = f.get("return") or {}
            key = (ob.get("departure"), ob.get("arrival"), ret.get("departure"), ret.get("arrival"))
        else:
            key = (f.get("departure"), f.get("arrival"), f.get("flight_number"))
        if key not in seen:
            seen.add(key)
            unique.append(f)

    if unique and "Amadeus" not in " ".join(all_warnings):
        all_warnings.append("SerpApi 한도 초과로 Amadeus API로 조회했습니다.")
    return unique, list(dict.fromkeys(all_warnings))


async def search_amadeus_with_preferred(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    client_id: str,
    client_secret: str,
    mileage_program: str | None,
    date_pairs: list[tuple[str, str]],
    one_way: bool = False,
    seat_class: str = "economy",
) -> tuple[list[dict], list[str]]:
    """
    선호 항공사(대한항공/아시아나) 보강: 일반 검색 + 선호 항공사 전용 검색 병합.
    Amadeus는 가격순으로 반환하므로 대한항공이 상대적으로 비싸면 누락될 수 있어,
    마일리지 프로그램이 있으면 includedAirlineCodes로 전용 검색을 추가 병합.
    date_pairs: 검색할 (출발일, 귀환일) 쌍 목록 (services에서 계산해 전달).
    """
    preferred_codes = _mileage_program_to_airline_codes(mileage_program)

    if len(date_pairs) > 1:
        main_flights, main_warnings = await search_amadeus_multi_pairs(
            origin, destination, date_pairs[:8], client_id, client_secret,
            one_way=one_way, seat_class=seat_class,
            included_airline_codes=None,
        )
    else:
        ob_d, ret_d = date_pairs[0] if date_pairs else (start_date, end_date)
        main_flights, main_warnings = await search_amadeus(
            origin, destination, ob_d, ret_d, client_id, client_secret,
            one_way=one_way, seat_class=seat_class,
            included_airline_codes=None,
        )

    if not preferred_codes:
        return main_flights, main_warnings

    supplement_pairs = date_pairs[:3] if date_pairs else [(start_date, end_date)]
    if len(supplement_pairs) == 1:
        ob_d, ret_d = supplement_pairs[0]
        supp_flights, supp_warnings = await search_amadeus(
            origin, destination, ob_d, ret_d, client_id, client_secret,
            one_way=one_way, seat_class=seat_class,
            included_airline_codes=preferred_codes, max_offers=15,
        )
    else:
        supp_flights, supp_warnings = await search_amadeus_multi_pairs(
            origin, destination, supplement_pairs, client_id, client_secret,
            one_way=one_way, seat_class=seat_class, max_offers_per_pair=15,
            included_airline_codes=preferred_codes,
        )

    seen: set = set()
    merged: list[dict] = []
    for f in main_flights + supp_flights:
        if f.get("round_trip"):
            ob, ret = f.get("outbound") or {}, f.get("return") or {}
            key = (ob.get("departure"), ob.get("arrival"), ret.get("departure"), ret.get("arrival"))
        else:
            key = (f.get("departure"), f.get("arrival"), f.get("flight_number"))
        if key not in seen:
            seen.add(key)
            merged.append(f)

    combined_warnings = list(dict.fromkeys(main_warnings + supp_warnings))
    return merged, combined_warnings

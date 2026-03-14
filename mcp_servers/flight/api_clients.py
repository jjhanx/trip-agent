"""Duffel API 항공편 검색 클라이언트 (대한항공·아시아나 포함).

Duffel은 Travelport GDS 경유로 Korean Air, Asiana 등 300+ 항공사 실시간 데이터 제공.
https://duffel.com/flights/airlines/korean-air
"""

import re
from typing import Any

import httpx


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
) -> dict:
    """통일된 항공편 형식으로 변환."""
    return {
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


def _parse_iso_duration(duration: str) -> float | None:
    """PT02H26M -> 2.4 (시간)."""
    if not duration:
        return None
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", str(duration).upper())
    if not m:
        return None
    h = int(m.group(1) or 0)
    mn = int(m.group(2) or 0)
    return round(h + mn / 60, 1)


def _currency_to_krw(amount: str | float, currency: str) -> int:
    """통화 → KRW 근사치."""
    try:
        amt = float(amount or 0)
    except (TypeError, ValueError):
        return 0
    rates = {"USD": 1400, "EUR": 1500, "GBP": 1750, "KRW": 1, "JPY": 9}
    rate = rates.get((currency or "USD").upper(), 1400)
    return int(amt * rate)


async def search_duffel(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    api_key: str,
    seat_class: str = "economy",
) -> tuple[list[dict], list[str]]:
    """
    Duffel Offer Requests API. 대한항공·아시아나 포함 300+ 항공사.
    Live 토큰 필요 (테스트 토큰은 Duffel Airways만 반환).
    Returns (flights, warnings)
    """
    if not api_key:
        return [], ["Duffel API 키가 설정되지 않았습니다. .env에 DUFFEL_ACCESS_TOKEN 추가."]

    warnings: list[str] = []
    o, d = origin.upper()[:3], destination.upper()[:3]
    cabin_map = {
        "economy": "economy",
        "premium_economy": "premium_economy",
        "business": "business",
        "first": "first",
    }
    cabin = cabin_map.get((seat_class or "economy").lower(), "economy")

    payload = {
        "data": {
            "slices": [
                {"origin": o, "destination": d, "departure_date": start_date},
                {"origin": d, "destination": o, "departure_date": end_date},
            ],
            "passengers": [{"type": "adult"}],
            "cabin_class": cabin,
            "return_offers": True,
        }
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.duffel.com/air/offer_requests",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Duffel-Version": "v2",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json=payload,
        )

    if resp.status_code != 200:
        err = resp.text
        if resp.status_code == 401:
            return [], [f"Duffel 인증 실패(401). Live 토큰 확인: duffel.com/dashboard"]
        if resp.status_code == 422:
            try:
                j = resp.json()
                errs = j.get("errors", [])
                if errs:
                    err = errs[0].get("message", str(errs))
            except Exception:
                pass
        return [], [f"Duffel 검색 실패: {resp.status_code} - {err[:200]}"]

    try:
        data = resp.json()
    except Exception:
        return [], ["Duffel 응답 파싱 실패"]

    odata = data.get("data", {})
    offers = odata.get("offers", [])
    if not offers:
        return [], warnings

    flights = []
    for offer in offers[:25]:
        total_amount = offer.get("total_amount") or offer.get("base_amount", "0")
        total_currency = offer.get("total_currency") or offer.get("base_currency", "USD")
        price_krw = _currency_to_krw(total_amount, total_currency)

        slices = offer.get("slices", [])
        if not slices:
            continue
        segs = slices[0].get("segments", [])
        if not segs:
            continue

        # 직항: 1개 세그먼트, 경유: 2개 이상
        is_direct = len(segs) == 1

        # 총 비행시간 (모든 세그먼트 합)
        dur_h = None
        for s in segs:
            d = _parse_iso_duration(s.get("duration", ""))
            dur_h = (dur_h or 0) + (d or 0)
        dur_h = round(dur_h, 1) if dur_h else None

        seg = segs[0]
        carrier = seg.get("operating_carrier") or seg.get("marketing_carrier") or {}
        airline = carrier.get("name", carrier.get("iata_code", ""))
        fn = seg.get("operating_carrier_flight_number") or seg.get("marketing_carrier_flight_number", "")
        iata = carrier.get("iata_code", "")
        if not airline and iata:
            airline = iata
        if not fn and iata:
            fn = f"{iata}{fn}" if fn else iata

        dep = seg.get("departing_at", "")[:19]
        last_seg = segs[-1]
        arr = last_seg.get("arriving_at", "")[:19]

        orig = seg.get("origin", {})
        dest = last_seg.get("destination", {})
        orig_code = orig.get("iata_code", o) if isinstance(orig, dict) else o
        dest_code = dest.get("iata_code", d) if isinstance(dest, dict) else d

        flights.append(
            _normalize_flight(
                airline=airline,
                flight_number=fn,
                departure=dep,
                arrival=arr,
                origin=orig_code,
                destination=dest_code,
                price_krw=price_krw,
                miles_required=None,
                duration_hours=dur_h,
                flight_id=offer.get("id"),
                seat_class=cabin,
                is_direct=is_direct,
            )
        )

    return flights, warnings

"""Amadeus, Kiwi Tequila, RapidAPI Skyscanner 항공편 검색 클라이언트."""

import asyncio
from typing import Any

import httpx

from mcp_servers.flight.usage_tracker import (
    can_use_amadeus,
    can_use_kiwi,
    can_use_rapidapi,
    record_amadeus,
    record_kiwi,
    record_rapidapi,
)


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
    }


async def search_amadeus(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    client_id: str,
    client_secret: str,
) -> tuple[list[dict], list[str]]:
    """
    Amadeus Flight Offers Search.
    Returns (flights, warnings)
    """
    can_use, warn = can_use_amadeus()
    if not can_use:
        return [], [warn or "Amadeus 한도 초과"]

    warnings = []
    if warn:
        warnings.append(warn)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # OAuth token
        token_resp = await client.post(
            "https://api.amadeus.com/v1/security/oauth2/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
        )
        if token_resp.status_code != 200:
            return [], warnings + [f"Amadeus 인증 실패: {token_resp.status_code}"]

        token = token_resp.json().get("access_token")
        if not token:
            return [], warnings + ["Amadeus 토큰 획득 실패"]

        # Flight search (outbound only - Amadeus free tier)
        resp = await client.get(
            "https://api.amadeus.com/v1/shopping/flight-offers",
            headers={"Authorization": f"Bearer {token}"},
            params={
                "originLocationCode": origin.upper()[:3],
                "destinationLocationCode": destination.upper()[:3],
                "departureDate": start_date,
                "adults": 1,
                "max": 10,
            },
        )

        if resp.status_code != 200:
            return [], warnings + [f"Amadeus 검색 실패: {resp.status_code}"]

        try:
            data = resp.json()
        except Exception:
            return [], warnings + ["Amadeus 응답 파싱 실패"]

        record_amadeus()

        flights = []
        for offer in data.get("data", [])[:10]:
            itineraries = offer.get("itineraries", [])
            if not itineraries:
                continue
            segs = itineraries[0].get("segments", [])
            if not segs:
                continue
            dep = segs[0].get("departure", {}).get("at", "")
            last_seg = segs[-1]
            arr = last_seg.get("arrival", {}).get("at", "")
            carr = segs[0].get("carrierCode", "")
            num = segs[0].get("number", "")
            price = offer.get("price", {}).get("grandTotal")
            # EUR to KRW approx (실제로는 환율 API)
            price_krw = int(float(price or 0) * 1450) if price else None

            flights.append(
                _normalize_flight(
                    airline=carr,
                    flight_number=f"{carr}{num}",
                    departure=dep[:19] if len(dep) >= 19 else dep,
                    arrival=arr[:19] if len(arr) >= 19 else arr,
                    origin=origin,
                    destination=destination,
                    price_krw=price_krw,
                    miles_required=None,
                    flight_id=offer.get("id"),
                )
            )

        return flights, warnings


async def search_kiwi(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    api_key: str,
) -> tuple[list[dict], list[str]]:
    """
    Kiwi Tequila Search API.
    Returns (flights, warnings)
    """
    can_use, warn = can_use_kiwi()
    if not can_use:
        return [], [warn or "Kiwi 분당 한도 초과"]

    warnings = []
    if warn:
        warnings.append(warn)

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(
            "https://api.tequila.kiwi.com/v2/search",
            headers={"apikey": api_key},
            params={
                "fly_from": origin.upper()[:3],
                "fly_to": destination.upper()[:3],
                "date_from": start_date,
                "date_to": start_date,
                "return_from": end_date,
                "return_to": end_date,
                "adults": 1,
                "limit": 10,
                "curr": "KRW",
            },
        )

        if resp.status_code != 200:
            return [], warnings + [f"Kiwi 검색 실패: {resp.status_code}"]

        try:
            data = resp.json()
        except Exception:
            return [], warnings + ["Kiwi 응답 파싱 실패"]

        record_kiwi()

        flights = []
        for r in data.get("data", [])[:10]:
            dep = r.get("local_departure", "")[:19]
            arr = r.get("local_arrival", "")[:19]
            route = r.get("route", [])
            if route:
                first = route[0]
                last = route[-1]
                airline = first.get("airline", "") or first.get("operating_carrier", "")
                fn = first.get("flight_no") or ""
                if not fn and airline:
                    fn = airline
            else:
                airline = r.get("airlines", ["Unknown"])[0]
                fn = ""

            price = r.get("price")
            price_krw = int(price) if price is not None else None
            dur = r.get("duration", {}).get("total")
            dur_h = round(dur / 3600, 1) if dur else None

            flights.append(
                _normalize_flight(
                    airline=airline,
                    flight_number=fn,
                    departure=dep,
                    arrival=arr,
                    origin=origin,
                    destination=destination,
                    price_krw=price_krw,
                    miles_required=None,
                    duration_hours=dur_h,
                    flight_id=r.get("id"),
                )
            )

        return flights, warnings


async def search_rapidapi_skyscanner(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    rapidapi_key: str,
) -> tuple[list[dict], list[str]]:
    """
    RapidAPI Skyscanner Browse Quotes.
    Returns (flights, warnings)
    """
    can_use, warn = can_use_rapidapi()
    if not can_use:
        return [], [warn or "RapidAPI 월 한도 초과"]

    warnings = []
    if warn:
        warnings.append(warn)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Browse quotes: country/currency/locale/origin/dest/outbound/inbound
        url = (
            f"https://skyscanner-skyscanner-flight-search-v1.p.rapidapi.com/apiservices/browsequotes/v1.0"
            f"/KR/KRW/ko-KR/{origin.upper()[:3]}-sky/{destination.upper()[:3]}-sky/{start_date}/{end_date}"
        )
        resp = await client.get(
            url,
            headers={
                "X-RapidAPI-Key": rapidapi_key,
                "X-RapidAPI-Host": "skyscanner-skyscanner-flight-search-v1.p.rapidapi.com",
            },
        )

        if resp.status_code != 200:
            return [], warnings + [f"RapidAPI 검색 실패: {resp.status_code}"]

        try:
            data = resp.json()
        except Exception:
            return [], warnings + ["RapidAPI 응답 파싱 실패"]

        record_rapidapi()

        # Build lookup: Carriers, Places, Quotes
        carriers = {c["CarrierId"]: c.get("Name", "") for c in data.get("Carriers", [])}
        quotes = data.get("Quotes", [])

        flights = []
        for q in quotes[:10]:
            out = q.get("OutboundLeg", {})
            cids = out.get("CarrierIds", [])
            cid = cids[0] if cids else None
            airline = carriers.get(cid, "Unknown") if cid else "Unknown"
            price = q.get("MinPrice")
            price_krw = int(price) if price is not None else None
            dep = out.get("DepartureDate", "")[:19]
            # Skyscanner doesn't always give arrival in quotes
            arrival = dep  # placeholder
            flights.append(
                _normalize_flight(
                    airline=airline,
                    flight_number="",
                    departure=dep,
                    arrival=arrival,
                    origin=origin,
                    destination=destination,
                    price_krw=price_krw,
                    miles_required=None,
                    flight_id=str(q.get("QuoteId", "")),
                )
            )

        return flights, warnings

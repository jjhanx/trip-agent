"""Amadeus Transfer Offers API — 공항↔시내 1회 이동 견적 (셀프 드라이브 렌트와 별개 제품).

https://developers.amadeus.com/self-service/category/cars/api-doc/transfer-offers
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

AMADEUS_TOKEN_URL = "https://test.api.amadeus.com/v1/security/oauth2/token"
AMADEUS_TRANSFER_URL = "https://test.api.amadeus.com/v1/shopping/transfer-offers"

# 대략적 환산(표시용). 정확한 환율이 필요하면 외부 환율 API 연동.
_FX_TO_KRW: dict[str, float] = {
    "KRW": 1.0,
    "USD": 1450.0,
    "EUR": 1580.0,
    "GBP": 1880.0,
    "JPY": 9.2,
}


def _get_token(client_id: str, client_secret: str) -> str | None:
    if not client_id or not client_secret:
        return None
    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.post(
                AMADEUS_TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        if r.status_code != 200:
            logger.warning("Amadeus token HTTP %s", r.status_code)
            return None
        return r.json().get("access_token")
    except Exception as e:
        logger.warning("Amadeus token error: %s", e)
        return None


def _normalize_start_datetime(dt: str) -> str:
    s = (dt or "").strip().replace(" ", "T")
    if len(s) == 16 and s[10] == "T":
        return s + ":00"
    if len(s) >= 19:
        return s[:19]
    return s


def _quotation_to_krw(q: dict | None) -> tuple[int | None, str | None, str | None]:
    if not q or not isinstance(q, dict):
        return None, None, None
    raw = q.get("monetaryAmount")
    if raw is None:
        return None, None, None
    try:
        amount = float(str(raw).replace(",", ""))
    except (TypeError, ValueError):
        return None, None, None
    cur = (q.get("currencyCode") or "EUR").upper()
    rate = _FX_TO_KRW.get(cur)
    if rate is None:
        return None, f"{raw}", cur
    krw = int(round(amount * rate))
    return krw, f"{raw}", cur


def _vehicle_seats(vehicle: dict | None) -> int | None:
    if not vehicle or not isinstance(vehicle, dict):
        return None
    seats = vehicle.get("seats")
    if isinstance(seats, list) and seats:
        total = 0
        for s in seats:
            if isinstance(s, dict) and s.get("count") is not None:
                total += int(s["count"])
        return total if total > 0 else None
    return None


def _vehicle_bags(vehicle: dict | None) -> str | None:
    if not vehicle or not isinstance(vehicle, dict):
        return None
    bags = vehicle.get("baggages")
    if not isinstance(bags, list) or not bags:
        return None
    parts = []
    for b in bags:
        if isinstance(b, dict):
            c, sz = b.get("count"), b.get("size")
            if c is not None:
                parts.append(f"{c}×{sz or 'M'}")
    return ", ".join(parts) if parts else None


def _offer_to_card(
    offer: dict,
    *,
    leg: str,
    idx: int,
    passengers: int,
) -> dict | None:
    if not isinstance(offer, dict) or offer.get("type") != "transfer-offer":
        return None
    oid = str(offer.get("id") or idx)
    vehicle = offer.get("vehicle") if isinstance(offer.get("vehicle"), dict) else {}
    sp = offer.get("serviceProvider") if isinstance(offer.get("serviceProvider"), dict) else {}
    q = offer.get("quotation") if isinstance(offer.get("quotation"), dict) else {}
    krw, amt, cur = _quotation_to_krw(q)
    if krw is None:
        return None
    desc = (vehicle.get("description") or "").strip() or "Transfer"
    seats = _vehicle_seats(vehicle) or passengers
    bags = _vehicle_bags(vehicle)
    ttype = offer.get("transferType") or ""
    vcode = vehicle.get("code") or ""
    features = [x for x in (ttype, vcode) if x]
    img = vehicle.get("imageURL") or vehicle.get("imageUrl")
    leg_ko = "공항→시내" if leg == "arrival" else "시내→공항"
    prov = (sp.get("name") or "Provider").strip()
    terms = (sp.get("termsUrl") or sp.get("terms_url") or "").strip()
    return {
        "rental_id": f"AMADEUS-{leg}-{oid[:12]}",
        "offer_kind": "amadeus_transfer",
        "transfer_leg": leg,
        "provider": f"Amadeus 트랜스퍼 · {prov}",
        "car_type": (vcode or "transfer").lower(),
        "seats": seats,
        "vehicle_name": desc,
        "description": f"{leg_ko} 1회 이동 견적 · {ttype or 'PRIVATE'}",
        "features": features,
        "luggage_capacity": bags or "차량·업체 기준",
        "image_url": img if isinstance(img, str) else None,
        "pickup_location": leg_ko,
        "dropoff_location": "",
        "price_total_krw": krw,
        "price_original_amount": amt,
        "price_original_currency": cur,
        "price_basis": (
            "Amadeus Transfer API 기준 1회 구간 견적입니다. "
            "셀프 드라이브 렌트의 ‘기간 총 렌트료’와는 다른 상품입니다."
        ),
        "recommended": seats >= passengers,
        "booking_url": terms if terms else None,
        "source_label": "Amadeus Transfer API",
    }


def fetch_transfer_offers(
    body: dict[str, Any],
    client_id: str,
    client_secret: str,
) -> list[dict]:
    token = _get_token(client_id, client_secret)
    if not token:
        return []
    try:
        with httpx.Client(timeout=35.0) as client:
            r = client.post(
                AMADEUS_TRANSFER_URL,
                json=body,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/vnd.amadeus+json",
                    "Accept": "application/vnd.amadeus+json",
                },
            )
    except Exception as e:
        logger.warning("Amadeus transfer POST failed: %s", e)
        return []
    if r.status_code != 200:
        logger.warning("Amadeus transfer HTTP %s: %s", r.status_code, r.text[:500])
        return []
    try:
        data = r.json()
    except Exception:
        return []
    arr = data.get("data")
    if not isinstance(arr, list):
        return []
    return [x for x in arr if isinstance(x, dict)]


def search_airport_to_city(
    airport_iata: str,
    start_datetime: str,
    end_city: str,
    end_country: str,
    passengers: int,
    client_id: str,
    client_secret: str,
    max_offers: int = 8,
) -> list[dict]:
    iata = (airport_iata or "").strip().upper()[:3]
    city = (end_city or "").strip()
    cc = (end_country or "").strip().upper()[:2]
    if len(iata) != 3 or not city or len(cc) != 2:
        return []
    body: dict[str, Any] = {
        "startLocationCode": iata,
        "startDateTime": _normalize_start_datetime(start_datetime),
        "endCityName": city[:35],
        "endCountryCode": cc,
        "passengers": max(1, min(passengers, 8)),
        "currency": "KRW",
    }
    offers = fetch_transfer_offers(body, client_id, client_secret)
    cards = []
    for i, o in enumerate(offers):
        c = _offer_to_card(o, leg="arrival", idx=i, passengers=passengers)
        if c:
            cards.append(c)
    cards.sort(key=lambda x: x.get("price_total_krw") or 0)
    return cards[:max_offers]


def search_city_to_airport(
    airport_iata: str,
    start_datetime: str,
    start_city: str,
    start_country: str,
    passengers: int,
    client_id: str,
    client_secret: str,
    max_offers: int = 8,
) -> list[dict]:
    iata = (airport_iata or "").strip().upper()[:3]
    city = (start_city or "").strip()
    cc = (start_country or "").strip().upper()[:2]
    if len(iata) != 3 or not city or len(cc) != 2:
        return []
    body: dict[str, Any] = {
        "startCityName": city[:35],
        "startCountryCode": cc,
        "startDateTime": _normalize_start_datetime(start_datetime),
        "endLocationCode": iata,
        "passengers": max(1, min(passengers, 8)),
        "currency": "KRW",
    }
    offers = fetch_transfer_offers(body, client_id, client_secret)
    cards = []
    for i, o in enumerate(offers):
        c = _offer_to_card(o, leg="departure", idx=i, passengers=passengers)
        if c:
            cards.append(c)
    cards.sort(key=lambda x: x.get("price_total_krw") or 0)
    return cards[:max_offers]

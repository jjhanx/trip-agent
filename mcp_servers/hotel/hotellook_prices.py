"""Travelpayouts Hotellook — 숙소 최저가 힌트(캐시 API). 실패 시 None."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

HOTELLOOK = "http://engine.hotellook.com/api/v2"
# 캐시 요금은 통화별 — EUR→KRW 대략(표시용, 실제 예약과 다를 수 있음)
_EUR_TO_KRW = 1450.0


def _normalize_name(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower().strip())


def _similarity(a: str, b: str) -> float:
    """아주 단순한 부분 일치 점수."""
    if not a or not b:
        return 0.0
    a, b = _normalize_name(a), _normalize_name(b)
    if a in b or b in a:
        return 0.9
    wa, wb = set(a.split()), set(b.split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / max(len(wa), len(wb))


def fetch_hotellook_min_price(
    hotel_display_name: str,
    lat: float,
    lng: float,
    check_in: str,
    check_out: str,
    token: str,
    rooms: int = 1,
) -> tuple[int | None, str, str | None]:
    """(krw_estimate, currency_note, deep_link_or_none).

    rooms: 일행 기준 필요 객실 수(가격에 곱함).
    """
    if not (token or "").strip():
        return None, "", None
    try:
        q = urlencode(
            {
                "query": f"{lat:.5f},{lng:.5f}",
                "lang": "en",
                "lookFor": "hotel",
                "limit": 20,
                "token": token.strip(),
            }
        )
        with httpx.Client(timeout=25.0) as client:
            r = client.get(f"{HOTELLOOK}/lookup.json?{q}")
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.debug("hotellook lookup failed: %s", e)
        return None, "", None

    hotels: list = []
    if isinstance(data, dict):
        res = data.get("results")
        if isinstance(res, dict):
            hotels = res.get("hotels") or []
        if not hotels and isinstance(data.get("hotels"), list):
            hotels = data["hotels"]
    if not isinstance(hotels, list):
        return None, "", None
    if not isinstance(hotels, list) or not hotels:
        return None, "", None

    best: dict[str, Any] | None = None
    best_sc = 0.0
    for h in hotels:
        if not isinstance(h, dict):
            continue
        nm = str(h.get("name") or h.get("label") or "")
        hid = h.get("id") or h.get("hotel_id")
        if hid is None:
            continue
        sc = _similarity(hotel_display_name, nm)
        if sc > best_sc:
            best_sc = sc
            best = h
    if best is None or best_sc < 0.15:
        best = hotels[0] if isinstance(hotels[0], dict) else None
    if not best:
        return None, "", None

    hid = best.get("id") or best.get("hotel_id")
    if hid is None:
        return None, "", None

    loc = {}
    if isinstance(data, dict):
        res = data.get("results")
        if isinstance(res, dict):
            loc = res.get("location") if isinstance(res.get("location"), dict) else {}
    loc_name = str(loc.get("name") or loc.get("id") or data.get("location") or "unknown")

    try:
        q2 = urlencode(
            {
                "location": loc_name,
                "hotelId": str(hid),
                "checkIn": check_in[:10],
                "checkOut": check_out[:10],
                "currency": "eur",
                "limit": 5,
                "token": token.strip(),
            }
        )
        with httpx.Client(timeout=25.0) as client:
            r2 = client.get(f"{HOTELLOOK}/cache.json?{q2}")
            r2.raise_for_status()
            cdata = r2.json()
    except Exception as e:
        logger.debug("hotellook cache failed: %s", e)
        return None, "EUR(조회 실패)", None

    hotels_c = cdata.get("hotels") if isinstance(cdata, dict) else None
    if not isinstance(hotels_c, list) or not hotels_c:
        return None, "EUR", None

    h0 = hotels_c[0] if isinstance(hotels_c[0], dict) else {}
    price = h0.get("price") or h0.get("minPrice") or h0.get("priceAvg")
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None, "EUR", None

    total_eur = p * max(1, rooms)
    krw = int(round(total_eur * _EUR_TO_KRW))
    link = None
    if isinstance(h0.get("location"), dict):
        link = h0.get("location", {}).get("url")
    return krw, "EUR(캐시·객실×추정)", link

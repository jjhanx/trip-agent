"""Travelpayouts Hotellook — 숙소 캐시 요금·식사 옵션 파싱(실시간 재고 아님)."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
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
    if not a or not b:
        return 0.0
    a, b = _normalize_name(a), _normalize_name(b)
    if a in b or b in a:
        return 0.9
    wa, wb = set(a.split()), set(b.split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / max(len(wa), len(wb))


def _float_price(d: dict[str, Any]) -> float | None:
    for k in ("price", "minPrice", "priceAvg", "total", "value", "amount"):
        v = d.get(k)
        if v is None:
            continue
        try:
            p = float(v)
            if p > 0:
                return p
        except (TypeError, ValueError):
            continue
    return None


def _text_blob_for_meal(d: dict[str, Any]) -> str:
    parts: list[str] = []
    for k in (
        "roomName",
        "room_name",
        "name",
        "fullName",
        "description",
        "label",
        "type",
        "meal",
        "mealType",
        "board",
        "category",
        "title",
    ):
        v = d.get(k)
        if v is not None and not isinstance(v, (dict, list)):
            parts.append(str(v))
    return " ".join(parts)


def _breakfast_in_blob(blob: str) -> bool:
    b = blob.lower()
    if any(
        x in b
        for x in (
            "breakfast",
            "b&b",
            "bed and breakfast",
            "buffet breakfast",
            "continental breakfast",
        )
    ):
        return True
    if "조식" in blob or "朝食" in blob:
        return True
    if re.search(r"\bbb\b", b) and "breakfast" in b:
        return True
    return False


def _half_full_board_in_blob(blob: str) -> bool:
    b = blob.lower()
    return any(
        x in b
        for x in (
            "half board",
            "half-board",
            "demi-pension",
            "halbpension",
            "full board",
            "all inclusive",
            "all-inclusive",
        )
    )


def _node_meal_included(node: dict[str, Any]) -> bool:
    blob = _text_blob_for_meal(node) + " " + json.dumps(node, ensure_ascii=False)[:600]
    return _breakfast_in_blob(blob) or _half_full_board_in_blob(blob)


def _collect_priced_dicts(obj: Any, acc: list[dict[str, Any]]) -> None:
    """cache.json 전체를 순회해 가격 필드가 있는 dict를 모은다."""
    if isinstance(obj, dict):
        if _float_price(obj) is not None:
            acc.append(obj)
        for v in obj.values():
            if isinstance(v, (dict, list)):
                _collect_priced_dicts(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _collect_priced_dicts(v, acc)


def _extract_booking_link(hotel_block: dict[str, Any], cdata: dict[str, Any]) -> str | None:
    for root in (hotel_block, cdata):
        if not isinstance(root, dict):
            continue
        for k in ("bookingUrl", "booking_url", "deepLink", "deep_link", "url"):
            u = root.get(k)
            if isinstance(u, str) and u.startswith("http"):
                return u.strip()
        loc = root.get("location")
        if isinstance(loc, dict):
            u = loc.get("url")
            if isinstance(u, str) and u.startswith("http"):
                return u.strip()
    return None


def fetch_hotellook_stay_quote(
    hotel_display_name: str,
    lat: float,
    lng: float,
    check_in: str,
    check_out: str,
    token: str,
    rooms: int = 1,
) -> dict[str, Any]:
    """Hotellook lookup + cache 기반 견적(캐시·실시간 재고 아님).

    반환 키:
      total_krw_estimate, price_per_night_krw, currency_note, booking_deep_link,
      rates_in_cache, breakfast_included, room_meal_label,
      meal_plan_summary_ko, availability_note_ko, price_basis_note
    """
    empty = {
        "total_krw_estimate": None,
        "price_per_night_krw": None,
        "currency_note": "",
        "booking_deep_link": None,
        "rates_in_cache": False,
        "breakfast_included": None,
        "room_meal_label": None,
        "meal_plan_summary_ko": None,
        "availability_note_ko": None,
        "price_basis_note": None,
    }
    if not (token or "").strip():
        empty["availability_note_ko"] = (
            "실시간 예약 가능 여부·요금은 서버에 TRAVELPAYOUTS_API_TOKEN이 있을 때 "
            "Hotellook 캐시로 채웁니다(캐시는 실제 재고와 다를 수 있음)."
        )
        return empty

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
        empty["availability_note_ko"] = "Hotellook 호텔 매칭(lookup)에 실패했습니다. 좌표·이름을 확인하세요."
        return empty

    hotels: list = []
    if isinstance(data, dict):
        res = data.get("results")
        if isinstance(res, dict):
            hotels = res.get("hotels") or []
        if not hotels and isinstance(data.get("hotels"), list):
            hotels = data["hotels"]
    if not isinstance(hotels, list) or not hotels:
        empty["availability_note_ko"] = "Hotellook에서 근처 호텔 목록을 받지 못했습니다."
        return empty

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
        empty["availability_note_ko"] = "Hotellook 호텔을 고르지 못했습니다."
        return empty

    hid = best.get("id") or best.get("hotel_id")
    if hid is None:
        return empty

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
                "limit": 20,
                "token": token.strip(),
            }
        )
        with httpx.Client(timeout=25.0) as client:
            r2 = client.get(f"{HOTELLOOK}/cache.json?{q2}")
            r2.raise_for_status()
            cdata = r2.json()
    except Exception as e:
        logger.debug("hotellook cache failed: %s", e)
        empty["availability_note_ko"] = (
            f"해당 체크인·체크아웃({check_in[:10]}~{check_out[:10]})의 캐시 요금을 가져오지 못했습니다. "
            "예약 링크에서 일정·인원을 맞춰 재고를 확인하세요."
        )
        empty["currency_note"] = "EUR(조회 실패)"
        return empty

    if not isinstance(cdata, dict):
        empty["availability_note_ko"] = "Hotellook 캐시 응답 형식이 올바르지 않습니다."
        return empty

    hotels_c = cdata.get("hotels")
    if not isinstance(hotels_c, list) or not hotels_c:
        empty["availability_note_ko"] = (
            "Hotellook 캐시에 해당 일정·호텔 조합의 요금이 없습니다. "
            "반드시 매진은 아니며 집계에 없을 수 있으니 예약 사이트에서 동일 일정으로 검색해 주세요."
        )
        return empty

    h0 = hotels_c[0] if isinstance(hotels_c[0], dict) else {}
    priced_nodes: list[dict[str, Any]] = []
    _collect_priced_dicts(cdata, priced_nodes)

    # 중복 제거(동일 가격·유사 텍스트)
    seen: set[tuple[float, str]] = set()
    unique: list[dict[str, Any]] = []
    for node in priced_nodes:
        p = _float_price(node)
        if p is None:
            continue
        label = _text_blob_for_meal(node)
        key = (round(p, 2), label[:80])
        if key in seen:
            continue
        seen.add(key)
        unique.append(node)

    if not unique:
        # 폴백: 구버전 단일 price 필드
        p0 = _float_price(h0)
        if p0 is None:
            empty["availability_note_ko"] = "캐시에 파싱 가능한 요금 필드가 없습니다."
            return empty
        unique = [h0]

    breakfast_nodes = [n for n in unique if _node_meal_included(n)]
    if breakfast_nodes:
        best_node = min(breakfast_nodes, key=lambda n: _float_price(n) or 1e12)
    else:
        best_node = min(unique, key=lambda n: _float_price(n) or 1e12)

    p_best = _float_price(best_node)
    if p_best is None:
        empty["availability_note_ko"] = "요금 숫자를 해석하지 못했습니다."
        return empty

    brk = _node_meal_included(best_node)

    total_eur = p_best * max(1, rooms)
    krw = int(round(total_eur * _EUR_TO_KRW))

    room_label = (_text_blob_for_meal(best_node) or "").strip()
    if len(room_label) > 120:
        room_label = room_label[:117] + "…"

    link = _extract_booking_link(h0, cdata)

    nights_hint = max(1, _nights_from_dates(check_in, check_out))
    ppn_krw = int(round(krw / nights_hint)) if nights_hint else krw

    meal_ko = (
        "조식(또는 식사 포함) 옵션 중 캐시상 최저가를 우선 표시했습니다."
        if brk
        else "캐시에 조식 포함 요금이 명확히 없어, 표시 금액은 룸온리 등 최저가에 가까운 옵션일 수 있습니다."
    )

    avail_ko = (
        "이 금액은 Travelpayouts·Hotellook 캐시 집계이며, 실시간 잔여 객실·최종 요금과 다를 수 있습니다. "
        "예약 가능 여부는 링크에서 동일 날짜·인원(및 객실 수)으로 확인하세요."
    )

    basis = (
        f"Hotellook 캐시 EUR→약 {int(_EUR_TO_KRW)}원 환산 · 객실 {rooms}실 · "
        f"{'조식·식사 포함 후보 우선' if brk else '최저가 후보'}"
    )

    return {
        "total_krw_estimate": krw,
        "price_per_night_krw": ppn_krw,
        "currency_note": "EUR(캐시·객실×추정)",
        "booking_deep_link": link,
        "rates_in_cache": True,
        "breakfast_included": bool(brk),
        "room_meal_label": room_label or None,
        "meal_plan_summary_ko": meal_ko,
        "availability_note_ko": avail_ko,
        "price_basis_note": basis,
    }


def _nights_from_dates(check_in: str, check_out: str) -> int:
    try:
        a = datetime.strptime((check_in or "")[:10], "%Y-%m-%d").date()
        b = datetime.strptime((check_out or "")[:10], "%Y-%m-%d").date()
        return max(1, (b - a).days)
    except (ValueError, TypeError):
        return 1


def fetch_hotellook_min_price(
    hotel_display_name: str,
    lat: float,
    lng: float,
    check_in: str,
    check_out: str,
    token: str,
    rooms: int = 1,
) -> tuple[int | None, str, str | None]:
    """(krw_estimate, currency_note, deep_link_or_none) — 하위 호환."""
    q = fetch_hotellook_stay_quote(
        hotel_display_name,
        lat,
        lng,
        check_in,
        check_out,
        token,
        rooms=rooms,
    )
    return (
        q.get("total_krw_estimate"),
        str(q.get("currency_note") or ""),
        q.get("booking_deep_link"),
    )

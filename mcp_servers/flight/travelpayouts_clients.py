"""Travelpayouts Flight Data API — 캐시 기반 최저가 (cheap / direct).

https://api.travelpayouts.com/documentation
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

BASE_URL = "https://api.travelpayouts.com"

# 응답 통화가 KRW가 아닐 때 대략 환산 (표시용)
_ROUGH_KRW_PER_UNIT = {"usd": 1400, "eur": 1500, "rub": 18, "gbp": 1800}


def _iso_from_tp_at(s: str | None) -> str:
    """Travelpayouts ISO 시간 → 프론트용 YYYY-MM-DDTHH:MM:SS (로컬 표시 근사)."""
    if not s:
        return ""
    t = str(s).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(t)
        return dt.strftime("%Y-%m-%dT%H:%M:00")
    except ValueError:
        if len(s) >= 19:
            return s[:19].replace(" ", "T")
        return s


def _flatten_cheap_data(raw: Any) -> list[dict[str, Any]]:
    """data 필드: { DEST: { \"0\": ticket, \"1\": ... } } 형태."""
    out: list[dict[str, Any]] = []
    if not isinstance(raw, dict):
        return out
    for _dest_key, inner in raw.items():
        if isinstance(inner, dict):
            for _idx, item in inner.items():
                if isinstance(item, dict) and ("price" in item or "departure_at" in item):
                    out.append(item)
        elif isinstance(inner, list):
            for item in inner:
                if isinstance(item, dict):
                    out.append(item)
    return out


def _price_to_krw(amount: float | int | None, currency: str) -> int | None:
    if amount is None:
        return None
    try:
        v = float(amount)
    except (TypeError, ValueError):
        return None
    c = (currency or "rub").lower()
    if c == "krw":
        return int(round(v))
    mult = _ROUGH_KRW_PER_UNIT.get(c, 1400 if c == "usd" else 1500)
    return int(round(v * mult))


def build_aviasales_search_url(
    origin: str,
    destination: str,
    depart_date: str,
    return_date: str | None,
    marker: str,
    *,
    one_way: bool,
    currency: str = "KRW",
) -> str:
    """Aviasales 검색 딥링크 (marker=제휴 마커)."""
    o = (origin or "").upper()[:3]
    d = (destination or "").upper()[:3]
    dep = (depart_date or "")[:10]
    ret = (return_date or "")[:10] if return_date else ""
    if one_way or not ret:
        path = f"{o}/{d}/{dep}"
    else:
        path = f"{o}/{d}/{dep}/{ret}"
    q = {
        "marker": marker,
        "currency": currency,
        "adults": 1,
        "children": 0,
        "infants": 0,
        "is_one_way": "true" if one_way else "false",
    }
    return f"https://www.aviasales.com/search/{path}?{urlencode(q)}"


def _leg_from_tp(
    airline: str,
    flight_number: str | int,
    dep_iso: str,
    arr_iso: str,
    origin: str,
    destination: str,
    duration_hours: float | None,
    is_direct: bool,
    seat_class: str,
) -> dict[str, Any]:
    fn = str(flight_number).strip() if flight_number is not None else ""
    return {
        "airline": airline or "Unknown",
        "flight_number": fn,
        "departure": dep_iso,
        "arrival": arr_iso,
        "origin": origin,
        "destination": destination,
        "duration_hours": duration_hours,
        "is_direct": is_direct,
        "seat_class": seat_class,
        "source": "api",
    }


def _estimate_arrival(dep_iso: str, duration_hours: float | None) -> str:
    if not dep_iso or not duration_hours or duration_hours <= 0:
        return dep_iso
    try:
        raw = dep_iso.replace("T", " ")[:19]
        dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        return (dt + timedelta(hours=duration_hours)).strftime("%Y-%m-%dT%H:%M:00")
    except ValueError:
        return dep_iso


async def search_travelpayouts_flights(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    token: str,
    *,
    one_way: bool = False,
    seat_class: str = "economy",
    marker: str = "",
    direct_only: bool = False,
    currency: str = "krw",
    quiet: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    cheap 또는 direct 엔드포인트 호출 → SerpApi와 유사한 flight / round_trip dict 목록.
    """
    warnings: list[str] = []
    o = (origin or "").strip().upper()[:3]
    d = (destination or "").strip().upper()[:3]
    if len(o) != 3 or len(d) != 3:
        return [], ["Travelpayouts: 출발/도착은 IATA 공항(도시) 코드 3자리여야 합니다."]

    if not (token or "").strip():
        return [], []

    depart = (start_date or "")[:10]
    ret_part = (end_date or "")[:10] if not one_way else None

    params: dict[str, str] = {
        "origin": o,
        "destination": d,
        "currency": currency.lower(),
        "depart_date": depart if len(depart) == 10 else (start_date or "")[:7],
    }
    if ret_part and len(ret_part) == 10:
        params["return_date"] = ret_part
    elif not one_way and end_date:
        params["return_date"] = (end_date or "")[:7]

    path = "/v1/prices/direct" if direct_only else "/v1/prices/cheap"
    headers = {"X-Access-Token": token.strip()}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{BASE_URL}{path}", headers=headers, params=params)
    except httpx.RequestError as e:
        return [], [f"Travelpayouts 네트워크 오류: {e}"]

    if resp.status_code == 429:
        return [], ["Travelpayouts API 요청 한도 초과(429). 잠시 후 재시도하세요."]
    if resp.status_code != 200:
        return [], [f"Travelpayouts API 오류: HTTP {resp.status_code}"]

    try:
        body = resp.json()
    except Exception:
        return [], ["Travelpayouts 응답 JSON 파싱 실패"]

    if not body.get("success"):
        return [], ["Travelpayouts 검색 실패(success=false)."]

    resp_currency = str(body.get("currency") or currency or "krw").lower()
    raw_data = body.get("data")
    items = _flatten_cheap_data(raw_data)
    if not items and len(depart) == 10:
        params_month = {**params, "depart_date": depart[:7]}
        if "return_date" in params and len(params["return_date"]) == 10:
            params_month["return_date"] = params["return_date"][:7]
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp2 = await client.get(f"{BASE_URL}{path}", headers=headers, params=params_month)
            if resp2.status_code == 200:
                body2 = resp2.json()
                if body2.get("success"):
                    items = _flatten_cheap_data(body2.get("data"))
                    resp_currency = str(body2.get("currency") or resp_currency).lower()
                    if items:
                        warnings.append(
                            "Travelpayouts: 일별 데이터가 없어 해당 월(yyyy-mm) 기준 캐시 가격을 표시합니다."
                        )
        except Exception:
            pass

    if not items:
        return [], []

    mk = (marker or "").strip()
    flights: list[dict[str, Any]] = []

    for idx, it in enumerate(sorted(items, key=lambda x: float(x.get("price") or 1e18))[:40]):
        price_raw = it.get("price")
        airline = str(it.get("airline") or "").strip() or "Unknown"
        fn = it.get("flight_number", "")
        dep_at = _iso_from_tp_at(it.get("departure_at"))
        ret_at = _iso_from_tp_at(it.get("return_at")) if it.get("return_at") else ""
        transfers = it.get("number_of_changes", it.get("transfers"))
        if transfers is None:
            is_direct = direct_only
        else:
            try:
                is_direct = int(transfers) == 0
            except (TypeError, ValueError):
                is_direct = direct_only

        dur_min = it.get("duration")
        try:
            dur_h_total = float(dur_min) / 60.0 if dur_min is not None else None
        except (TypeError, ValueError):
            dur_h_total = None

        price_krw = _price_to_krw(price_raw, resp_currency)
        booking_url = (
            build_aviasales_search_url(o, d, depart, ret_part, mk, one_way=one_way)
            if mk
            else ""
        )

        if one_way or not ret_at:
            ob_dur = dur_h_total
            ob_arr = _estimate_arrival(dep_at, ob_dur)
            leg = _leg_from_tp(airline, fn, dep_at, ob_arr, o, d, ob_dur, is_direct, seat_class)
            flights.append(
                {
                    **leg,
                    "flight_id": f"tp_{idx}_{airline}_{fn}_{dep_at}",
                    "price_krw": price_krw,
                    "miles_required": None,
                    "seat_class": seat_class,
                    "source": "api",
                    "booking_url": booking_url,
                    "data_source": "travelpayouts",
                }
            )
        else:
            ob_dur = (dur_h_total / 2.0) if dur_h_total else 3.0
            ret_dur = (dur_h_total / 2.0) if dur_h_total else 3.0
            ob_arr = _estimate_arrival(dep_at, ob_dur)
            ret_arr = _estimate_arrival(ret_at, ret_dur)
            ob_leg = _leg_from_tp(airline, fn, dep_at, ob_arr, o, d, ob_dur, is_direct, seat_class)
            ret_leg = _leg_from_tp(airline, fn, ret_at, ret_arr, d, o, ret_dur, is_direct, seat_class)
            flights.append(
                {
                    "round_trip": True,
                    "flight_id": f"tp_rt_{idx}_{airline}_{fn}_{dep_at}",
                    "price_krw": price_krw,
                    "miles_required": None,
                    "seat_class": seat_class,
                    "source": "api",
                    "outbound": ob_leg,
                    "return": ret_leg,
                    "booking_url": booking_url,
                    "data_source": "travelpayouts",
                }
            )

    if flights and not quiet:
        warnings.append(
            "항공료는 Travelpayouts(캐시) 기준 참고가이며, 실시간·최종 가격은 예약 링크(Aviasales)에서 확인하세요."
        )
    return flights, warnings

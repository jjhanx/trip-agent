"""Google Places(Nearby) + Distance Matrix로 일정 명소 대비 주행시간이 짧은 숙소 후보를 고른다."""

from __future__ import annotations

import logging
import math
import os
import time
from typing import Any
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "TripAgent/1.0 (hotel route optimization)"


def _get_json(url: str) -> dict[str, Any] | None:
    try:
        with httpx.Client(timeout=35.0, headers={"User-Agent": USER_AGENT}) as client:
            r = client.get(url)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        logger.warning("google_places_hotels HTTP failed: %s", e)
        return None


def geocode_text(address: str, api_key: str) -> tuple[float, float] | None:
    if not (address or "").strip() or not (api_key or "").strip():
        return None
    q = urlencode({"address": address.strip(), "key": api_key})
    url = f"https://maps.googleapis.com/maps/api/geocode/json?{q}"
    data = _get_json(url)
    if not data or data.get("status") not in ("OK",):
        return None
    results = data.get("results") or []
    if not results:
        return None
    loc = results[0].get("geometry", {}).get("location", {})
    lat, lng = loc.get("lat"), loc.get("lng")
    if lat is None or lng is None:
        return None
    return float(lat), float(lng)


def _centroid(points: list[dict[str, Any]]) -> tuple[float, float]:
    lat = sum(p["lat"] for p in points) / len(points)
    lng = sum(p["lng"] for p in points) / len(points)
    return lat, lng


def _radius_for_points(center: tuple[float, float], points: list[dict[str, Any]]) -> int:
    """명소까지 거리 + 여유로 Nearby 반경(미터), 최대 50km."""
    clat, clng = center
    max_km = 0.0
    for p in points:
        km = _haversine_km(clat, clng, p["lat"], p["lng"])
        max_km = max(max_km, km)
    # 반경은 중심에서 가장 먼 명소까지 + 약 15km 버퍼, 최소 8km
    r = int(max(8000, (max_km + 15) * 1000))
    return min(50000, r)


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(min(1.0, a)))


def nearby_lodging(
    lat: float,
    lng: float,
    radius_m: int,
    api_key: str,
    page_token: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Returns (results, next_page_token)."""
    params: dict[str, Any] = {
        "location": f"{lat},{lng}",
        "radius": str(radius_m),
        "type": "lodging",
        "key": api_key,
    }
    if page_token:
        params = {"pagetoken": page_token, "key": api_key}
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json?" + urlencode(params)
    data = _get_json(url)
    if not data or data.get("status") not in ("OK", "ZERO_RESULTS"):
        logger.warning("nearbysearch status=%s", (data or {}).get("status"))
        return [], None
    return data.get("results") or [], data.get("next_page_token")


def place_details_fields(place_id: str, api_key: str) -> dict[str, Any] | None:
    fields = (
        "place_id,name,rating,user_ratings_total,formatted_address,geometry,"
        "photos,url,price_level,international_phone_number,types"
    )
    q = urlencode(
        {"place_id": place_id, "fields": fields, "key": api_key, "language": "ko"},
    )
    url = f"https://maps.googleapis.com/maps/api/place/details/json?{q}"
    data = _get_json(url)
    if not data or data.get("status") not in ("OK",):
        return None
    return data.get("result")


def photo_url(photo_reference: str, api_key: str, max_width: int = 800) -> str:
    q = urlencode({"maxwidth": str(max_width), "photo_reference": photo_reference, "key": api_key})
    return f"https://maps.googleapis.com/maps/api/place/photo?{q}"


def distance_matrix_durations_minutes(
    origin_lat: float,
    origin_lng: float,
    dest_points: list[dict[str, Any]],
    api_key: str,
) -> list[tuple[str, int | None]]:
    """각 목적지까지 편도 주행 분. 이름은 dest_points[].name."""
    if not dest_points:
        return []
    # 한 요청당 destination 최대 ~25 (문서상 25 destinations)
    origins = f"{origin_lat},{origin_lng}"
    parts: list[str] = []
    for p in dest_points[:25]:
        parts.append(f"{p['lat']},{p['lng']}")
    if not parts:
        return []
    dest = "|".join(parts)
    q = urlencode(
        {
            "origins": origins,
            "destinations": dest,
            "mode": "driving",
            "key": api_key,
            "language": "ko",
        }
    )
    url = f"https://maps.googleapis.com/maps/api/distancematrix/json?{q}"
    data = _get_json(url)
    if not data or data.get("status") not in ("OK",):
        return [(p["name"], None) for p in dest_points[:25]]
    row = (data.get("rows") or [{}])[0]
    elems = row.get("elements") or []
    out: list[tuple[str, int | None]] = []
    for i, p in enumerate(dest_points[:25]):
        el = elems[i] if i < len(elems) else {}
        if el.get("status") != "OK":
            out.append((p["name"], None))
            continue
        sec = (el.get("duration") or {}).get("value")
        if sec is None:
            out.append((p["name"], None))
        else:
            out.append((p["name"], max(1, int(round(sec / 60)))))
    return out


def _score_total_minutes(pairs: list[tuple[str, int | None]]) -> float:
    s = 0
    n = 0
    for _, m in pairs:
        if m is not None:
            s += m
            n += 1
    if n == 0:
        return float("inf")
    return float(s)


def search_route_optimized_hotels(
    *,
    location_label: str,
    attraction_points: list[dict[str, Any]],
    check_in: str,
    check_out: str,
    travelers_total: int,
    api_key: str | None,
) -> list[dict[str, Any]] | None:
    """실패 시 None (호출 측에서 mock으로 폴백)."""
    key = (api_key or os.environ.get("GOOGLE_PLACES_API_KEY") or "").strip()
    if not key:
        return None

    points = [p for p in attraction_points if isinstance(p, dict)]
    if points:
        center = _centroid(points)
        radius = _radius_for_points(center, points)
    else:
        g = geocode_text(location_label, key)
        if not g:
            return None
        center = g
        radius = 15000

    # Nearby 후보 수집 (최대 2페이지)
    raw: list[dict[str, Any]] = []
    tok: str | None = None
    for _ in range(2):
        batch, tok = nearby_lodging(center[0], center[1], radius, key, page_token=tok)
        raw.extend(batch)
        if not tok:
            break
        time.sleep(2.0)  # next_page_token 유효화 대기

    if not raw:
        return None

    def sort_key(r: dict[str, Any]) -> tuple[float, float]:
        rating = float(r.get("rating") or 0)
        nrat = float(r.get("user_ratings_total") or 0)
        return (-rating * math.log10(nrat + 10), -nrat)

    raw.sort(key=sort_key)
    candidates = raw[:8]

    scored: list[tuple[float, dict[str, Any], list[tuple[str, int | None]]]] = []
    dest_for_matrix = points[:25] if points else []
    for c in candidates:
        pid = c.get("place_id")
        if not pid:
            continue
        det = place_details_fields(pid, key)
        if not det:
            continue
        loc = (det.get("geometry") or {}).get("location") or {}
        hlat, hlng = loc.get("lat"), loc.get("lng")
        if hlat is None or hlng is None:
            continue
        if dest_for_matrix:
            pairs = distance_matrix_durations_minutes(
                float(hlat), float(hlng), dest_for_matrix, key
            )
            total = _score_total_minutes(pairs)
        else:
            pairs = []
            total = 0.0
        scored.append((total, det, pairs))

    if not scored:
        return None

    if dest_for_matrix:
        scored.sort(key=lambda x: x[0])
    else:
        scored.sort(
            key=lambda x: (
                -float((x[1] or {}).get("rating") or 0),
                -float((x[1] or {}).get("user_ratings_total") or 0),
            )
        )
    nights = max(1, _nights_between(check_in, check_out))
    guests = max(1, travelers_total)

    out: list[dict[str, Any]] = []
    for _, det, pairs in scored[:5]:
        pid = det.get("place_id") or ""
        photos = det.get("photos") or []
        image_urls: list[str] = []
        for ph in photos[:6]:
            ref = ph.get("photo_reference")
            if ref:
                image_urls.append(photo_url(ref, key, max_width=1000))

        price_level = det.get("price_level")
        plevel_str = {1: "저렴", 2: "보통", 3: "다소 높음", 4: "고가"}.get(
            int(price_level) if price_level is not None else -1,
            "미표시",
        )

        drive_rows = [
            {"name": name, "minutes": m} for name, m in pairs if m is not None
        ]
        unknown = sum(1 for _, m in pairs if m is None)
        sum_m = sum(m for _, m in pairs if m is not None)
        note = (
            f"렌트(승용차) 기준 숙소→각 명소 편도 주행 분 합계 약 {sum_m}분"
            if pairs
            else "명소 좌표가 없어 주행 분은 표시하지 않았습니다(목적지 중심 검색)."
        )
        if unknown:
            note += f" (일부 구간 {unknown}건은 계산 실패)"
        if len(attraction_points) > 25:
            note += " — 명소가 많아 상위 25곳만 반영했습니다."

        maps_url = det.get("url") or f"https://www.google.com/maps/search/?api=1&query_place_id={pid}"

        out.append(
            {
                "hotel_id": f"GP-{pid[:24]}",
                "place_id": pid,
                "name": det.get("name") or "숙소",
                "location": det.get("formatted_address") or location_label,
                "price_per_night_krw": None,
                "rating": float(det["rating"]) if det.get("rating") is not None else None,
                "amenities": [],
                "breakfast_included": None,
                "kitchen": None,
                "bedroom_summary": "",
                "parking_fee_text": "현지 숙소·예약 페이지에서 확인",
                "feature_highlights": [f"가격대(추정): {plevel_str}"],
                "fit_notes": note,
                "booking_url": maps_url,
                "accommodation_type": "hotel",
                "image_urls": image_urls,
                "stay_nights": nights,
                "total_stay_estimate_krw": None,
                "selection_rationale": (
                    f"Google Maps 기준으로 일정 명소까지의 주행 시간 합이 비교적 짧은 숙소 후보입니다. "
                    f"(일행 {guests}명, 체크인 {check_in})"
                ),
                "attraction_drive_times": drive_rows,
                "total_driving_minutes_sum": int(sum_m) if pairs else None,
                "optimization_metric": "sum_of_driving_minutes_hotel_to_attractions",
            }
        )

    return out if out else None


def _nights_between(check_in: str, check_out: str) -> int:
    from datetime import datetime

    try:
        a = datetime.strptime((check_in or "")[:10], "%Y-%m-%d").date()
        b = datetime.strptime((check_out or "")[:10], "%Y-%m-%d").date()
        return max(1, (b - a).days)
    except Exception:
        return 1

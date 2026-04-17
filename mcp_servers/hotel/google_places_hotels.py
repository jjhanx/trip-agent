"""Google Places(Nearby) + Distance Matrix — 일자·명소 구간별 숙소 후보."""

from __future__ import annotations

import logging
import math
import os
import time
from datetime import datetime, timedelta
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
    clat, clng = center
    max_km = 0.0
    for p in points:
        km = _haversine_km(clat, clng, p["lat"], p["lng"])
        max_km = max(max_km, km)
    # 당일 명소가 퍼져 있을수록 반경을 넓혀 숙소 후보를 더 잡음(도로·산악 구간 대비 여유 km)
    r = int(max(12000, (max_km + 28) * 1000))
    return min(85000, r)


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
        "photos,url,website,price_level,international_phone_number,types,"
        "editorial_summary,opening_hours,business_status,wheelchair_accessible_entrance"
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
    if not dest_points:
        return []
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


def _max_minutes(pairs: list[tuple[str, int | None]]) -> int:
    vals = [m for _, m in pairs if m is not None]
    return max(vals) if vals else 0


def _lodging_facility_hints(det: dict[str, Any]) -> dict[str, Any]:
    """Places 세부에 없는 시설은 이름·요약 키워드로 추정(오탐 가능 → 확인 권장)."""
    types = [str(t).lower() for t in (det.get("types") or [])]
    type_blob = " ".join(types)
    name = str(det.get("name") or "").lower()
    ed = det.get("editorial_summary") if isinstance(det.get("editorial_summary"), dict) else {}
    overview = str((ed or {}).get("overview") or "").lower()
    blob = f"{name} {overview} {type_blob}"

    def has_kw(*keys: str) -> bool:
        return any(k in blob for k in keys)

    return {
        "swimming_pool": has_kw("pool", "수영", "piscina", "schwimmbad"),
        "sauna": has_kw("sauna", "사우나"),
        "jacuzzi": has_kw("jacuzzi", "자쿠지", "whirlpool", "hot tub"),
        "gym_fitness": has_kw("gym", "fitness", "체력", "workout"),
        "spa": has_kw("spa", "스파"),
        "bbq": has_kw("bbq", "barbecue", "바베큐", "grill"),
        "breakfast_included_hint": has_kw("breakfast", "조식", "buffet breakfast"),
        "kitchenette_hint": has_kw("kitchen", "kitchenette", "주방", "cucina"),
        "parking_free_hint": has_kw("free parking", "무료 주차", "parcheggio gratuito"),
        "parking_likely_hint": has_kw(
            "parking",
            "주차",
            "parcheggio",
            "parkplatz",
            "car park",
            "parking lot",
            "garage",
        ),
        "notes_ko": "시설·주차는 구글 Places 소개 키워드 추정이며, 확정은 예약 화면·Hotellook 캐시를 참고하세요.",
    }


def rank_hotels_for_attraction_points(
    *,
    location_label: str,
    attraction_points: list[dict[str, Any]],
    api_key: str,
    max_hotels: int = 3,
    top_candidates: int = 14,
    itinerary_scope: str = "single_day",
    max_commute_minutes_one_way: int | None = 60,
    travelers_total: int | None = None,
) -> list[dict[str, Any]] | None:
    """특정 일(또는 구간)의 명소 집합에 대해서만 주행 분을 계산해 상위 숙소를 고른다."""
    key = (api_key or "").strip()
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

    raw: list[dict[str, Any]] = []
    tok: str | None = None
    for _ in range(2):
        batch, tok = nearby_lodging(center[0], center[1], radius, key, page_token=tok)
        raw.extend(batch)
        if not tok:
            break
        time.sleep(2.0)

    if not raw:
        return None

    def sort_key(r: dict[str, Any]) -> tuple[float, float]:
        rating = float(r.get("rating") or 0)
        nrat = float(r.get("user_ratings_total") or 0)
        return (-rating * math.log10(nrat + 10), -nrat)

    raw.sort(key=sort_key)
    candidates = raw[:top_candidates]

    dest_for_matrix = points[:25] if points else []
    scored: list[tuple[float, float, dict[str, Any], list[tuple[str, int | None]]]] = []
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
            mx = float(_max_minutes(pairs))
        else:
            pairs = []
            total = 0.0
            mx = 0.0
        scored.append((total, mx, det, pairs))

    if not scored:
        return None

    commute_relaxed = False
    if dest_for_matrix and max_commute_minutes_one_way and max_commute_minutes_one_way > 0:
        capped = [x for x in scored if float(x[1]) <= float(max_commute_minutes_one_way)]
        if capped:
            scored = capped
        else:
            commute_relaxed = True

    if dest_for_matrix:
        scored.sort(key=lambda x: (x[0], x[1]))
    else:
        scored.sort(
            key=lambda x: (
                -float((x[2] or {}).get("rating") or 0),
                -float((x[2] or {}).get("user_ratings_total") or 0),
            )
        )

    out_hotels: list[dict[str, Any]] = []
    for total_min, max_min, det, pairs in scored[:max_hotels]:
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
        sum_m = sum(m for _, m in pairs if m is not None)
        max_m = _max_minutes(pairs)
        unknown = sum(1 for _, m in pairs if m is None)
        if pairs:
            if itinerary_scope == "full_trip":
                note = (
                    f"여행 일정에 포함된 전체 명소 기준(날짜 구분 없음): "
                    f"편도 주행 분 합 약 {sum_m}분, 최장 편도 약 {max_m}분 (렌트·승용차). "
                    "실제 이동은 날짜·동선별로 달라집니다."
                )
            else:
                note = (
                    f"이 날 방문하는 명소만 기준: 편도 주행 분 합 약 {sum_m}분, "
                    f"최장 편도 약 {max_m}분 (렌트·승용차)"
                )
        else:
            note = "명소 좌표 없음."
        if unknown:
            note += f" (실패 {unknown}건)"
        if len(attraction_points) > 25:
            note += " — 명소가 많아 상위 25곳만 반영."

        maps_url = det.get("url") or f"https://www.google.com/maps/search/?api=1&query_place_id={pid}"
        website = (det.get("website") or "").strip()
        fac = _lodging_facility_hints(det)
        guests = max(1, int(travelers_total or 2))
        party_line = f"일행 {guests}명 기준(요금·객실 수는 Hotellook 캐시·예약 링크와 함께 확인)"
        if fac.get("parking_free_hint"):
            park_txt = "무료 주차 가능성(Places 키워드 추정) — 유료·대수는 예약 시 확인"
        elif fac.get("parking_likely_hint"):
            park_txt = "주차·차고 관련 언급 있음(추정) — 유료·가능 여부는 예약 링크에서 확인"
        else:
            park_txt = "주차: Places에서 명확한 정보 없음 — 예약·지도 리뷰에서 확인"

        out_hotels.append(
            {
                "hotel_id": f"GP-{pid[:24]}",
                "place_id": pid,
                "hotel_lat": float(hlat),
                "hotel_lng": float(hlng),
                "name": det.get("name") or "숙소",
                "location": det.get("formatted_address") or location_label,
                "price_per_night_krw": None,
                "rating": float(det["rating"]) if det.get("rating") is not None else None,
                "amenities": [],
                "breakfast_included": fac.get("breakfast_included_hint"),
                "kitchen": fac.get("kitchenette_hint"),
                "bedroom_summary": "Hotellook 캐시가 붙으면 객실·식사 옵션명이 표시됩니다.",
                "parking_fee_text": park_txt,
                "feature_highlights": [
                    f"가격대(구글): {plevel_str}",
                    party_line,
                ],
                "facility_hints": fac,
                "detail_urls": {
                    "google_maps": maps_url,
                    "official_website": website or None,
                },
                "commute_target_minutes_one_way": max_commute_minutes_one_way,
                "commute_constraint_relaxed": commute_relaxed,
                "fit_notes": note
                + (
                    " · 당일 명소까지 최장 편도 "
                    f"{max_commute_minutes_one_way}분 이내 후보를 우선했으나 "
                    "해당 조건을 만족하는 후보가 없어 완화했습니다."
                    if commute_relaxed
                    else ""
                ),
                "booking_url": website or maps_url,
                "accommodation_type": "hotel",
                "image_urls": image_urls,
                "stay_nights": 1,
                "total_stay_estimate_krw": None,
                "selection_rationale": (
                    "당일 일정에 포함된 명소까지의 주행 시간을 기준으로 고른 후보입니다."
                ),
                "attraction_drive_times": drive_rows,
                "total_driving_minutes_sum": int(sum_m) if pairs else None,
                "max_driving_minutes_one_way": int(max_m) if pairs else None,
                "optimization_metric": "daily_attractions_only_sum_and_max_leg",
                "drive_time_scope": (
                    "all_trip_attractions" if itinerary_scope == "full_trip" else "single_day_attractions"
                ),
            }
        )

    return out_hotels if out_hotels else None


def search_route_optimized_hotels(
    *,
    location_label: str,
    attraction_points: list[dict[str, Any]],
    check_in: str,
    check_out: str,
    travelers_total: int,
    api_key: str | None,
    hotellook_token: str | None = None,
    rooms_for_pricing: int = 1,
) -> list[dict[str, Any]] | None:
    """전체 명소 한 덩어리(레거시 폴백)."""
    key = (api_key or os.environ.get("GOOGLE_PLACES_API_KEY") or "").strip()
    if not key:
        return None
    hotels = rank_hotels_for_attraction_points(
        location_label=location_label,
        attraction_points=attraction_points,
        api_key=key,
        max_hotels=5,
        top_candidates=8,
        itinerary_scope="full_trip",
        max_commute_minutes_one_way=None,
        travelers_total=travelers_total,
    )
    if not hotels:
        return None
    nights = max(1, _nights_between(check_in, check_out))
    guests = max(1, travelers_total)
    for h in hotels:
        h["stay_nights"] = nights
        h["selection_rationale"] = (
            f"Google Maps 기준(전체 명소 합산 레거시). 일행 {guests}명, 체크인 {check_in}"
        )
        _attach_hotellook_price(h, check_in, check_out, hotellook_token, rooms_for_pricing)
    return hotels


def search_hotels_per_daily_segments(
    *,
    location_label: str,
    daily_segments: list[dict[str, Any]],
    check_in: str,
    check_out: str,
    travelers_total: int,
    api_key: str | None,
    hotellook_token: str | None = None,
    rooms_for_pricing: int = 1,
) -> list[dict[str, Any]] | None:
    """일자별로 명소 구간만 두고 숙소 후보를 나눈다."""
    key = (api_key or os.environ.get("GOOGLE_PLACES_API_KEY") or "").strip()
    if not key or not daily_segments:
        return None

    out_segments: list[dict[str, Any]] = []
    guests = max(1, travelers_total)

    for seg in daily_segments:
        d = str(seg.get("date") or "")[:10]
        pts = seg.get("points") or []
        if not isinstance(pts, list) or not pts:
            out_segments.append(
                {
                    "segment_type": "daily_stay_hint",
                    "date": d,
                    "overnight_area_hint": seg.get("overnight_area_hint"),
                    "day_route_summary": (seg.get("route_notes") or "")[:400],
                    "attraction_names_today": [],
                    "hotels": [],
                    "party_rooms_hint": f"일행 {guests}명 기준 객실 {max(1, rooms_for_pricing)}실 추정(가격 곱셈에 반영)",
                    "suggests_hotel_relocation": seg.get("suggests_hotel_relocation"),
                    "approx_drive_previous_day_region_to_today_minutes": seg.get(
                        "approx_drive_previous_day_region_to_today_minutes"
                    ),
                    "hotel_search_note_ko": "이 날짜 명소 좌표가 카탈로그에 없어 숙소 후보를 검색하지 못했습니다.",
                }
            )
            continue
        ohint = seg.get("overnight_area_hint")
        rnotes = (seg.get("route_notes") or "")[:400]
        names = [p.get("name") or "" for p in pts if isinstance(p, dict)]

        hotels = rank_hotels_for_attraction_points(
            location_label=location_label,
            attraction_points=pts,
            api_key=key,
            max_hotels=3,
            top_candidates=14,
            itinerary_scope="single_day",
            max_commute_minutes_one_way=60,
            travelers_total=guests,
        )

        ci, co = _one_night_around_date(d)
        if hotels:
            for h in hotels:
                h["segment_stay_date"] = d
                h["selection_rationale"] = (
                    f"{d} 당일 방문({', '.join(names[:6])}{'…' if len(names) > 6 else ''}) 기준. 일행 {guests}명."
                )
                _attach_hotellook_price(h, ci, co, hotellook_token, rooms_for_pricing)

        out_segments.append(
            {
                "segment_type": "daily_stay_hint",
                "date": d,
                "overnight_area_hint": ohint,
                "day_route_summary": rnotes,
                "attraction_names_today": names,
                "hotels": hotels or [],
                "party_rooms_hint": f"일행 {guests}명 기준 객실 {max(1, rooms_for_pricing)}실 추정(가격 곱셈에 반영)",
                "suggests_hotel_relocation": seg.get("suggests_hotel_relocation"),
                "approx_drive_previous_day_region_to_today_minutes": seg.get(
                    "approx_drive_previous_day_region_to_today_minutes"
                ),
                "hotel_search_note_ko": (
                    None
                    if hotels
                    else "이 날짜 방문 명소 주변에서 조건에 맞는 숙소 후보를 찾지 못했습니다. 반경·조건을 완화했거나 지역 특성상 60분 이내 숙소가 없을 수 있습니다."
                ),
            }
        )

    return out_segments if out_segments else None


def search_hotels_per_stay_groups(
    *,
    location_label: str,
    group_segments: list[dict[str, Any]],
    check_in: str,
    check_out: str,
    travelers_total: int,
    api_key: str | None,
    hotellook_token: str | None = None,
    rooms_for_pricing: int = 1,
) -> list[dict[str, Any]] | None:
    """숙소 이동 없이 묶인 구간별로 거점 숙소 후보를 찾는다."""
    if not group_segments:
        return None
    key = (api_key or os.environ.get("GOOGLE_PLACES_API_KEY") or "").strip()
    guests = max(1, int(travelers_total or 2))
    out_segments: list[dict[str, Any]] = []
    for seg in group_segments:
        pts = seg.get("points") or []
        gi = int(seg.get("group_index") or 0)
        df = str(seg.get("date_from") or check_in)[:10]
        dt = str(seg.get("date_to") or df)[:10]
        label = str(seg.get("label_ko") or "").strip()
        names = [str(p.get("name") or "").strip() for p in pts if isinstance(p, dict) and p.get("name")]
        names = [n for n in names if n][:12]
        ohint = label or f"그룹 {gi + 1} 구역"
        rnotes = f"{location_label} · {ohint} · 그룹 일자 {df}~{dt}"
        try:
            a0 = datetime.strptime(df, "%Y-%m-%d").date()
            b0 = datetime.strptime(dt, "%Y-%m-%d").date()
            ci = a0.isoformat()
            co = (b0 + timedelta(days=1)).isoformat()
        except Exception:
            ci, co = _one_night_around_date(df)
        hotels = None
        if key and pts:
            hotels = rank_hotels_for_attraction_points(
                location_label=location_label,
                attraction_points=pts,
                api_key=key,
                max_hotels=5,
                top_candidates=14,
                itinerary_scope="single_day",
                max_commute_minutes_one_way=60,
                travelers_total=guests,
            )
        if hotels:
            for h in hotels:
                h["segment_stay_date"] = df
                h["stay_group_index"] = gi
                h["stay_group_date_from"] = df
                h["stay_group_date_to"] = dt
                h["selection_rationale"] = (
                    f"{df}~{dt} 구간({', '.join(names[:6])}{'…' if len(names) > 6 else ''}) 기준. 일행 {guests}명."
                )
                _attach_hotellook_price(h, ci, co, hotellook_token, rooms_for_pricing)
        out_segments.append(
            {
                "segment_type": "stay_group_hint",
                "group_index": gi,
                "date_from": df,
                "date_to": dt,
                "dates_in_group": seg.get("dates") or seg.get("dates_in_group") or [],
                "overnight_area_hint": ohint,
                "day_route_summary": rnotes,
                "attraction_names_in_group": names,
                "hotels": hotels or [],
                "party_rooms_hint": f"일행 {guests}명 기준 객실 {max(1, rooms_for_pricing)}실 추정(가격 곱셈에 반영)",
                "suggests_hotel_relocation": False,
                "approx_drive_previous_day_region_to_today_minutes": None,
                "hotel_search_note_ko": (
                    None
                    if hotels
                    else (
                        "이 구간 명소 좌표가 없거나 Google Places 키가 없어 숙소 후보를 채우지 못했습니다."
                        if not key or not pts
                        else "이 구간 방문 명소 주변에서 조건에 맞는 숙소 후보를 찾지 못했습니다. 반경·조건을 완화했거나 지역 특성상 60분 이내 숙소가 없을 수 있습니다."
                    )
                ),
            }
        )
    return out_segments if out_segments else None


def _attach_hotellook_price(
    hotel: dict[str, Any],
    check_in: str,
    check_out: str,
    token: str | None,
    rooms: int,
) -> None:
    if not token:
        hotel.setdefault(
            "availability_note_ko",
            "요금·재고 요약(캐시)을 보려면 서버에 TRAVELPAYOUTS_API_TOKEN을 설정하세요. "
            "토큰이 없으면 구글 정보와 동선만으로 후보를 고릅니다.",
        )
        return
    try:
        from mcp_servers.hotel.hotellook_prices import fetch_hotellook_stay_quote

        lat = float(hotel.get("hotel_lat") or 0)
        lng = float(hotel.get("hotel_lng") or 0)
        if lat == 0 and lng == 0:
            return
        q = fetch_hotellook_stay_quote(
            str(hotel.get("name") or ""),
            lat,
            lng,
            check_in[:10],
            check_out[:10],
            token,
            rooms=rooms,
        )
        nights = max(1, int(hotel.get("stay_nights") or _nights_between(check_in, check_out)))
        tot = q.get("total_krw_estimate")
        if tot:
            hotel["total_stay_estimate_krw"] = tot
            hotel["price_per_night_krw"] = int(round(tot / nights))
        if q.get("price_basis_note"):
            hotel["price_basis_note"] = q["price_basis_note"]
        if q.get("room_meal_label"):
            hotel["bedroom_summary"] = q["room_meal_label"]
        if q.get("breakfast_included") is not None:
            hotel["breakfast_included"] = bool(q["breakfast_included"])
        if q.get("meal_plan_summary_ko"):
            hotel["meal_plan_summary_ko"] = q["meal_plan_summary_ko"]
        if q.get("availability_note_ko"):
            hotel["availability_note_ko"] = q["availability_note_ko"]
        if q.get("booking_deep_link"):
            hotel["booking_url"] = q["booking_deep_link"]
    except Exception as e:
        logger.debug("hotellook attach skipped: %s", e)


def _one_night_around_date(d: str) -> tuple[str, str]:
    try:
        a = datetime.strptime(d[:10], "%Y-%m-%d").date()
        b = a + timedelta(days=1)
        return a.isoformat(), b.isoformat()
    except Exception:
        return d, d


def _nights_between(check_in: str, check_out: str) -> int:
    try:
        a = datetime.strptime((check_in or "")[:10], "%Y-%m-%d").date()
        b = datetime.strptime((check_out or "")[:10], "%Y-%m-%d").date()
        return max(1, (b - a).days)
    except Exception:
        return 1

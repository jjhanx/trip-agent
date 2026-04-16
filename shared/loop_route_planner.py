"""공항(또는 출발 앵커)–최근접 명소–최원거리 명소–공항 루프 경로와, 그 주변 명소를 경로상 순서로 정렬한다.

일정은 하루 2곳(오전·오후)으로 나누는 상위 로직은 `itinerary_route_schedule`에서 처리한다.
"""

from __future__ import annotations

import logging
import math
from typing import Any
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "TripAgent/1.0 (loop route planner)"


async def _get_json(url: str) -> dict[str, Any] | None:
    try:
        async with httpx.AsyncClient(timeout=35.0, headers={"User-Agent": USER_AGENT}) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        logger.warning("loop_route_planner HTTP failed: %s", e)
        return None


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


async def driving_minutes_from_anchor(
    anchor_lat: float,
    anchor_lng: float,
    dest_lat: float,
    dest_lng: float,
    api_key: str,
) -> int | None:
    q = urlencode(
        {
            "origin": f"{anchor_lat},{anchor_lng}",
            "destination": f"{dest_lat},{dest_lng}",
            "mode": "driving",
            "key": api_key,
        }
    )
    url = f"https://maps.googleapis.com/maps/api/directions/json?{q}"
    data = await _get_json(url)
    if not data or data.get("status") not in ("OK",):
        return None
    routes = data.get("routes") or []
    if not routes:
        return None
    legs = routes[0].get("legs") or []
    if not legs:
        return None
    sec = legs[0].get("duration", {}).get("value")
    if sec is None:
        return None
    return max(1, int(round(float(sec) / 60.0)))


def _order_along_segment(
    c: dict[str, Any],
    f: dict[str, Any],
    others: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """최근접–최원거리 직선(대원거리) 위에 사영한 순서로 others 정렬."""
    clat = float(c["attr_lat"])
    clng = float(c["attr_lng"])
    flat = float(f["attr_lat"])
    flng = float(f["attr_lng"])
    vx, vy = flat - clat, flng - clng
    denom = vx * vx + vy * vy
    if denom < 1e-12:
        return list(others)

    scored: list[tuple[float, dict[str, Any]]] = []
    for a in others:
        if not isinstance(a, dict):
            continue
        alat = a.get("attr_lat")
        alng = a.get("attr_lng")
        if not isinstance(alat, (int, float)) or not isinstance(alng, (int, float)):
            continue
        px, py = float(alat) - clat, float(alng) - clng
        t = (px * vx + py * vy) / denom
        t = max(0.0, min(1.0, t))
        scored.append((t, a))
    scored.sort(key=lambda x: x[0])
    return [x[1] for x in scored]


async def pick_closest_farthest_and_order(
    anchor_lat: float,
    anchor_lng: float,
    enriched: list[dict[str, Any]],
    api_key: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """앵커에서 가장 가깝고 먼 명소를 고르고, 나머지는 두 점 사이 ‘경로상’ 순으로 정렬한 전체 방문 리스트."""
    items = [x for x in enriched if isinstance(x, dict) and x.get("id")]
    for a in items:
        alat, alng = a.get("attr_lat"), a.get("attr_lng")
        if not isinstance(alat, (int, float)) or not isinstance(alng, (int, float)):
            continue

    if not items:
        return [], {}

    if len(items) == 1:
        a0 = items[0]
        meta = {
            "closest_attraction_id": str(a0.get("id")),
            "farthest_attraction_id": str(a0.get("id")),
            "anchor_label": "anchor",
            "ordering_note": "명소 1곳만 있어 순서가 단일입니다.",
        }
        return [a0], meta

    times: list[tuple[dict[str, Any], int | None]] = []
    for a in items:
        alat, alng = a.get("attr_lat"), a.get("attr_lng")
        if not isinstance(alat, (int, float)) or not isinstance(alng, (int, float)):
            times.append((a, None))
            continue
        m = await driving_minutes_from_anchor(
            anchor_lat, anchor_lng, float(alat), float(alng), api_key
        )
        times.append((a, m))

    def sort_key(x: tuple[dict[str, Any], int | None]) -> float:
        _, m = x
        if m is None:
            return float("inf")
        return float(m)

    by_time = sorted([x for x in times if x[1] is not None], key=sort_key)
    if not by_time:
        by_h = sorted(
            items,
            key=lambda a: _haversine_km(
                anchor_lat,
                anchor_lng,
                float(a["attr_lat"]),
                float(a["attr_lng"]),
            ),
        )
        c, f = by_h[0], by_h[-1]
    else:
        c = by_time[0][0]
        f = by_time[-1][0]

    cid = str(c.get("id"))
    fid = str(f.get("id"))

    if cid == fid:
        return items, {
            "closest_attraction_id": cid,
            "farthest_attraction_id": fid,
            "ordering_note": "최근접·최원거리가 동일 명소로 계산되었습니다.",
        }

    middle_ids = {str(x.get("id")) for x in items} - {cid, fid}
    others = [x for x in items if str(x.get("id")) in middle_ids]
    ordered_mid = _order_along_segment(c, f, others)
    ordered = [c] + ordered_mid + [f]

    meta = {
        "closest_attraction_id": cid,
        "farthest_attraction_id": fid,
        "ordering_note": (
            "출발 앵커에서 승용차 시간이 가장 짧은 명소와 가장 긴 명소를 고른 뒤, "
            "그 두 점을 잇는 구간 위에 사영한 순서로 나머지 명소를 배치했습니다."
        ),
    }
    return ordered, meta


async def fetch_loop_route_directions(
    anchor_lat: float,
    anchor_lng: float,
    closest: dict[str, Any],
    farthest: dict[str, Any],
    api_key: str,
) -> dict[str, Any]:
    """앵커 → 최근접 → 최원거리 → 앵커 루프의 폴리라인·링크."""
    clat = float(closest["attr_lat"])
    clng = float(closest["attr_lng"])
    flat = float(farthest["attr_lat"])
    flng = float(farthest["attr_lng"])
    wp = f"via:{clat},{clng}|via:{flat},{flng}"
    q = urlencode(
        {
            "origin": f"{anchor_lat},{anchor_lng}",
            "destination": f"{anchor_lat},{anchor_lng}",
            "waypoints": wp,
            "mode": "driving",
            "key": api_key,
        }
    )
    url = f"https://maps.googleapis.com/maps/api/directions/json?{q}"
    data = await _get_json(url)
    out: dict[str, Any] = {
        "overview_polyline": None,
        "bounds": None,
        "google_maps_directions_url": None,
        "static_map_url": None,
        "legs_summary_ko": "",
    }
    if not data or data.get("status") not in ("OK",) or not data.get("routes"):
        return out

    route = data["routes"][0]
    poly = (route.get("overview_polyline") or {}).get("points")
    out["overview_polyline"] = poly
    out["bounds"] = route.get("bounds")

    legs = route.get("legs") or []
    parts: list[str] = []
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        dur = (leg.get("duration") or {}).get("text")
        dst = (leg.get("distance") or {}).get("text")
        if dur and dst:
            parts.append(f"{dst}, 약 {dur}")
    if parts:
        out["legs_summary_ko"] = " → ".join(parts)

    maps_origin = f"{anchor_lat},{anchor_lng}"
    maps_dest = maps_origin
    mq = urlencode(
        {
            "api": "1",
            "origin": maps_origin,
            "destination": maps_dest,
            "waypoints": f"{clat},{clng}|{flat},{flng}",
            "travelmode": "driving",
        }
    )
    out["google_maps_directions_url"] = f"https://www.google.com/maps/dir/?{mq}"

    if poly:
        path_val = f"weight:4|color:0x2563ebff|enc:{poly}"
        static_params = [
            ("size", "640x400"),
            ("scale", "2"),
            ("maptype", "roadmap"),
            ("path", path_val),
            ("markers", f"color:green|label:A|{anchor_lat},{anchor_lng}"),
            ("markers", f"color:blue|label:C|{clat},{clng}"),
            ("markers", f"color:red|label:F|{flat},{flng}"),
            ("key", api_key),
        ]
        out["static_map_url"] = "https://maps.googleapis.com/maps/api/staticmap?" + urlencode(
            static_params
        )

    return out


def add_attraction_markers_to_static_map(
    base_url: str | None,
    attractions: list[dict[str, Any]],
    api_key: str,
) -> str | None:
    """경로 지도에 명소 위치를 작은 마커로 덧붙인 URL(길이 제한 시 원본 반환)."""
    if not base_url or "maps.googleapis.com/maps/api/staticmap" not in base_url:
        return base_url
    pts: list[str] = []
    for a in attractions[:24]:
        if not isinstance(a, dict):
            continue
        lat, lng = a.get("attr_lat"), a.get("attr_lng")
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            pts.append(f"{float(lat)},{float(lng)}")
    if not pts:
        return base_url
    group = "size:tiny|color:0xf97316|" + "|".join(pts)
    merged = base_url + "&" + urlencode({"markers": group})
    if len(merged) > 7500:
        return base_url
    return merged

"""목적지 공통: 출발지에 가까운 게이트웨이 공항 → 목적지 루프(Directions) → 루프 주변 Places.

Grand Circle은 서부 허브(LAX/LAS/PHX/SLC) + 고정 국립공원 루프를 유지하고,
그 외 목적지는 목적지 중심 근처의 공항(Places Nearby) 후보 중 출발지와 대원거리 최단을 고른다."""

from __future__ import annotations

import logging
from typing import Any

from shared.attraction_geo import haversine_km

logger = logging.getLogger(__name__)

# Grand Circle: 서부 직항 허브(출발지와 가장 가까운 곳을 고르면 LAX·LAS 등으로 수렴)
GC_GATEWAY_AIRPORTS: tuple[tuple[str, str], ...] = (
    ("LAX", "Los Angeles International Airport CA USA"),
    ("LAS", "Harry Reid International Airport Las Vegas NV USA"),
    ("PHX", "Phoenix Sky Harbor International Airport AZ USA"),
    ("SLC", "Salt Lake City International Airport UT USA"),
)

GC_LOOP_WAYPOINT_ADDRESSES: tuple[str, ...] = (
    "Grand Canyon South Rim Visitor Center Arizona USA",
    "Springdale Utah USA",
    "Bryce Canyon National Park Utah USA",
    "Page Arizona USA",
    "Monument Valley Navajo Tribal Park Utah USA",
    "Arches National Park Moab Utah USA",
)

# 루프 도로 주변 '차로 약 1시간' 직선 상한(km)
CORRIDOR_MAX_KM = 110.0

NEARBY_SEARCH_RADIUS_METERS = 200_000
MAX_DIRECTIONS_WAYPOINTS = 23


def corridor_max_km() -> float:
    return CORRIDOR_MAX_KM


def grand_circle_corridor_max_km() -> float:
    """하위 호환 이름."""
    return corridor_max_km()


async def geocode_ll(client: Any, address: str, api_key: str) -> str | None:
    from urllib.parse import urlencode

    if not (address or "").strip() or not (api_key or "").strip():
        return None
    url = "https://maps.googleapis.com/maps/api/geocode/json?" + urlencode(
        {"address": address.strip(), "key": api_key}
    )
    try:
        r = await client.get(url, timeout=12)
        if r.status_code != 200:
            return None
        results = r.json().get("results", [])
        if not results:
            return None
        loc = results[0].get("geometry", {}).get("location", {})
        lat, lng = loc.get("lat"), loc.get("lng")
        if lat is None or lng is None:
            return None
        return f"{lat},{lng}"
    except Exception as e:
        logger.debug("geocode_ll failed: %s", e)
        return None


async def pick_gateway_ll_closest_to_origin(
    client: Any,
    api_key: str,
    origin: str,
    candidate_lls: list[str],
) -> str | None:
    """출발지와 대원거리가 가장 짧은 후보 좌표. 출발지가 비어 있으면 후보 첫 좌표."""
    if not candidate_lls:
        return None
    if not (origin or "").strip():
        return candidate_lls[0]
    origin_ll = await geocode_ll(client, origin, api_key)
    if not origin_ll:
        return candidate_lls[0]
    try:
        olat, olng = map(float, origin_ll.split(","))
    except (ValueError, TypeError):
        return candidate_lls[0]

    best_ll: str | None = None
    best_km = 1e18
    for ll in candidate_lls:
        if not ll:
            continue
        try:
            alat, alng = map(float, ll.split(","))
        except (ValueError, TypeError):
            continue
        km = haversine_km(olat, olng, alat, alng)
        if km < best_km:
            best_km = km
            best_ll = ll
    return best_ll or candidate_lls[0]


async def pick_grand_circle_gateway_ll(client: Any, origin: str, api_key: str) -> str | None:
    """GC 전용: LAX/LAS/PHX/SLC 지오코드 후 출발지와 가장 가까운 공항 좌표."""
    if not (api_key or "").strip():
        return None
    cands: list[str] = []
    for _code, gaddr in GC_GATEWAY_AIRPORTS:
        ll = await geocode_ll(client, gaddr, api_key)
        if ll:
            cands.append(ll)
    if not cands:
        return None
    return await pick_gateway_ll_closest_to_origin(client, api_key, origin or "", cands)


async def find_airport_candidates_near_latlng(
    client: Any,
    api_key: str,
    center_ll: str,
    *,
    radius_m: int = NEARBY_SEARCH_RADIUS_METERS,
    max_results: int = 12,
) -> list[str]:
    """목적지 중심 근처 공항 좌표 후보(Places Nearby type=airport)."""
    from urllib.parse import urlencode

    if not center_ll or not (api_key or "").strip():
        return []
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
    params = {
        "location": center_ll,
        "radius": str(radius_m),
        "type": "airport",
        "key": api_key,
    }
    out: list[str] = []
    seen: set[str] = set()
    try:
        r = await client.get(url, params=params, timeout=20)
        if r.status_code != 200:
            return []
        for p in r.json().get("results") or []:
            types = set(p.get("types") or [])
            if "airport" not in types:
                continue
            geom = p.get("geometry") or {}
            loc = geom.get("location") if isinstance(geom, dict) else None
            if not isinstance(loc, dict):
                continue
            lat, lng = loc.get("lat"), loc.get("lng")
            if lat is None or lng is None:
                continue
            s = f"{lat},{lng}"
            key = f"{round(float(lat), 4)},{round(float(lng), 4)}"
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
            if len(out) >= max_results:
                break
    except Exception as e:
        logger.debug("find_airport_candidates_near_latlng: %s", e)
    return out


async def find_airport_candidates_textsearch_fallback(
    client: Any,
    api_key: str,
    center_ll: str,
    place_hint: str,
    *,
    max_results: int = 8,
) -> list[str]:
    """Nearby가 비었을 때 Text Search로 공항 후보 보강."""
    from urllib.parse import urlencode

    if not center_ll or not (api_key or "").strip():
        return []
    q = (place_hint or "").strip() or "tourist destination"
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    params = {
        "query": f"international airport near {q}"[:180],
        "location": center_ll,
        "radius": str(NEARBY_SEARCH_RADIUS_METERS),
        "key": api_key,
    }
    out: list[str] = []
    seen: set[str] = set()
    try:
        r = await client.get(url, params=params, timeout=20)
        if r.status_code != 200:
            return []
        for p in r.json().get("results") or []:
            types = set(p.get("types") or [])
            if "airport" not in types:
                continue
            geom = p.get("geometry") or {}
            loc = geom.get("location") if isinstance(geom, dict) else None
            if not isinstance(loc, dict):
                continue
            lat, lng = loc.get("lat"), loc.get("lng")
            if lat is None or lng is None:
                continue
            s = f"{lat},{lng}"
            key = f"{round(float(lat), 4)},{round(float(lng), 4)}"
            if key in seen:
                continue
            seen.add(key)
            out.append(s)
            if len(out) >= max_results:
                break
    except Exception as e:
        logger.debug("find_airport_candidates_textsearch_fallback: %s", e)
    return out


async def build_round_trip_loop_points(
    client: Any,
    api_key: str,
    gateway_ll: str,
    waypoint_addresses: list[str],
) -> tuple[list[str], list[str]]:
    """
    게이트웨이 → 웨이포인트들 → 게이트웨이 Directions 루프의 step 끝점 샘플.

    waypoint_addresses: 지오코딩 가능한 주소 문자열(최대 MAX_DIRECTIONS_WAYPOINTS개).
    """
    from urllib.parse import urlencode

    dest: list[str] = []
    if gateway_ll:
        dest.append(gateway_ll)

    trimmed = [a.strip() for a in waypoint_addresses if (a or "").strip()][
        :MAX_DIRECTIONS_WAYPOINTS
    ]
    if not trimmed:
        return dest, []

    waypoint_lls: list[str] = []
    for addr in trimmed:
        ll = await geocode_ll(client, addr, api_key)
        if ll:
            waypoint_lls.append(ll)
            if ll not in dest:
                dest.append(ll)

    route_samples: list[str] = []
    try:
        wp = "|".join(trimmed)
        url = (
            "https://maps.googleapis.com/maps/api/directions/json?"
            + urlencode(
                {
                    "origin": gateway_ll,
                    "destination": gateway_ll,
                    "waypoints": wp,
                    "key": api_key,
                }
            )
        )
        r = await client.get(url, timeout=35)
        if r.status_code != 200:
            return dest, waypoint_lls
        data = r.json()
        routes = data.get("routes") or []
        if not routes:
            return dest, waypoint_lls
        for leg in routes[0].get("legs") or []:
            for step in leg.get("steps") or []:
                el = step.get("end_location") or {}
                lat, lng = el.get("lat"), el.get("lng")
                if lat is None or lng is None:
                    continue
                s = f"{lat},{lng}"
                if route_samples and route_samples[-1] == s:
                    continue
                route_samples.append(s)
        if len(route_samples) > 80:
            stride = max(1, len(route_samples) // 60)
            route_samples = [route_samples[i] for i in range(0, len(route_samples), stride)]
    except Exception as e:
        logger.warning("Directions round-trip loop failed: %s", e)

    seen: set[str] = set()
    merged_route: list[str] = []
    for s in route_samples:
        if s not in seen:
            seen.add(s)
            merged_route.append(s)
    if not merged_route:
        merged_route = list(waypoint_lls)
    return dest, merged_route


async def build_grand_circle_loop_points(
    client: Any,
    api_key: str,
    gateway_ll: str,
) -> tuple[list[str], list[str]]:
    """Grand Circle 고정 루프."""
    return await build_round_trip_loop_points(
        client, api_key, gateway_ll, list(GC_LOOP_WAYPOINT_ADDRESSES)
    )

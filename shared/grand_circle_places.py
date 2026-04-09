"""Grand Circle 명소 수집: 출발지→게이트웨이 공항(LAX/LAS/PHX/SLC 중 출발지와 가장 가까운 곳) + 대표 공원 고정 루프 경로 주변."""

from __future__ import annotations

import logging
from typing import Any

from shared.attraction_geo import haversine_km

logger = logging.getLogger(__name__)

# 출발지와의 대원거리가 가장 짧은 게이트웨이를 고르면(아시아 등) LAX·LAS 등 서부 허브에 수렴하기 쉬움
GC_GATEWAY_AIRPORTS: tuple[tuple[str, str], ...] = (
    ("LAX", "Los Angeles International Airport CA USA"),
    ("LAS", "Harry Reid International Airport Las Vegas NV USA"),
    ("PHX", "Phoenix Sky Harbor International Airport AZ USA"),
    ("SLC", "Salt Lake City International Airport UT USA"),
)

# 루프 순서: 그랜드캐년 → 자이언 → 브라이스 → 페이지(앤텔로프) → 모뉴먼트 밸리 → 아치스 → (Directions로 게이트웨이까지 복귀)
GC_LOOP_WAYPOINT_ADDRESSES: tuple[str, ...] = (
    "Grand Canyon South Rim Visitor Center Arizona USA",
    "Springdale Utah USA",
    "Bryce Canyon National Park Utah USA",
    "Page Arizona USA",
    "Monument Valley Navajo Tribal Park Utah USA",
    "Arches National Park Moab Utah USA",
)


def grand_circle_corridor_max_km() -> float:
    """루프 도로 주변 '차로 약 1시간'에 맞춘 직선 거리 상한(오탐 차단)."""
    return 110.0


async def _geocode(client: Any, address: str, api_key: str) -> str | None:
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
        logger.debug("grand_circle geocode failed: %s", e)
        return None


async def pick_grand_circle_gateway_ll(client: Any, origin: str, api_key: str) -> str | None:
    """출발지에서 대원거리가 가장 가까운 서부 게이트웨이 공항 좌표."""
    if not (api_key or "").strip():
        return None
    default_las = await _geocode(client, GC_GATEWAY_AIRPORTS[1][1], api_key)
    if not (origin or "").strip():
        return default_las

    origin_ll = await _geocode(client, origin, api_key)
    if not origin_ll:
        return default_las

    try:
        olat, olng = map(float, origin_ll.split(","))
    except (ValueError, TypeError):
        return default_las

    best_ll: str | None = None
    best_km = 1e18
    for _code, gaddr in GC_GATEWAY_AIRPORTS:
        ll = await _geocode(client, gaddr, api_key)
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
    return best_ll or default_las


async def build_grand_circle_loop_points(
    client: Any,
    api_key: str,
    gateway_ll: str,
) -> tuple[list[str], list[str]]:
    """
    Returns:
      dest_points: 게이트웨이 + 각 웨이포인트 지오코드 (Places 앵커·텍스트 바이어스)
      route_sample_points: 게이트웨이→공원들→게이트웨이 주행 경로의 step 끝점 샘플 (Nearby 밀도)
    """
    from urllib.parse import urlencode

    dest: list[str] = []
    if gateway_ll:
        dest.append(gateway_ll)

    waypoint_lls: list[str] = []
    for addr in GC_LOOP_WAYPOINT_ADDRESSES:
        ll = await _geocode(client, addr, api_key)
        if ll:
            waypoint_lls.append(ll)
            if ll not in dest:
                dest.append(ll)

    route_samples: list[str] = []
    try:
        wp = "|".join(GC_LOOP_WAYPOINT_ADDRESSES)
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
        logger.warning("Grand Circle Directions loop failed: %s", e)

    seen: set[str] = set()
    merged_route: list[str] = []
    for s in route_samples:
        if s not in seen:
            seen.add(s)
            merged_route.append(s)
    if not merged_route:
        merged_route = list(waypoint_lls)
    return dest, merged_route

"""명소 Places 수집용 지리 헬퍼 — 특정 지역 하드코딩이 아니라 앵커 집합까지의 최단 거리로 후보를 거른다."""

from __future__ import annotations

import math


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def min_km_to_anchor_strings(lat: float, lng: float, anchors: list[str]) -> float | None:
    """`"lat,lng"` 문자열 앵커들까지의 하버사인 거리(km) 최솟값."""
    if not anchors:
        return None
    best: float | None = None
    for s in anchors:
        if not s or not isinstance(s, str):
            continue
        parts = s.split(",")
        if len(parts) < 2:
            continue
        try:
            alat = float(parts[0].strip())
            alng = float(parts[1].strip())
        except (TypeError, ValueError):
            continue
        km = haversine_km(lat, lng, alat, alng)
        if best is None or km < best:
            best = km
    return best


def build_places_anchors(
    dest_points: list[str],
    route_points: list[str],
    *,
    origin_ll: str | None,
    include_origin: bool,
) -> list[str]:
    """목적지 지오코드 + (렌트 시) 경로 샘플점 + (지역 구간일 때만) 출발지 지오코드."""
    out: list[str] = []
    for p in dest_points or []:
        if p and p not in out:
            out.append(p)
    for p in route_points or []:
        if p and p not in out:
            out.append(p)
    if include_origin and origin_ll and origin_ll not in out:
        out.append(origin_ll)
    return out


def default_max_km_for_places_filter(patagonia: bool) -> float:
    """광역 자연권(파타고니아 등)은 앵커 간 거리가 길어 상한을 넓힌다. 그 외는 도시권·루프 여행에 맞춘 기본 상한."""
    return 2400.0 if patagonia else 1000.0

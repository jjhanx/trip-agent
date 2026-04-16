"""승용차 이동 시간 행렬 + NN·2-opt로 ‘모든 명소를 한 번씩 도는’ 순서를 근사한다.

직선 사영이 아니라 Distance Matrix(도로) 기반으로 순서를 정한 뒤, Directions로 전체 투어 폴리라인을 만든다.
"""

from __future__ import annotations

import logging
import math
from typing import Any
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "TripAgent/1.0 (tour route optimizer)"


async def _get_json(url: str) -> dict[str, Any] | None:
    try:
        async with httpx.AsyncClient(timeout=45.0, headers={"User-Agent": USER_AGENT}) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        logger.warning("tour_route_optimizer HTTP failed: %s", e)
        return None


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _haversine_minutes_fallback_km(km: float) -> float:
    """도로 실패 시 대략 분(고속·산악 혼합 가정)."""
    return max(1.0, (km / 45.0) * 60.0)


async def build_driving_minutes_matrix(
    coords: list[tuple[float, float]],
    api_key: str,
) -> list[list[float | None]]:
    """coords[i] = (lat,lng). 대칭이 아닐 수 있음 — i→j만 사용."""
    n = len(coords)
    if n == 0:
        return []
    key = (api_key or "").strip()
    if not key:
        return [[None] * n for _ in range(n)]

    mat: list[list[float | None]] = [[None] * n for _ in range(n)]
    for i in range(n):
        mat[i][i] = 0.0

    chunk = 25

    async def one_block(
        o_start: int, o_end: int, d_start: int, d_end: int
    ) -> None:
        origins = "|".join(f"{coords[i][0]},{coords[i][1]}" for i in range(o_start, o_end))
        dests = "|".join(f"{coords[j][0]},{coords[j][1]}" for j in range(d_start, d_end))
        q = urlencode(
            {
                "origins": origins,
                "destinations": dests,
                "mode": "driving",
                "key": key,
                "language": "ko",
            }
        )
        url = f"https://maps.googleapis.com/maps/api/distancematrix/json?{q}"
        data = await _get_json(url)
        if not data or data.get("status") not in ("OK",):
            return
        rows = data.get("rows") or []
        for ri, row in enumerate(rows):
            elems = row.get("elements") or []
            for ej, el in enumerate(elems):
                ii = o_start + ri
                jj = d_start + ej
                if ii >= n or jj >= n:
                    continue
                if el.get("status") != "OK":
                    continue
                sec = (el.get("duration") or {}).get("value")
                if sec is None:
                    continue
                mat[ii][jj] = max(1.0, float(sec) / 60.0)

    for o_start in range(0, n, chunk):
        o_end = min(n, o_start + chunk)
        for d_start in range(0, n, chunk):
            d_end = min(n, d_start + chunk)
            await one_block(o_start, o_end, d_start, d_end)

    # 빈 칸은 직선 거리로 보정
    for i in range(n):
        for j in range(n):
            if i != j and mat[i][j] is None:
                km = _haversine_km(coords[i][0], coords[i][1], coords[j][0], coords[j][1])
                mat[i][j] = _haversine_minutes_fallback_km(km)
    return mat


def _tour_cost(mat: list[list[float | None]], order: list[int]) -> float:
    """order: 방문할 노드 인덱스 순서(앵커 0 제외, 1..n-1의 순열)."""
    if not order:
        return float("inf")
    t = 0.0
    prev = 0
    for idx in order:
        m = mat[prev][idx]
        if m is None:
            return float("inf")
        t += m
        prev = idx
    m0 = mat[prev][0]
    if m0 is None:
        return float("inf")
    t += m0
    return t


def _nn_tour(mat: list[list[float | None]]) -> list[int]:
    """노드 0에서 출발해 미방문 중 최단(분) 다음 노드."""
    n = len(mat)
    if n <= 2:
        return list(range(1, n))
    unvisited = set(range(1, n))
    order: list[int] = []
    current = 0
    while unvisited:
        best_j = -1
        best_t = float("inf")
        for j in unvisited:
            m = mat[current][j]
            if m is None:
                continue
            if float(m) < best_t:
                best_t = float(m)
                best_j = j
        if best_j < 0:
            best_j = min(unvisited)
        order.append(best_j)
        unvisited.remove(best_j)
        current = best_j
    return order


def _two_opt_improve(mat: list[list[float | None]], order: list[int]) -> list[int]:
    """비대칭 행렬에서도 2-opt 스왑으로 개선 시도."""
    if len(order) < 4:
        return order
    best = order[:]
    best_c = _tour_cost(mat, best)
    improved = True
    while improved:
        improved = False
        for i in range(len(best) - 1):
            for j in range(i + 2, len(best)):
                cand = best[: i + 1] + list(reversed(best[i + 1 : j + 1])) + best[j + 1 :]
                c = _tour_cost(mat, cand)
                if c < best_c - 1e-6:
                    best = cand
                    best_c = c
                    improved = True
                    break
            if improved:
                break
    return best


async def optimize_visit_order_driving(
    anchor_lat: float,
    anchor_lng: float,
    attractions: list[dict[str, Any]],
    api_key: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """앵커(인덱스 0)에서 출발·복귀하는 전체 명소 투어 순서(근사 최단)."""
    items = [a for a in attractions if isinstance(a, dict) and a.get("id")]
    for a in items:
        if not (
            isinstance(a.get("attr_lat"), (int, float)) and isinstance(a.get("attr_lng"), (int, float))
        ):
            return [], {"error": "좌표 없는 명소가 있어 투어 순서를 만들 수 없습니다."}

    if not items:
        return [], {}
    if len(items) == 1:
        return items, {
            "method": "single_attraction",
            "note_ko": "명소가 한 곳뿐입니다.",
        }

    coords: list[tuple[float, float]] = [(float(anchor_lat), float(anchor_lng))]
    for a in items:
        coords.append((float(a["attr_lat"]), float(a["attr_lng"])))

    mat = await build_driving_minutes_matrix(coords, api_key)
    if len(mat) != len(coords):
        return items, {"error": "행렬 생성 실패"}

    order_idx = _nn_tour(mat)
    order_idx = _two_opt_improve(mat, order_idx)

    ordered_attr: list[dict[str, Any]] = []
    for k in order_idx:
        # k는 1..n-1
        ordered_attr.append(items[k - 1])

    meta: dict[str, Any] = {
        "method": "distance_matrix_nn_two_opt",
        "node_count": len(coords),
        "approx_round_trip_minutes": round(_tour_cost(mat, order_idx), 1),
        "ordered_attraction_ids": [str(x.get("id")) for x in ordered_attr if x.get("id")],
        "route_kind_ko": (
            "도착 앵커(인덱스 0)에서 출발해 모든 명소를 한 번씩 도는 순서를 "
            "Google Distance Matrix의 승용차 시간으로 채운 뒤, "
            "탐욕(Nearest Neighbor) + 2-opt로 전체 동선 시간을 줄였습니다. "
            "직선 사영이 아닙니다."
        ),
    }
    return ordered_attr, meta


async def fetch_full_tour_directions(
    anchor_lat: float,
    anchor_lng: float,
    ordered_attractions: list[dict[str, Any]],
    api_key: str,
) -> dict[str, Any]:
    """전체 투어를 한 번에 그리기(웨이포인트 최대 25개)."""
    out: dict[str, Any] = {
        "overview_polyline": None,
        "google_maps_directions_url": None,
        "static_map_url": None,
        "legs_summary_ko": "",
        "waypoint_truncated": False,
    }
    key = (api_key or "").strip()
    if not key:
        return out

    wps: list[str] = []
    for a in ordered_attractions:
        lat, lng = a.get("attr_lat"), a.get("attr_lng")
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            wps.append(f"{float(lat)},{float(lng)}")
    if not wps:
        return out

    max_wp = 25
    if len(wps) > max_wp:
        wps = wps[:max_wp]
        out["waypoint_truncated"] = True

    wp_param = "|".join(f"via:{w}" for w in wps)
    q = urlencode(
        {
            "origin": f"{anchor_lat},{anchor_lng}",
            "destination": f"{anchor_lat},{anchor_lng}",
            "waypoints": wp_param,
            "mode": "driving",
            "key": key,
        }
    )
    url = f"https://maps.googleapis.com/maps/api/directions/json?{q}"
    data = await _get_json(url)
    if not data or data.get("status") not in ("OK",) or not data.get("routes"):
        return out

    route = data["routes"][0]
    poly = (route.get("overview_polyline") or {}).get("points")
    out["overview_polyline"] = poly
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

    mq = urlencode(
        {
            "api": "1",
            "origin": f"{anchor_lat},{anchor_lng}",
            "destination": f"{anchor_lat},{anchor_lng}",
            "waypoints": "|".join(wps),
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
            ("key", key),
        ]
        out["static_map_url"] = "https://maps.googleapis.com/maps/api/staticmap?" + urlencode(
            static_params
        )
    return out

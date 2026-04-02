"""Google Directions + Places Nearby로 parking 문구를 확정한다.

거점은 **명소 좌표 기준 지도상 가장 가까운 locality(마을·시)** — Places `rankby=distance`.
(나)의 **분**은 해당 거점 좌표 → 명소 좌표 **Directions(driving)** 값.
광역 관광지명(예: Dolomites) 지오코딩 결과는 거점으로 쓰지 않는다(거리·분 부자연 방지).
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = (
    "TripAgent/1.0 (https://github.com/jjhanx/trip-agent; directions parking)"
)


def _destination_is_vague_region(dest: str) -> bool:
    """도시명이 아니라 광역·산악권만 적힌 경우 — 지오코딩해도 거점으로 쓰지 않음."""
    d = (dest or "").strip().lower()
    if not d:
        return True
    vague = (
        "dolomiti",
        "dolomiten",
        "dolomites",
        "dolomite",
        "tre cime",
        "drei zinnen",
        "alta badia",
        "sella ronda",
        "south tyrol",
        "alto adige",
        "südtirol",
        "sudtirol",
        "돌로미티",
        "도로미티",
        "트레 치메",
    )
    return any(k in d for k in vague)


async def _http_get_json(url: str) -> dict[str, Any] | None:
    try:
        async with httpx.AsyncClient(timeout=22, headers={"User-Agent": USER_AGENT}) as client:
            r = await client.get(url)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        logger.debug("directions_parking request failed: %s", e)
        return None


async def geocode_address(address: str, api_key: str) -> tuple[float, float, str] | None:
    if not (address or "").strip() or not (api_key or "").strip():
        return None
    url = "https://maps.googleapis.com/maps/api/geocode/json?" + urlencode(
        {"address": address.strip(), "key": api_key}
    )
    data = await _http_get_json(url)
    if not data or data.get("status") not in ("OK",):
        return None
    results = data.get("results") or []
    if not results:
        return None
    loc = results[0].get("geometry", {}).get("location", {})
    lat, lng = loc.get("lat"), loc.get("lng")
    if lat is None or lng is None:
        return None
    addr = (results[0].get("formatted_address") or address).strip()
    short_name = addr.split(",")[0].strip() if addr else address.strip()
    return float(lat), float(lng), short_name


async def nearest_locality_rankby_distance(
    lat: float, lng: float, api_key: str
) -> dict[str, Any] | None:
    """명소 좌표에서 지도상 거리 순 첫 locality — Google 권장: rankby=distance (반경 없음)."""
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json?" + urlencode(
        {
            "location": f"{lat},{lng}",
            "rankby": "distance",
            "type": "locality",
            "key": api_key,
        }
    )
    data = await _http_get_json(url)
    if not data or data.get("status") not in ("OK", "ZERO_RESULTS"):
        return None
    results = data.get("results") or []
    if not results:
        return None
    r0 = results[0]
    loc = r0.get("geometry", {}).get("location", {})
    la, lo = loc.get("lat"), loc.get("lng")
    if la is None or lo is None:
        return None
    nm = (r0.get("name") or "").strip()
    if not nm:
        return None
    return {"name": nm, "lat": float(la), "lng": float(lo)}


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


async def nearest_locality_by_radius_haversine(
    lat: float, lng: float, api_key: str, *, radius_m: int = 50000
) -> dict[str, Any] | None:
    """rankby 실패 시 반경 검색 후 직선거리 최소 locality."""
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json?" + urlencode(
        {
            "location": f"{lat},{lng}",
            "radius": radius_m,
            "type": "locality",
            "key": api_key,
        }
    )
    data = await _http_get_json(url)
    if not data or data.get("status") not in ("OK", "ZERO_RESULTS"):
        return None
    results = data.get("results") or []
    best: dict[str, Any] | None = None
    best_d = 1e18
    for r in results:
        loc = r.get("geometry", {}).get("location", {})
        la, lo = loc.get("lat"), loc.get("lng")
        if la is None or lo is None:
            continue
        nm = (r.get("name") or "").strip()
        if not nm:
            continue
        d = _haversine_m(lat, lng, float(la), float(lo))
        if d < best_d:
            best_d = d
            best = {"name": nm, "lat": float(la), "lng": float(lo)}
    return best


async def resolve_nearest_village_hub(
    api_key: str,
    destination: str,
    attr_lat: float,
    attr_lng: float,
) -> tuple[str, float, float] | None:
    """지도상 가장 가까운 마을·시 좌표. 광역 목적지 지오코딩은 보조로만(모호하면 생략)."""
    hub = await nearest_locality_rankby_distance(attr_lat, attr_lng, api_key)
    if not hub:
        hub = await nearest_locality_by_radius_haversine(attr_lat, attr_lng, api_key)
    if hub:
        return hub["name"], hub["lat"], hub["lng"]
    if not _destination_is_vague_region(destination):
        geo = await geocode_address(destination, api_key)
        if geo:
            la, lo, nm = geo
            return nm, la, lo
    return None


async def driving_minutes_between(
    api_key: str,
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
) -> int | None:
    url = "https://maps.googleapis.com/maps/api/directions/json?" + urlencode(
        {
            "origin": f"{origin_lat},{origin_lng}",
            "destination": f"{dest_lat},{dest_lng}",
            "mode": "driving",
            "key": api_key,
        }
    )
    data = await _http_get_json(url)
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


def _extract_toll_snippet(text: str) -> str:
    if not text or "€" not in text:
        return ""
    for part in text.replace("。", ".").split("."):
        if "€" in part:
            return part.strip()
    return ""


def _build_parking_line_nearest_village(
    village_name: str,
    minutes: int,
    toll_extra: str,
) -> str:
    toll = f" {toll_extra}" if toll_extra else ""
    return (
        f"(가) 거점 {village_name} — 명소 좌표 기준 **지도상 가장 가까운** 읍·면·시(Places locality)입니다. "
        f"(나) 그 마을·시 쪽 도로 접근 지점에서 이 명소까지 승용차 약 {minutes}분 "
        f"(Google Maps Directions 도로 기준, 실시간·통제에 따라 다름).{toll}"
    ).strip()


async def enrich_attractions_parking_directions(
    attractions: list[dict[str, Any]],
    destination: str,
    api_key: str,
) -> list[dict[str, Any]]:
    """명소 좌표에서 가장 가까운 마을까지의 주행 분(Directions)으로 parking을 덮어쓴다."""
    if not attractions or not (api_key or "").strip():
        return attractions

    from shared.google_place_details import fetch_place_details_raw

    sem = asyncio.Semaphore(4)

    async def one(idx: int) -> None:
        a = attractions[idx]
        if not isinstance(a, dict):
            return
        async with sem:
            alat = a.get("attr_lat")
            alng = a.get("attr_lng")
            if alat is None or alng is None:
                pid = (a.get("place_id") or "").strip()
                if pid:
                    raw = await fetch_place_details_raw(pid, api_key)
                    if raw:
                        loc = (raw.get("geometry") or {}).get("location") or {}
                        if isinstance(loc.get("lat"), (int, float)) and isinstance(
                            loc.get("lng"), (int, float)
                        ):
                            alat = float(loc["lat"])
                            alng = float(loc["lng"])
                            a["attr_lat"] = alat
                            a["attr_lng"] = alng
            if alat is None or alng is None:
                g = await geocode_address(
                    f"{(a.get('name') or '').strip()} {destination}".strip(),
                    api_key,
                )
                if g:
                    alat, alng, _ = g
                    a["attr_lat"] = alat
                    a["attr_lng"] = alng
            if alat is None or alng is None:
                logger.debug("directions_parking: no coords for %s", a.get("name"))
                return

            hub = await resolve_nearest_village_hub(
                api_key, destination, float(alat), float(alng)
            )
            if not hub:
                logger.warning("directions_parking: nearest village 없음 — %s", a.get("name"))
                return

            vname, vla, vlo = hub
            mins = await driving_minutes_between(
                api_key, vla, vlo, float(alat), float(alng)
            )
            if mins is None:
                logger.warning("directions_parking: Directions 실패 — %s", a.get("name"))
                return

            old_pk = str((a.get("practical_details") or {}).get("parking") or "")
            toll = _extract_toll_snippet(old_pk)
            line = _build_parking_line_nearest_village(vname, mins, toll)
            pr = dict(a.get("practical_details") or {})
            pr["parking"] = line
            a["practical_details"] = pr

    await asyncio.gather(*(one(i) for i in range(len(attractions))))
    return attractions

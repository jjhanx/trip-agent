"""Google Directions + Places Nearby + Reverse Geocoding으로 parking 문구를 확정한다.

거점 좌표는 명소와 가까운 **도시·마을(locality)** — 고개(Passo)·콜(Colle) 등은 건너뜀.
표시명은 **역지오코딩 locality**(영어 우선, 없으면 한국어)로 실제 행정·도시명에 가깝게.
분은 거점 좌표 → 명소 좌표 Directions(driving)로 채움.
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


def _looks_like_pass_or_non_town_hub(name: str) -> bool:
    """고개·패스·콜만 있는 이름은 '도시·마을' 거점으로 부적절 — 다음 후보 사용."""
    n = (name or "").strip().lower()
    if not n:
        return True
    # 이탈리아어 고개·안부
    if n.startswith("passo ") or n.startswith("passo,"):
        return True
    if " passo " in n or n.endswith(" passo"):
        return True
    if n.startswith("colle ") or " colle " in n:
        return True
    if n.startswith("forcella") or " forcella " in n:
        return True
    if n.startswith("bocca ") and len(n) < 35:
        return True
    return False


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


def _locality_from_geocode_result(results: list[dict[str, Any]]) -> str | None:
    for res in results:
        for comp in res.get("address_components", []) or []:
            types = comp.get("types") or []
            if "locality" in types:
                nm = (comp.get("long_name") or comp.get("short_name") or "").strip()
                if nm:
                    return nm
    for res in results:
        for comp in res.get("address_components", []) or []:
            types = comp.get("types") or []
            if "administrative_area_level_3" in types:
                nm = (comp.get("long_name") or "").strip()
                if nm:
                    return nm
    return None


async def reverse_geocode_city_display_name(
    lat: float, lng: float, api_key: str
) -> str | None:
    """좌표 → 행정상 도시·마을명. 유럽 지명은 영어 우선, 없으면 한국어."""
    for lang in ("en", "ko"):
        url = "https://maps.googleapis.com/maps/api/geocode/json?" + urlencode(
            {
                "latlng": f"{lat},{lng}",
                "key": api_key,
                "language": lang,
            }
        )
        data = await _http_get_json(url)
        if not data or data.get("status") not in ("OK",):
            continue
        results = data.get("results") or []
        if not results:
            continue
        nm = _locality_from_geocode_result(results)
        if nm:
            return nm
    return None


async def nearest_localities_rankby_distance_list(
    lat: float, lng: float, api_key: str, *, limit: int = 12
) -> list[dict[str, Any]]:
    """거리순 locality 목록(고개 제외 시 다음 후보로 사용)."""
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
        return []
    out: list[dict[str, Any]] = []
    for r in (data.get("results") or [])[:limit]:
        loc = r.get("geometry", {}).get("location", {})
        la, lo = loc.get("lat"), loc.get("lng")
        if la is None or lo is None:
            continue
        nm = (r.get("name") or "").strip()
        if not nm:
            continue
        out.append({"name": nm, "lat": float(la), "lng": float(lo)})
    return out


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


async def nearest_locality_by_radius_haversine_list(
    lat: float, lng: float, api_key: str, *, radius_m: int = 50000
) -> list[dict[str, Any]]:
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
        return []
    rows: list[tuple[float, dict[str, Any]]] = []
    for r in data.get("results") or []:
        loc = r.get("geometry", {}).get("location", {})
        la, lo = loc.get("lat"), loc.get("lng")
        if la is None or lo is None:
            continue
        nm = (r.get("name") or "").strip()
        if not nm:
            continue
        d = _haversine_m(lat, lng, float(la), float(lo))
        rows.append((d, {"name": nm, "lat": float(la), "lng": float(lo)}))
    rows.sort(key=lambda x: x[0])
    return [x[1] for x in rows]


def _pick_hub_skipping_passes(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    for c in candidates:
        if not _looks_like_pass_or_non_town_hub(c.get("name") or ""):
            return c
    return candidates[0] if candidates else None


async def resolve_nearest_village_hub(
    api_key: str,
    destination: str,
    attr_lat: float,
    attr_lng: float,
) -> tuple[str, float, float] | None:
    """도시·마을 좌표. 고개명은 건너뛰고 다음 locality 사용."""
    cands = await nearest_localities_rankby_distance_list(attr_lat, attr_lng, api_key)
    if not cands:
        cands = await nearest_locality_by_radius_haversine_list(attr_lat, attr_lng, api_key)
    hub = _pick_hub_skipping_passes(cands)
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


def _build_parking_line_real_city(display_name: str, minutes: int, toll_extra: str) -> str:
    """거점 지명 + 승용차 분 한 줄."""
    toll = f" {toll_extra}" if toll_extra else ""
    return (
        f"{display_name}에서 승용차 약 {minutes}분 (Google Maps 도로 검색 기준).{toll}"
    ).strip()


async def enrich_attractions_parking_directions(
    attractions: list[dict[str, Any]],
    destination: str,
    api_key: str,
) -> list[dict[str, Any]]:
    """거점 좌표·Directions로 분 확정. 표시명은 역지오코딩 locality."""
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

            _places_name, vla, vlo = hub
            mins = await driving_minutes_between(
                api_key, vla, vlo, float(alat), float(alng)
            )
            if mins is None:
                logger.warning("directions_parking: Directions 실패 — %s", a.get("name"))
                return

            display = await reverse_geocode_city_display_name(vla, vlo, api_key)
            if not display:
                display = _places_name

            a["nearest_hub_display_name"] = display
            a["drive_minutes_from_nearest_hub"] = int(mins)

            old_pk = str((a.get("practical_details") or {}).get("parking") or "")
            toll = _extract_toll_snippet(old_pk)
            line = _build_parking_line_real_city(display, mins, toll)
            pr = dict(a.get("practical_details") or {})
            pr["parking"] = line
            a["practical_details"] = pr

    await asyncio.gather(*(one(i) for i in range(len(attractions))))
    return attractions

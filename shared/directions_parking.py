"""Google Directions + Geocoding + Places Nearby로 거점·주행 분을 산출해 parking 문구를 확정한다.

LLM 추정과 무관하게 (나)의 **분**은 Directions API 값을 사용한다.
동일 Maps API 키로 Geocoding·Directions·Places가 동작한다(콘솔에서 API 사용 설정 필요).
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = (
    "TripAgent/1.0 (https://github.com/jjhanx/trip-agent; directions parking)"
)


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


async def nearby_locality_candidates(
    lat: float, lng: float, api_key: str, *, radius_m: int = 55000
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
    out: list[dict[str, Any]] = []
    for r in (data.get("results") or [])[:10]:
        loc = r.get("geometry", {}).get("location", {})
        la, lo = loc.get("lat"), loc.get("lng")
        if la is None or lo is None:
            continue
        nm = (r.get("name") or "").strip()
        if not nm:
            continue
        out.append({"name": nm, "lat": float(la), "lng": float(lo)})
    return out


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


def _dedupe_hubs(cands: list[tuple[str, float, float]]) -> list[tuple[str, float, float]]:
    seen: set[str] = set()
    out: list[tuple[str, float, float]] = []
    for nm, la, lo in cands:
        k = nm.strip().lower()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append((nm.strip(), la, lo))
    return out


async def pick_nearest_hub_drive_minutes(
    api_key: str,
    destination: str,
    attr_lat: float,
    attr_lng: float,
) -> tuple[str, int] | None:
    """목적지 지오코드 + 인근 locality 후보 각각에 대해 명소까지 주행 분을 구해 최소인 거점을 고른다."""
    candidates: list[tuple[str, float, float]] = []
    geo = await geocode_address(destination, api_key)
    if geo:
        la, lo, nm = geo
        candidates.append((nm, la, lo))
    for n in await nearby_locality_candidates(attr_lat, attr_lng, api_key):
        candidates.append((n["name"], n["lat"], n["lng"]))
    candidates = _dedupe_hubs(candidates)
    if not candidates:
        return None

    sem = asyncio.Semaphore(5)
    results: list[tuple[str, int]] = []

    async def measure(nm: str, ola: float, olo: float) -> None:
        async with sem:
            m = await driving_minutes_between(api_key, ola, olo, attr_lat, attr_lng)
        if m is not None:
            results.append((nm, m))

    await asyncio.gather(*(measure(nm, la, lo) for nm, la, lo in candidates))
    if not results:
        return None
    best = min(results, key=lambda x: x[1])
    return best[0], best[1]


def _extract_toll_snippet(text: str) -> str:
    if not text or "€" not in text:
        return ""
    for part in text.replace("。", ".").split("."):
        if "€" in part:
            return part.strip()
    return ""


def _extract_population_fragment(text: str) -> str:
    if not text:
        return ""
    m = re.search(
        r"(?:약\s*)?[\d.,]+\s*명(?:\s*이상)?|인구[^.]{0,45}",
        text,
    )
    if m:
        return m.group(0).strip()
    return ""


def _build_parking_line(
    hub_name: str,
    minutes: int,
    *,
    population_hint: str,
    toll_extra: str,
) -> str:
    pop_part = population_hint if population_hint else "인구 등은 지자체·통계 공표 자료를 참고하세요"
    toll = f" {toll_extra}" if toll_extra else ""
    return (
        f"(가) 거점 {hub_name} ({pop_part}). "
        f"(나) 위 거점 도심에서 이 명소까지 승용차 약 {minutes}분 "
        f"(Google Maps Directions 도로 기준, 실시간·통제에 따라 다름).{toll}"
    ).strip()


async def enrich_attractions_parking_directions(
    attractions: list[dict[str, Any]],
    destination: str,
    api_key: str,
) -> list[dict[str, Any]]:
    """각 명소에 attr_lat/lng가 있으면 Directions로 거점·분을 확정해 parking을 덮어쓴다."""
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
                logger.debug(
                    "directions_parking: no coords for %s", a.get("name")
                )
                return

            picked = await pick_nearest_hub_drive_minutes(
                api_key, destination, float(alat), float(alng)
            )
            if not picked:
                logger.warning(
                    "directions_parking: hub/directions 실패 — %s", a.get("name")
                )
                return

            hub_name, mins = picked
            old_pk = str((a.get("practical_details") or {}).get("parking") or "")
            pop_hint = _extract_population_fragment(old_pk)
            toll = _extract_toll_snippet(old_pk)
            line = _build_parking_line(
                hub_name,
                mins,
                population_hint=pop_hint,
                toll_extra=toll,
            )
            pr = dict(a.get("practical_details") or {})
            pr["parking"] = line
            a["practical_details"] = pr

    await asyncio.gather(*(one(i) for i in range(len(attractions))))
    return attractions

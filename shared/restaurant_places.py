"""명소 좌표 주변 Google Places로 실제 맛집 후보(이름·평점·소개·URL·지도)를 채운다."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx
from urllib.parse import urlencode

from shared.directions_parking import geocode_address
from shared.google_place_details import fetch_place_details_raw

logger = logging.getLogger(__name__)

USER_AGENT = (
    "TripAgent/1.0 (https://github.com/jjhanx/trip-agent; restaurant nearby)"
)

_TYPE_LABELS = {
    "restaurant": "레스토랑",
    "food": "음식점",
    "cafe": "카페",
    "bar": "바",
    "bakery": "베이커리",
    "meal_takeaway": "포장·테이크아웃",
    "meal_delivery": "배달",
}


def _score_row(row: dict[str, Any]) -> float:
    r = float(row.get("rating") or 0.0)
    rev = int(row.get("user_ratings_total") or 0)
    return r * (1.0 + (max(rev, 0) ** 0.5) / 40.0)


def _is_food_establishment(types: list[str] | None) -> bool:
    t = set(types or [])
    if t & {"gas_station", "convenience_store", "supermarket", "lodging", "storage"}:
        return False
    return bool(t & {"restaurant", "food", "cafe", "bar", "bakery", "meal_takeaway"})


def _maps_url_from_details(details: dict[str, Any], place_id: str) -> str:
    u = (details.get("url") or "").strip()
    if u.startswith("http"):
        return u
    return f"https://www.google.com/maps/search/?api=1&query_place_id={place_id}"


def _build_description(details: dict[str, Any], vicinity: str) -> str:
    parts: list[str] = []
    es = details.get("editorial_summary")
    if isinstance(es, dict):
        ov = (es.get("overview") or "").strip()
        if ov:
            parts.append(ov)
    types = list(details.get("types") or [])
    labels = []
    for x in types[:6]:
        if x in ("point_of_interest", "establishment"):
            continue
        labels.append(_TYPE_LABELS.get(x, x.replace("_", " ")))
    if labels:
        parts.append("유형: " + ", ".join(labels[:5]))
    revs = details.get("reviews") or []
    if isinstance(revs, list) and revs:
        t0 = revs[0].get("text") if isinstance(revs[0], dict) else None
        if isinstance(t0, str):
            t0 = t0.strip()
            if len(t0) > 25:
                parts.append("리뷰: " + t0[:220] + ("…" if len(t0) > 220 else ""))
    addr = (details.get("formatted_address") or vicinity or "").strip()
    if addr:
        parts.append("주소: " + addr[:200])
    price = details.get("price_level")
    if price is not None and isinstance(price, (int, float)):
        pl = int(price)
        if 0 <= pl <= 4:
            price_hint = ["", "저렴", "보통", "다소 비쌈", "고급", "매우 고급"]
            parts.append(f"가격대(추정): {price_hint[pl]}")
    return " ".join(parts) if parts else "Google Places에서 조회한 식당입니다."


async def _nearby_restaurants(
    lat: float, lng: float, api_key: str, *, radius_m: int = 4000
) -> list[dict[str, Any]]:
    params = {
        "location": f"{lat},{lng}",
        "radius": str(radius_m),
        "type": "restaurant",
        "key": api_key,
        "language": "ko",
    }
    url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json?" + urlencode(params)
    try:
        async with httpx.AsyncClient(timeout=22, headers={"User-Agent": USER_AGENT}) as client:
            r = await client.get(url)
            if r.status_code != 200:
                return []
            data = r.json()
            if data.get("status") not in ("OK", "ZERO_RESULTS"):
                return []
            return list(data.get("results") or [])
    except Exception as e:
        logger.debug("nearby restaurants failed: %s", e)
        return []


async def _textsearch_restaurants(
    lat: float, lng: float, api_key: str, *, radius_m: int = 6000
) -> list[dict[str, Any]]:
    params = {
        "query": "restaurant",
        "location": f"{lat},{lng}",
        "radius": str(radius_m),
        "key": api_key,
        "language": "ko",
    }
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json?" + urlencode(params)
    try:
        async with httpx.AsyncClient(timeout=22, headers={"User-Agent": USER_AGENT}) as client:
            r = await client.get(url)
            if r.status_code != 200:
                return []
            data = r.json()
            if data.get("status") not in ("OK", "ZERO_RESULTS"):
                return []
            return list(data.get("results") or [])
    except Exception as e:
        logger.debug("textsearch restaurants failed: %s", e)
        return []


async def _resolve_attr_lat_lng(
    attr: dict[str, Any], destination: str, api_key: str
) -> tuple[float, float] | None:
    alat, alng = attr.get("attr_lat"), attr.get("attr_lng")
    if isinstance(alat, (int, float)) and isinstance(alng, (int, float)):
        return float(alat), float(alng)
    nm = (attr.get("name") or "").strip()
    if nm:
        g = await geocode_address(f"{nm} {destination}".strip(), api_key)
        if g:
            return float(g[0]), float(g[1])
    if destination:
        g = await geocode_address(destination, api_key)
        if g:
            return float(g[0]), float(g[1])
    return None


def _dedupe_by_place_id(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        pid = str(row.get("place_id") or "").strip()
        if not pid or pid in seen:
            continue
        seen.add(pid)
        out.append(row)
    return out


async def _one_restaurant_record(
    nearby_row: dict[str, Any], api_key: str
) -> dict[str, Any] | None:
    place_id = str(nearby_row.get("place_id") or "").strip()
    if not place_id:
        return None
    vicinity = str(nearby_row.get("vicinity") or "").strip()
    details = await fetch_place_details_raw(place_id, api_key)
    if not details:
        # Details 실패 시 Nearby 정보만 사용
        name = str(nearby_row.get("name") or "").strip()
        rating = float(nearby_row.get("rating") or 0.0)
        rev = int(nearby_row.get("user_ratings_total") or 0)
        desc = vicinity or "Google Places 근처 검색 결과입니다."
        return {
            "id": place_id,
            "place_id": place_id,
            "name": name or place_id,
            "rating": rating,
            "user_ratings_total": rev,
            "description": desc,
            "website": None,
            "google_maps_url": f"https://www.google.com/maps/search/?api=1&query_place_id={place_id}",
        }

    name = str(details.get("name") or nearby_row.get("name") or "").strip()
    rating = float(details.get("rating") or nearby_row.get("rating") or 0.0)
    rev = int(details.get("user_ratings_total") or nearby_row.get("user_ratings_total") or 0)
    desc = _build_description(details, vicinity)
    web = (details.get("website") or "").strip()
    website = web if web.startswith("http") else None
    return {
        "id": place_id,
        "place_id": place_id,
        "name": name,
        "rating": rating,
        "user_ratings_total": rev,
        "description": desc,
        "website": website,
        "google_maps_url": _maps_url_from_details(details, place_id),
    }


async def restaurants_near_attraction(
    attr: dict[str, Any], destination: str, api_key: str, *, need: int = 3
) -> list[dict[str, Any]]:
    """명소 1곳 주변 실제 식당 need개 (Places Nearby + Details)."""
    if not (api_key or "").strip():
        return []
    ll = await _resolve_attr_lat_lng(attr, destination, api_key)
    if not ll:
        return []
    lat, lng = ll
    raw = await _nearby_restaurants(lat, lng, api_key)
    if len(raw) < need:
        raw.extend(await _textsearch_restaurants(lat, lng, api_key))
    raw = _dedupe_by_place_id(raw)
    filtered = [x for x in raw if _is_food_establishment(list(x.get("types") or []))]
    if len(filtered) < need:
        filtered = raw
    filtered.sort(key=_score_row, reverse=True)
    candidates = filtered[: max(need * 2, 8)]

    sem = asyncio.Semaphore(4)

    async def run_one(row: dict[str, Any]) -> dict[str, Any] | None:
        async with sem:
            return await _one_restaurant_record(row, api_key)

    tasks = [run_one(r) for r in candidates[:need]]
    done = await asyncio.gather(*tasks)
    out = [x for x in done if x]
    # 이름·평점 중복 제거
    seen_n: set[str] = set()
    uniq: list[dict[str, Any]] = []
    for x in out:
        key = re.sub(r"\s+", " ", (x.get("name") or "").lower()).strip()
        if key in seen_n:
            continue
        seen_n.add(key)
        uniq.append(x)
        if len(uniq) >= need:
            break
    return uniq[:need]


async def enrich_restaurants_by_attraction_from_places(
    route_bundle: dict[str, Any],
    selected_objs: list[dict[str, Any]],
    destination: str,
    api_key: str,
) -> dict[str, Any]:
    """restaurants_by_attraction를 Places 실데이터로 교체(가능할 때만)."""
    if not (api_key or "").strip():
        return route_bundle
    rba = route_bundle.get("restaurants_by_attraction")
    if not isinstance(rba, dict) or not rba:
        return route_bundle

    id_to_attr: dict[str, dict[str, Any]] = {}
    for a in selected_objs:
        if isinstance(a, dict) and a.get("id"):
            id_to_attr[str(a["id"])] = a

    new_rba: dict[str, list[dict[str, Any]]] = dict(rba)

    async def fill_one(aid: str) -> None:
        attr = id_to_attr.get(str(aid))
        if not attr:
            return
        try:
            got = await restaurants_near_attraction(attr, destination, api_key, need=3)
        except Exception as e:
            logger.warning("restaurants_near_attraction %s: %s", aid, e)
            return
        if len(got) >= 2:
            new_rba[str(aid)] = got

    await asyncio.gather(*[fill_one(aid) for aid in list(rba.keys())])

    out = dict(route_bundle)
    out["restaurants_by_attraction"] = new_rba
    return out

"""명소 입장·주차 요금 보강 — SerpApi Google 검색 스니펫(Places API만으로는 금액 필드 없음)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "TripAgent/1.0 (https://github.com/jjhanx/trip-agent; fees search)"

_MAX_SNIPPET_BLOCK = 1600


async def _serpapi_google_search(q: str, api_key: str, *, hl: str = "ko", num: int = 8) -> dict[str, Any]:
    url = "https://serpapi.com/search.json?" + urlencode(
        {
            "engine": "google",
            "q": q,
            "api_key": api_key,
            "hl": hl,
            "num": num,
        }
    )
    async with httpx.AsyncClient(timeout=22.0, headers={"User-Agent": USER_AGENT}) as client:
        r = await client.get(url)
        r.raise_for_status()
        data = r.json()
    if data.get("error"):
        logger.warning("serpapi google search error: %s", data.get("error"))
        return {}
    return data


def _organic_text_from_serp(data: dict[str, Any], max_chars: int = _MAX_SNIPPET_BLOCK) -> str:
    parts: list[str] = []
    ab = data.get("answer_box") or {}
    if isinstance(ab, dict):
        ans = ab.get("answer")
        if ans:
            parts.append(str(ans).strip())
        sn = ab.get("snippet")
        if sn:
            parts.append(str(sn).strip())
    kg = data.get("knowledge_graph") or {}
    if isinstance(kg, dict):
        desc = kg.get("description")
        if desc:
            parts.append(str(desc).strip())
    for o in (data.get("organic_results") or [])[:7]:
        if not isinstance(o, dict):
            continue
        t = (o.get("title") or "").strip()
        s = (o.get("snippet") or "").strip()
        if t or s:
            parts.append(f"{t}. {s}".strip())
    out = "\n".join(parts)
    if len(out) > max_chars:
        return out[:max_chars].rstrip() + "…"
    return out


async def fetch_fee_search_snippets_for_attraction(
    name: str,
    destination: str,
    api_key: str,
) -> str:
    """`{이름} 입장료`, `{이름} 주차비` 각각 Google 검색 스니펫을 모은다."""
    name = (name or "").strip()
    if not name or not (api_key or "").strip():
        return ""

    q_admission = f"{name} 입장료"
    q_parking = f"{name} 주차비"
    dest = (destination or "").strip()
    if dest and dest not in name and len(name) < 40:
        q_admission = f"{name} {dest} 입장료"
        q_parking = f"{name} {dest} 주차비"

    async def one(query: str) -> str:
        try:
            data = await _serpapi_google_search(query, api_key)
            return _organic_text_from_serp(data)
        except Exception as e:
            logger.debug("serpapi fee search failed %s: %s", query[:100], e)
            return ""

    t1, t2 = await asyncio.gather(one(q_admission), one(q_parking))
    blocks: list[str] = []
    if t1:
        blocks.append(f"[검색: 입장료]\n{t1}")
    if t2:
        blocks.append(f"[검색: 주차비]\n{t2}")
    return "\n\n".join(blocks).strip()


async def enrich_attractions_fee_search_snippets(
    attractions: list[dict[str, Any]],
    api_key: str,
    destination: str,
) -> None:
    """각 명소에 `_fee_search_snippets` 문자열을 붙인다(폴리시·비-LLM 폴백용)."""
    if not attractions or not (api_key or "").strip():
        return

    sem = asyncio.Semaphore(5)

    async def one(idx: int) -> None:
        a = attractions[idx]
        if not isinstance(a, dict):
            return
        nm = str(a.get("name") or "").strip()
        if not nm:
            return
        async with sem:
            snip = await fetch_fee_search_snippets_for_attraction(nm, destination, api_key)
        if snip:
            a["_fee_search_snippets"] = snip

    await asyncio.gather(*(one(i) for i in range(len(attractions))))

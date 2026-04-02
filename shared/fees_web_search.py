"""입장·주차 요금 보강 — Google **웹 검색** 결과 스니펫만 사용(Places API로 입장료 필드를 받지 않음).

우선순위:
1) **Google Programmable Search (Custom Search JSON API)** — `GOOGLE_CSE_CX` + API 키(콘솔에서 Custom Search API 사용 설정)
2) **SerpApi `engine=google`** — Google 검색 결과 페이지를 JSON으로 받는 서비스(항공 등과 동일 키 가능)

둘 다 본질적으로 **google.com 검색 질의**에 대한 스니펫·요약을 가져오는 방식이다.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "TripAgent/1.0 (https://github.com/jjhanx/trip-agent; google web search snippets)"

_MAX_SNIPPET_BLOCK = 1600


async def _google_custom_search_json(q: str, api_key: str, cx: str) -> dict[str, Any]:
    """Google 공식 Custom Search JSON API (웹 검색)."""
    url = "https://www.googleapis.com/customsearch/v1?" + urlencode(
        {
            "key": api_key,
            "cx": cx,
            "q": q,
            "num": 8,
        }
    )
    async with httpx.AsyncClient(timeout=22.0, headers={"User-Agent": USER_AGENT}) as client:
        r = await client.get(url)
        try:
            data = r.json()
        except Exception:
            return {}
        if r.status_code != 200:
            logger.debug("google cse http %s: %s", r.status_code, str(data)[:300])
            return {}
        if data.get("error"):
            logger.debug("google cse error body: %s", data.get("error"))
            return {}
        return data


def _text_from_cse_items(data: dict[str, Any], max_chars: int = _MAX_SNIPPET_BLOCK) -> str:
    parts: list[str] = []
    for item in (data.get("items") or [])[:8]:
        if not isinstance(item, dict):
            continue
        t = (item.get("title") or "").strip()
        s = (item.get("snippet") or "").strip()
        if t or s:
            parts.append(f"{t}. {s}".strip())
    out = "\n".join(parts)
    if len(out) > max_chars:
        return out[:max_chars].rstrip() + "…"
    return out


async def _serpapi_google_search(q: str, api_key: str, *, hl: str = "ko", num: int = 8) -> dict[str, Any]:
    """SerpApi: Google 검색 엔진 결과(JSON)."""
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


def _text_from_serp_organic(data: dict[str, Any], max_chars: int = _MAX_SNIPPET_BLOCK) -> str:
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


async def _one_query_snippets(
    q: str,
    *,
    google_api_key: str,
    google_cse_cx: str,
    serpapi_key: str,
) -> str:
    """한 검색어에 대해 CSE → SerpApi 순으로 시도."""
    gk = (google_api_key or "").strip()
    cx = (google_cse_cx or "").strip()
    sk = (serpapi_key or "").strip()

    if cx and gk:
        try:
            data = await _google_custom_search_json(q, gk, cx)
            if data.get("items"):
                return _text_from_cse_items(data)
            err = data.get("error", {})
            if isinstance(err, dict) and err.get("message"):
                logger.debug("cse empty or error: %s", err.get("message"))
        except Exception as e:
            logger.debug("google custom search failed %s: %s", q[:80], e)

    if sk:
        try:
            data = await _serpapi_google_search(q, sk)
            return _text_from_serp_organic(data)
        except Exception as e:
            logger.debug("serpapi search failed %s: %s", q[:80], e)
    return ""


async def fetch_google_search_snippets_for_attraction(
    name: str,
    destination: str,
    *,
    google_api_key: str = "",
    google_cse_cx: str = "",
    serpapi_key: str = "",
) -> str:
    """`{이름} 입장료`, `{이름} 주차비`로 Google 웹 검색한 결과 스니펫을 모은다."""
    name = (name or "").strip()
    if not name:
        return ""
    if not (google_cse_cx and google_api_key) and not (serpapi_key or "").strip():
        return ""

    q_admission = f"{name} 입장료"
    q_parking = f"{name} 주차비"
    dest = (destination or "").strip()
    if dest and dest not in name and len(name) < 40:
        q_admission = f"{name} {dest} 입장료"
        q_parking = f"{name} {dest} 주차비"

    t1, t2 = await asyncio.gather(
        _one_query_snippets(
            q_admission,
            google_api_key=google_api_key,
            google_cse_cx=google_cse_cx,
            serpapi_key=serpapi_key,
        ),
        _one_query_snippets(
            q_parking,
            google_api_key=google_api_key,
            google_cse_cx=google_cse_cx,
            serpapi_key=serpapi_key,
        ),
    )
    blocks: list[str] = []
    if t1:
        blocks.append(f"[Google 웹 검색: 입장료]\n{t1}")
    if t2:
        blocks.append(f"[Google 웹 검색: 주차비]\n{t2}")
    return "\n\n".join(blocks).strip()


async def enrich_attractions_google_search_snippets(
    attractions: list[dict[str, Any]],
    destination: str,
    *,
    google_api_key: str = "",
    google_cse_cx: str = "",
    serpapi_key: str = "",
) -> None:
    """각 명소에 `_google_web_search_snippets`를 붙인다."""
    if not attractions:
        return
    if not ((google_cse_cx or "").strip() and (google_api_key or "").strip()) and not (
        serpapi_key or ""
    ).strip():
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
            snip = await fetch_google_search_snippets_for_attraction(
                nm,
                destination,
                google_api_key=google_api_key,
                google_cse_cx=google_cse_cx,
                serpapi_key=serpapi_key,
            )
        if snip:
            a["_google_web_search_snippets"] = snip

    await asyncio.gather(*(one(i) for i in range(len(attractions))))


# 하위 호환 (이전 import 경로)
enrich_attractions_fee_search_snippets = enrich_attractions_google_search_snippets

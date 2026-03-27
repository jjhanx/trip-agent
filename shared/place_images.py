"""명소별 실제 장소 이미지: Wikipedia·Wikimedia Commons 우선, 선택 시 SerpApi 이미지 검색."""

from __future__ import annotations

import asyncio
import html as html_mod
import logging
import re
from typing import Any
from urllib.parse import urlencode

import httpx

from shared.image_fallbacks import unsplash_scenic_pool

logger = logging.getLogger(__name__)

# https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy
USER_AGENT = (
    "TripAgent/1.0 (https://github.com/jjhanx/trip-agent; "
    "itinerary place thumbnails; contact via repo)"
)

ENWIKI_API = "https://en.wikipedia.org/w/api.php"
ITWIKI_API = "https://it.wikipedia.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"


def _strip_html_credit(s: str) -> str:
    t = html_mod.unescape(s or "")
    t = re.sub(r"<[^>]+>", " ", t)
    return " ".join(t.split())[:220]


def _unsplash_fallback(idx: int) -> dict[str, str]:
    pool = unsplash_scenic_pool()
    u, c = pool[idx % len(pool)]
    return {"image_url": u, "image_credit": c, "image_source": "unsplash_fallback"}


async def _get_json(client: httpx.AsyncClient, base: str, params: dict[str, Any]) -> dict[str, Any] | None:
    try:
        r = await client.get(base, params=params)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.debug("place_images request failed: %s", e)
        return None


async def fetch_wikipedia_article_thumbnail(
    client: httpx.AsyncClient,
    api_root: str,
    search_query: str,
    lang_label: str,
) -> dict[str, str] | None:
    """위키백과 검색 → 첫 문서의 썸네일(해당 장소를 설명하는 사진인 경우가 많음)."""
    q = search_query.strip()[:300]
    if len(q) < 2:
        return None
    data = await _get_json(
        client,
        api_root,
        {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": q,
            "srlimit": 1,
            "srnamespace": 0,
        },
    )
    if not data:
        return None
    hits = (data.get("query") or {}).get("search") or []
    if not hits:
        return None
    title = hits[0].get("title")
    if not title:
        return None
    data2 = await _get_json(
        client,
        api_root,
        {
            "action": "query",
            "format": "json",
            "titles": title,
            "prop": "pageimages",
            "piprop": "thumbnail",
            "pithumbsize": 960,
        },
    )
    if not data2:
        return None
    pages = (data2.get("query") or {}).get("pages") or {}
    for _pid, page in pages.items():
        thumb = page.get("thumbnail") or {}
        src = thumb.get("source")
        if src and src.startswith("https://"):
            return {
                "image_url": src,
                "image_credit": f"Wikipedia ({lang_label}) · {title} · article thumbnail",
                "image_source": "wikipedia_thumb",
            }
    return None


async def fetch_commons_file_thumbnail(client: httpx.AsyncClient, search_query: str) -> dict[str, str] | None:
    """Commons 파일 검색 → 첫 이미지의 스케일된 URL + 라이선스 메타(가능 시)."""
    q = search_query.strip()[:300]
    if len(q) < 2:
        return None
    data = await _get_json(
        client,
        COMMONS_API,
        {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": q,
            "srnamespace": 6,
            "srlimit": 3,
        },
    )
    if not data:
        return None
    hits = (data.get("query") or {}).get("search") or []
    for h in hits:
        title = h.get("title")
        if not title or not title.startswith("File:"):
            continue
        data2 = await _get_json(
            client,
            COMMONS_API,
            {
                "action": "query",
                "format": "json",
                "titles": title,
                "prop": "imageinfo",
                "iiprop": "url|extmetadata",
                "iiurlwidth": 960,
            },
        )
        if not data2:
            continue
        pages = (data2.get("query") or {}).get("pages") or {}
        for _pid, page in pages.items():
            infos = page.get("imageinfo") or []
            if not infos:
                continue
            info = infos[0]
            thumburl = info.get("thumburl") or info.get("url")
            if not thumburl or not str(thumburl).startswith("https://"):
                continue
            meta = info.get("extmetadata") or {}
            lic = (meta.get("LicenseShortName") or {}).get("value") or ""
            artist = (meta.get("Artist") or {}).get("value") or ""
            credit = "Wikimedia Commons"
            if lic:
                credit += f" · {lic}"
            if artist:
                credit += f" · {_strip_html_credit(artist)}"
            credit += f" · {title}"
            return {
                "image_url": str(thumburl),
                "image_credit": credit,
                "image_source": "commons_file",
            }
    return None


async def fetch_serpapi_google_image(
    query: str,
    api_key: str,
) -> dict[str, str] | None:
    """SerpApi google_images — 키·옵션 있을 때만. 저작권은 원 게시자에게 있음(표시용)."""
    if not api_key.strip():
        return None
    q = query.strip()[:200]
    if len(q) < 2:
        return None
    params = {
        "engine": "google_images",
        "q": q,
        "api_key": api_key,
        "num": 5,
        "ijn": 0,
    }
    url = "https://serpapi.com/search.json?" + urlencode(params)
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            client.headers["User-Agent"] = USER_AGENT
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.debug("serpapi images failed: %s", e)
        return None
    imgs = data.get("images_results") or []
    for im in imgs:
        u = im.get("original") or im.get("thumbnail")
        if u and str(u).startswith("https://"):
            title = (im.get("title") or "")[:80]
            return {
                "image_url": str(u),
                "image_credit": f"Google 이미지 검색 결과(저작권은 원 게시자) · {title}",
                "image_source": "serpapi_google_images",
            }
    return None


async def resolve_place_image(
    name: str,
    destination: str,
    *,
    serpapi_key: str = "",
    use_serpapi: bool = False,
    idx: int = 0,
) -> dict[str, str]:
    """이름·목적지로 실제 장소 이미지 URL을 찾는다. 실패 시 Unsplash 폴백."""
    name = (name or "").strip()
    dest = (destination or "").strip()
    q_full = f"{name} {dest}".strip() or name
    q_short = name or dest

    headers = {"User-Agent": USER_AGENT}
    async with httpx.AsyncClient(timeout=18, headers=headers) as client:
        for api, lang in (
            (ENWIKI_API, "en"),
            (ITWIKI_API, "it"),
        ):
            r = await fetch_wikipedia_article_thumbnail(client, api, q_full, lang)
            if not r and q_short != q_full:
                r = await fetch_wikipedia_article_thumbnail(client, api, q_short, lang)
            if r:
                return r

        r = await fetch_commons_file_thumbnail(client, q_full)
        if not r and q_short != q_full:
            r = await fetch_commons_file_thumbnail(client, q_short)
        if r:
            return r

    if use_serpapi and serpapi_key:
        r = await fetch_serpapi_google_image(q_full, serpapi_key)
        if not r and q_short != q_full:
            r = await fetch_serpapi_google_image(q_short, serpapi_key)
        if r:
            return r

    fb = _unsplash_fallback(idx)
    return fb


async def enrich_attractions_images(
    attractions: list[dict[str, Any]],
    destination: str,
    *,
    serpapi_key: str = "",
    use_serpapi: bool = False,
    max_concurrent: int = 4,
) -> list[dict[str, Any]]:
    """각 명소에 대해 위키·커먼스(및 선택 SerpApi)로 이미지 보강."""
    if not attractions:
        return attractions
    sem = asyncio.Semaphore(max_concurrent)

    async def one(i: int, a: dict[str, Any]) -> dict[str, Any]:
        out = dict(a)
        name = out.get("name") or ""
        try:
            async with sem:
                res = await resolve_place_image(
                    name,
                    destination,
                    serpapi_key=serpapi_key,
                    use_serpapi=use_serpapi,
                    idx=i,
                )
            out["image_url"] = res.get("image_url", out.get("image_url", ""))
            out["image_credit"] = res.get("image_credit", out.get("image_credit", ""))
            src = res.get("image_source", "")
            if src:
                out["image_source"] = src
        except Exception as e:
            logger.warning("enrich attraction image failed: %s", e)
        return out

    return await asyncio.gather(*[one(i, a) for i, a in enumerate(attractions)])

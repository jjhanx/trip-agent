"""명소별 이미지: Wikipedia·Commons·선택 SerpApi. URL 중복·부정확 매칭 억제, 실패 시 사진 생략."""

from __future__ import annotations

import html as html_mod
import logging
import re
from typing import Any
from urllib.parse import urlparse
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = (
    "TripAgent/1.0 (https://github.com/jjhanx/trip-agent; "
    "itinerary place thumbnails; contact via repo)"
)

ENWIKI_API = "https://en.wikipedia.org/w/api.php"
ITWIKI_API = "https://it.wikipedia.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"

# 너무 흔한 조사·관사 (영·이·독 등)
_STOP = frozenset({
    "the", "and", "for", "with", "from", "near", "that", "this", "are", "was",
    "de", "di", "da", "la", "le", "il", "lo", "gli", "del", "della", "delle", "degli",
    "von", "und", "der", "die", "das", "des", "ein", "eine", "dem", "den",
})

NO_IMAGE_CREDIT_KO = (
    "자동 검색으로 이 명소만의 사진을 확신할 수 없어 생략했습니다. "
    "Wikimedia Commons에서 명소명으로 검색해 보세요."
)


def normalize_url_key(url: str) -> str:
    """동일 자산의 다른 해상도 URL을 같은 것으로 본다."""
    if not url or not isinstance(url, str):
        return ""
        
    u = url.strip()
    
    # Google Places API 예외 처리 (쿼리의 photoreference 자체가 고유 키)
    if "maps.googleapis.com/maps/api/place/photo" in u:
        try:
            from urllib.parse import parse_qs
            p = urlparse(u)
            qs = parse_qs(p.query)
            refs = qs.get("photoreference")
            if refs:
                return f"google_places_{refs[0]}"
        except Exception:
            pass
        return u

    base_u = u.split("?")[0].rstrip("/")
    try:
        p = urlparse(base_u)
        return (p.netloc + p.path).lower()
    except Exception:
        return base_u.lower()


def _tokens(s: str) -> list[str]:
    s = re.sub(r"[^\w\s]", " ", (s or "").lower())
    return [w for w in s.split() if len(w) >= 3 and w not in _STOP]


def _title_relevant_to_attraction(article_title: str, attraction_name: str) -> bool:
    """문서/파일 제목이 명소 이름과 충분히 겹치는지(첫 검색 결과만 믿지 않음)."""
    if not attraction_name or not article_title:
        return False
    nt = _tokens(attraction_name)
    at = set(_tokens(article_title))
    if not nt:
        return True
    hit = sum(1 for w in nt if w in at)
    if len(nt) <= 2:
        return hit >= 1
    need = max(2, (len(nt) + 1) // 2)
    return hit >= need


def _commons_file_relevant(file_title: str, attraction_name: str) -> bool:
    """File: 이름이 명소와 어느 정도 연관되는지."""
    if not file_title or not attraction_name:
        return False
    base = file_title.replace("File:", "")
    base = re.sub(r"\.(jpg|jpeg|png|webp|tif|tiff)$", "", base, flags=re.I)
    base = base.replace("_", " ")
    return _title_relevant_to_attraction(base, attraction_name)


def _strip_html_credit(s: str) -> str:
    t = html_mod.unescape(s or "")
    t = re.sub(r"<[^>]+>", " ", t)
    return " ".join(t.split())[:220]


async def _get_json(client: httpx.AsyncClient, base: str, params: dict[str, Any]) -> dict[str, Any] | None:
    try:
        r = await client.get(base, params=params)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.debug("place_images request failed: %s", e)
        return None


async def _wiki_thumbnail_for_title(
    client: httpx.AsyncClient,
    api_root: str,
    title: str,
) -> str | None:
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
        if src and str(src).startswith("https://"):
            return str(src)
    return None


async def fetch_wikipedia_unique_thumbnail(
    client: httpx.AsyncClient,
    api_root: str,
    search_query: str,
    lang_label: str,
    attraction_name: str,
    exclude_url_keys: set[str],
    srlimit: int = 12,
) -> dict[str, str] | None:
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
            "srlimit": srlimit,
            "srnamespace": 0,
        },
    )
    if not data:
        return None
    hits = (data.get("query") or {}).get("search") or []
    for hit in hits:
        title = hit.get("title")
        if not title or not _title_relevant_to_attraction(title, attraction_name):
            continue
        src = await _wiki_thumbnail_for_title(client, api_root, title)
        if not src:
            continue
        key = normalize_url_key(src)
        if key in exclude_url_keys:
            continue
        return {
            "image_url": src,
            "image_credit": f"Wikipedia ({lang_label}) · {title} · article thumbnail",
            "image_source": "wikipedia_thumb",
        }
    return None


async def fetch_commons_unique_thumbnail(
    client: httpx.AsyncClient,
    search_query: str,
    attraction_name: str,
    exclude_url_keys: set[str],
    srlimit: int = 15,
) -> dict[str, str] | None:
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
            "srlimit": srlimit,
        },
    )
    if not data:
        return None
    hits = (data.get("query") or {}).get("search") or []
    for h in hits:
        title = h.get("title")
        if not title or not title.startswith("File:"):
            continue
        if not _commons_file_relevant(title, attraction_name):
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
            key = normalize_url_key(str(thumburl))
            if key in exclude_url_keys:
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


async def fetch_serpapi_google_image_unique(
    query: str,
    api_key: str,
    exclude_url_keys: set[str],
    max_results: int = 10,
) -> dict[str, str] | None:
    if not api_key.strip():
        return None
    q = query.strip()[:200]
    if len(q) < 2:
        return None
    params = {
        "engine": "google_images",
        "q": q,
        "api_key": api_key,
        "num": min(max_results, 10),
        "ijn": 0,
    }
    url = "https://serpapi.com/search.json?" + urlencode(params)
    try:
        async with httpx.AsyncClient(timeout=22) as client:
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
        if not u or not str(u).startswith("https://"):
            continue
        key = normalize_url_key(str(u))
        if key in exclude_url_keys:
            continue
        title = (im.get("title") or "")[:80]
        return {
            "image_url": str(u),
            "image_credit": f"Google 이미지 검색 결과(저작권은 원 게시자) · {title}",
            "image_source": "serpapi_google_images",
        }
    return None


async def fetch_google_places_unique(
    client: httpx.AsyncClient,
    query: str,
    api_key: str,
    exclude_url_keys: set[str],
) -> dict[str, str] | None:
    if not api_key.strip():
        return None
    q = query.strip()[:200]
    if len(q) < 2:
        return None
    params = {
        "query": q,
        "key": api_key,
    }
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json?" + urlencode(params)
    try:
        r = await client.get(url)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.debug("google places textsearch failed: %s", e)
        return None
    results = data.get("results") or []
    for res in results:
        photos = res.get("photos") or []
        if not photos:
            continue
        pref = photos[0].get("photo_reference")
        if not pref:
            continue
        title = (res.get("name") or q)[:80]
        place_id = res.get("place_id") or ""
        # redirect를 피하기 위해 maxwidth를 지정하여 이미지 URL 생성
        photo_url = f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=960&photoreference={pref}&key={api_key}"
        key = normalize_url_key(photo_url)
        if key in exclude_url_keys:
            continue
        return {
            "image_url": photo_url,
            "image_credit": f"Google Maps · {title}",
            "image_source": "google_places",
            "place_id": place_id,
        }
    return None


def _empty_result() -> dict[str, str]:
    return {
        "image_url": "",
        "image_credit": NO_IMAGE_CREDIT_KO,
        "image_source": "none",
    }


async def resolve_place_image(
    name: str,
    destination: str,
    *,
    exclude_url_keys: set[str] | None = None,
    serpapi_key: str = "",
    use_serpapi: bool = False,
    google_places_api_key: str = "",
) -> dict[str, str]:
    """배치 내 이미지 URL 중복(exclude_url_keys)을 피해 한 장만 고른다. 실패 시 빈 URL."""
    exclude_url_keys = exclude_url_keys or set()
    name = (name or "").strip()
    dest = (destination or "").strip()
    attraction_name = name
    q_full = f"{name} {dest}".strip() or name
    q_short = name or dest

    headers = {"User-Agent": USER_AGENT}
    async with httpx.AsyncClient(timeout=20, headers=headers) as client:
        # 1. Google Places API (가장 정확하고 무료 크레딧 활용 가능)
        if google_places_api_key:
            r = await fetch_google_places_unique(client, q_full, google_places_api_key, exclude_url_keys)
            if not r and q_short != q_full:
                r = await fetch_google_places_unique(client, q_short, google_places_api_key, exclude_url_keys)
            if r:
                return r

        # 2. Wikipedia Thumbnail
        for api, lang in ((ENWIKI_API, "en"), (ITWIKI_API, "it")):
            r = await fetch_wikipedia_unique_thumbnail(
                client, api, q_full, lang, attraction_name, exclude_url_keys
            )
            if not r and q_short != q_full:
                r = await fetch_wikipedia_unique_thumbnail(
                    client, api, q_short, lang, attraction_name, exclude_url_keys
                )
            if r:
                return r

        r = await fetch_commons_unique_thumbnail(client, q_full, attraction_name, exclude_url_keys)
        if not r and q_short != q_full:
            r = await fetch_commons_unique_thumbnail(client, q_short, attraction_name, exclude_url_keys)
        if r:
            return r

    if use_serpapi and serpapi_key:
        r = await fetch_serpapi_google_image_unique(q_full, serpapi_key, exclude_url_keys)
        if not r and q_short != q_full:
            r = await fetch_serpapi_google_image_unique(q_short, serpapi_key, exclude_url_keys)
        if r:
            return r

    return _empty_result()


async def enrich_attractions_images(
    attractions: list[dict[str, Any]],
    destination: str,
    *,
    serpapi_key: str = "",
    use_serpapi: bool = False,
    google_places_api_key: str = "",
) -> list[dict[str, Any]]:
    """순차 처리로 이미지 URL 중복 제거. 부정확한 일반 풍경(Unsplash) 폴백 없음."""
    if not attractions:
        return attractions
    used_keys: set[str] = set()
    out: list[dict[str, Any]] = []

    used_place_ids: set[str] = set()

    for a in attractions:
        item = dict(a)
        name = item.get("name") or ""
        try:
            if item.get("place_id") and item.get("image_url"):
                res = {
                    "place_id": item.get("place_id"),
                    "image_url": item.get("image_url"),
                    "image_credit": item.get("image_credit", ""),
                    "image_source": item.get("image_source", ""),
                }
            else:
                res = await resolve_place_image(
                    name,
                    destination,
                    exclude_url_keys=used_keys,
                    serpapi_key=serpapi_key or "",
                    use_serpapi=use_serpapi,
                    google_places_api_key=google_places_api_key or "",
                )
            
            pid = res.get("place_id")
            if pid:
                if pid in used_place_ids:
                    continue  # 완벽히 같은 장소이므로 생략 (중복 제거)
                used_place_ids.add(pid)
                
            u = (res.get("image_url") or "").strip()
            if u.startswith("https://"):
                k = normalize_url_key(u)
                if k and k not in used_keys:
                    used_keys.add(k)
                    item["image_url"] = u
                    item["image_credit"] = res.get("image_credit", "")
                    item["image_source"] = res.get("image_source", "")
                else:
                    item["image_url"] = ""
                    item["image_credit"] = NO_IMAGE_CREDIT_KO
                    item["image_source"] = "duplicate_skipped"
            else:
                item["image_url"] = ""
                item["image_credit"] = res.get("image_credit", NO_IMAGE_CREDIT_KO)
                item["image_source"] = res.get("image_source", "none")
        except Exception as e:
            logger.warning("enrich attraction image failed: %s", e)
            item["image_url"] = ""
            item["image_credit"] = NO_IMAGE_CREDIT_KO
            item["image_source"] = "error"
        out.append(item)

    return out

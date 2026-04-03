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


def _clean_name_for_places_search(name: str) -> str:
    """Place Text Search·제목 매칭용: 한글 부제·전망 설명을 줄여 라틴 지명으로 검색·매칭하기 쉽게 한다."""
    s = (name or "").strip()
    if not s:
        return ""
    s = re.sub(r"（[^）]*）", " ", s)
    s = re.sub(r"\([^)]*[가-힣][^)]*\)", " ", s)
    for tail in (
        "전망 포인트",
        "전망포인트",
        "뷰포인트",
        "뷰 포인트",
        "관망 포인트",
        "전망대",
    ):
        s = s.replace(tail, " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:200]


def _tokens_attraction_match(s: str) -> list[str]:
    """Places/Commons 제목과 비교할 때 명소명 쪽 토큰.
    한글·괄호 설명이 붙으면 토큰이 늘어 (cadini, misurina, 포인트…) 과반 일치 요구가 커져
    Google/Commons 라틴 지명만 있는 제목과 매칭이 실패할 수 있음 → 라틴 지명 토큰을 우선한다."""
    allw = _tokens(s)
    latin = [w for w in allw if re.match(r"^[a-z]{3,}$", w)]
    if len(latin) >= 2:
        return latin
    if len(latin) == 1:
        return latin + [w for w in allw if w not in latin]
    return allw


def _title_relevant_to_attraction(article_title: str, attraction_name: str) -> bool:
    """문서/파일 제목이 명소 이름과 충분히 겹치는지(첫 검색 결과만 믿지 않음)."""
    if not attraction_name or not article_title:
        return False
    nt = _tokens_attraction_match(attraction_name)
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


def _serpapi_title_likely_wrong_region(title: str, attraction_name: str) -> bool:
    """한국 소매·배달 등 엉뚱한 썸네일 제외."""
    t = (title or "").lower()
    if any(x in t for x in ("마트", "창동", "하나로", "hanaro", "emart", "이마트", "쿠팡", "배달")):
        return True
    if any(x in t for x in ("korea", "seoul", "busan", "incheon")) and not _title_relevant_to_attraction(
        title, attraction_name
    ):
        return True
    return False


async def fetch_serpapi_google_image_unique(
    query: str,
    api_key: str,
    exclude_url_keys: set[str],
    max_results: int = 10,
    *,
    attraction_name: str = "",
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
        "hl": "en",
        "gl": "it",
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
        title = (im.get("title") or "")[:200]
        if _serpapi_title_likely_wrong_region(title, attraction_name):
            continue
        return {
            "image_url": str(u),
            "image_credit": f"Google 이미지 검색 결과(저작권은 원 게시자) · {title[:80]}",
            "image_source": "serpapi_google_images",
        }
    return None


async def fetch_google_places_unique(
    client: httpx.AsyncClient,
    query: str,
    api_key: str,
    exclude_url_keys: set[str],
    *,
    attraction_name: str = "",
    location_bias: str | None = None,
    radius_m: int = 85000,
) -> dict[str, str] | None:
    if not api_key.strip():
        return None
    q = query.strip()[:200]
    if len(q) < 2:
        return None
    params: dict[str, Any] = {
        "query": q,
        "key": api_key,
    }
    if location_bias and "," in location_bias:
        params["location"] = location_bias.strip()
        params["radius"] = str(min(max(radius_m, 1000), 50000))
    url = "https://maps.googleapis.com/maps/api/place/textsearch/json?" + urlencode(params)
    try:
        r = await client.get(url)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.debug("google places textsearch failed: %s", e)
        return None
    results = data.get("results") or []
    an = (attraction_name or "").strip()
    details_attempts = 0
    max_details_fallback = 5
    for res in results:
        pname = (res.get("name") or "").strip()
        if an and pname and not _title_relevant_to_attraction(pname, an):
            continue
        place_id = (res.get("place_id") or "").strip()
        photos = res.get("photos") or []
        title = (pname or q)[:80]
        if photos:
            pref = photos[0].get("photo_reference")
            if pref:
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
        # Text Search 응답에 photos가 비어 있어도 Place Details(photos) + Place Photo URL로 받을 수 있음
        if place_id and details_attempts < max_details_fallback:
            details_attempts += 1
            r2 = await fetch_place_photo_from_place_details(
                client, place_id, api_key, exclude_url_keys, maxwidth=960
            )
            if r2:
                return r2
    return None


def _empty_result() -> dict[str, str]:
    return {
        "image_url": "",
        "image_credit": NO_IMAGE_CREDIT_KO,
        "image_source": "none",
    }


async def fetch_place_photo_from_place_details(
    client: httpx.AsyncClient,
    place_id: str,
    api_key: str,
    exclude_url_keys: set[str],
    *,
    maxwidth: int = 960,
) -> dict[str, str] | None:
    """Place Details의 photos 필드로 공식 사진 URL 생성(Text Search에 photos가 없을 때 보강)."""
    if not place_id or not api_key.strip():
        return None
    url = "https://maps.googleapis.com/maps/api/place/details/json?" + urlencode(
        {
            "place_id": place_id,
            "fields": "photos,name",
            "key": api_key,
            "language": "en",
        }
    )
    try:
        r = await client.get(url)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.debug("place details photos failed: %s", e)
        return None
    if data.get("status") not in ("OK",):
        return None
    result = data.get("result") or {}
    photos = result.get("photos") or []
    if not photos:
        return None
    pref = photos[0].get("photo_reference")
    if not pref:
        return None
    place_name = (result.get("name") or "")[:80]
    photo_url = (
        f"https://maps.googleapis.com/maps/api/place/photo?"
        f"maxwidth={maxwidth}&photoreference={pref}&key={api_key}"
    )
    k = normalize_url_key(photo_url)
    if k in exclude_url_keys:
        return None
    return {
        "image_url": photo_url,
        "image_credit": f"Google Maps · {place_name}",
        "image_source": "google_places_details",
        "place_id": place_id,
    }


def _wikimedia_commons_fallback(name: str) -> dict[str, str] | None:
    """명소명 키워드로 알려진 Wikimedia Commons 썸네일(라이선스 명시)."""
    n = (name or "").lower()
    # (필요 키워드 튜플, url, credit)
    rules: list[tuple[tuple[str, ...], str, str]] = [
        (
            ("val di funes", "funes"),
            "https://upload.wikimedia.org/wikipedia/commons/thumb/6/6e/St._Johann_in_Ranui_mit_Geislergruppe.jpg/800px-St._Johann_in_Ranui_mit_Geislergruppe.jpg",
            "Wikimedia Commons · Val di Funes",
        ),
        (
            ("cadini", "misurina"),
            "https://upload.wikimedia.org/wikipedia/commons/thumb/4/4f/Cadini_di_Misurina.jpg/800px-Cadini_di_Misurina.jpg",
            "Wikimedia Commons · Cadini di Misurina",
        ),
        (
            ("카디니", "미수리나"),
            "https://upload.wikimedia.org/wikipedia/commons/thumb/4/4f/Cadini_di_Misurina.jpg/800px-Cadini_di_Misurina.jpg",
            "Wikimedia Commons · Cadini di Misurina",
        ),
        (
            ("passo gardena",),
            "https://upload.wikimedia.org/wikipedia/commons/thumb/2/2b/Passo_Gardena.jpg/800px-Passo_Gardena.jpg",
            "Wikimedia Commons · Passo Gardena",
        ),
        (
            ("lago", "carezza"),
            "https://upload.wikimedia.org/wikipedia/commons/thumb/7/7d/Karersee_01.jpg/800px-Karersee_01.jpg",
            "Wikimedia Commons · Lago di Carezza",
        ),
        (
            ("carezza", "karer"),
            "https://upload.wikimedia.org/wikipedia/commons/thumb/7/7d/Karersee_01.jpg/800px-Karersee_01.jpg",
            "Wikimedia Commons · Lago di Carezza",
        ),
        (
            ("karersee",),
            "https://upload.wikimedia.org/wikipedia/commons/thumb/7/7d/Karersee_01.jpg/800px-Karersee_01.jpg",
            "Wikimedia Commons · Karersee",
        ),
    ]
    for keys, img_url, credit in rules:
        if all(k in n for k in keys):
            return {
                "image_url": img_url,
                "image_credit": credit,
                "image_source": "wikimedia_commons_fallback",
            }
    return None


async def resolve_place_image(
    name: str,
    destination: str,
    *,
    exclude_url_keys: set[str] | None = None,
    serpapi_key: str = "",
    use_serpapi: bool = False,
    google_places_api_key: str = "",
    location_bias: str | None = None,
) -> dict[str, str]:
    """배치 내 이미지 URL 중복(exclude_url_keys)을 피해 한 장만 고른다. 실패 시 빈 URL."""
    exclude_url_keys = exclude_url_keys or set()
    name = (name or "").strip()
    dest = (destination or "").strip()
    cleaned = _clean_name_for_places_search(name)
    attraction_name = (cleaned if cleaned else name).strip()
    q_full = f"{attraction_name} {dest}".strip() or name
    q_short = attraction_name or name or dest

    headers = {"User-Agent": USER_AGENT}
    async with httpx.AsyncClient(timeout=20, headers=headers) as client:
        # 1. Google Places: Text Search → Place Photo URL, 또는 photos 없으면 Place Details(photos) → Place Photo
        if google_places_api_key:
            r = await fetch_google_places_unique(
                client,
                q_full,
                google_places_api_key,
                exclude_url_keys,
                attraction_name=attraction_name,
                location_bias=location_bias,
            )
            if not r and q_short != q_full:
                r = await fetch_google_places_unique(
                    client,
                    q_short,
                    google_places_api_key,
                    exclude_url_keys,
                    attraction_name=attraction_name,
                    location_bias=location_bias,
                )
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
        r = await fetch_serpapi_google_image_unique(
            q_full, serpapi_key, exclude_url_keys, attraction_name=attraction_name
        )
        if not r and q_short != q_full:
            r = await fetch_serpapi_google_image_unique(
                q_short, serpapi_key, exclude_url_keys, attraction_name=attraction_name
            )
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
    location_bias: str | None = None,
) -> list[dict[str, Any]]:
    """순차 처리로 이미지 URL 중복 제거. place_id만 있고 사진이 없으면 Details API로 보강, 이후 Commons 키워드 폴백."""
    if not attractions:
        return attractions
    used_keys: set[str] = set()
    out: list[dict[str, Any]] = []
    headers = {"User-Agent": USER_AGENT}

    async with httpx.AsyncClient(timeout=22, headers=headers) as details_client:
        for a in attractions:
            item = dict(a)
            name = item.get("name") or ""
            try:
                res: dict[str, str] | None = None
                pid = (item.get("place_id") or "").strip()
                existing = (item.get("image_url") or "").strip()

                if pid and existing.startswith("https://"):
                    res = {
                        "place_id": pid,
                        "image_url": existing,
                        "image_credit": item.get("image_credit", "") or "Google Maps",
                        "image_source": item.get("image_source", "") or "catalog",
                    }
                elif pid and google_places_api_key and not existing.startswith("https://"):
                    r = await fetch_place_photo_from_place_details(
                        details_client, pid, google_places_api_key, used_keys
                    )
                    if r:
                        res = r

                # 알려진 Wikimedia 정적 URL은 검색 실패·엄격한 제목 매칭보다 먼저(중복 키는 아래에서 걸러짐)
                if not res or not (res.get("image_url") or "").strip().startswith("https://"):
                    fb_early = _wikimedia_commons_fallback(name)
                    if fb_early:
                        u_e = (fb_early.get("image_url") or "").strip()
                        k_e = normalize_url_key(u_e)
                        if u_e.startswith("https://") and k_e and k_e not in used_keys:
                            res = fb_early

                if not res or not (res.get("image_url") or "").strip().startswith("https://"):
                    res = await resolve_place_image(
                        name,
                        destination,
                        exclude_url_keys=used_keys,
                        serpapi_key=serpapi_key or "",
                        use_serpapi=use_serpapi,
                        google_places_api_key=google_places_api_key or "",
                        location_bias=location_bias,
                    )

                if (not res.get("image_url") or not str(res.get("image_url")).strip().startswith("https://")):
                    fb = _wikimedia_commons_fallback(name)
                    if fb:
                        res = fb

                u = (res.get("image_url") or "").strip()
                if u.startswith("https://"):
                    k = normalize_url_key(u)
                    if k and k not in used_keys:
                        used_keys.add(k)
                        item["image_url"] = u
                        item["image_credit"] = res.get("image_credit", "")
                        item["image_source"] = res.get("image_source", "")
                        if res.get("place_id"):
                            item["place_id"] = res["place_id"]
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

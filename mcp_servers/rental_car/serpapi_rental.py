"""SerpApi Google 검색으로 렌트카 비교·OTA 페이지를 찾고, 스니펫에서 가격 힌트를 추출.

공식 ‘렌트카 쇼핑’ 엔진이 없어 Google organic 결과를 사용합니다.
금액은 요약문 기반이므로 일당/총액·세금 구분이 불명확할 수 있어 price_is_estimate로 표시합니다.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_FX_TO_KRW: dict[str, float] = {"EUR": 1580.0, "USD": 1450.0, "GBP": 1880.0, "KRW": 1.0}

_SKIP_SUBSTR = (
    "youtube.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "wikipedia.org",
    "reddit.com",
    "pinterest.com",
    "linkedin.com",
)


def _domain(url: str) -> str:
    try:
        h = urlparse(url).netloc.lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


def _extract_price_eur_usd_krw(text: str) -> tuple[float | None, str | None, bool]:
    """(amount, currency, looks_per_day) — 스니펫/제목에서 휴리스틱 추출."""
    if not text:
        return None, None, False
    t = text.replace("\xa0", " ")
    per_day = bool(re.search(r"/\s*day|per\s*day|\/일|일당", t, re.I))

    m = re.search(r"([\d,]+)\s*원", t)
    if m:
        return float(m.group(1).replace(",", "")), "KRW", per_day

    m = re.search(r"([\d.,]+)\s*€", t)
    if m:
        return float(m.group(1).replace(",", ".")), "EUR", per_day
    m = re.search(r"€\s*([\d.,]+)", t)
    if m:
        return float(m.group(1).replace(",", ".")), "EUR", per_day

    m = re.search(r"\$\s*([\d.,]+)", t)
    if m:
        return float(m.group(1).replace(",", ".")), "USD", per_day
    m = re.search(r"([\d.,]+)\s*(?:USD|usd)\b", t)
    if m:
        return float(m.group(1).replace(",", ".")), "USD", per_day

    m = re.search(
        r"(?:from|ab|desde|da|à partir|starting at)\s*([\d.,]+)\s*(€|\$|eur|usd)?",
        t,
        re.I,
    )
    if m:
        sym = (m.group(2) or "").lower()
        window = t[max(0, m.start() - 6) : m.end() + 8]
        if sym in ("€", "eur") or "€" in window:
            cur = "EUR"
        else:
            cur = "USD"
        return float(m.group(1).replace(",", ".")), cur, True

    return None, None, False


def _to_krw(amount: float, cur: str) -> int | None:
    r = _FX_TO_KRW.get(cur or "")
    if r is None:
        return None
    if cur == "KRW":
        return int(round(amount))
    return int(round(amount * r))


def _guess_seats(text: str) -> int | None:
    t = text.lower()
    m = re.search(r"(\d+)\s*[-]?\s*seats?\b", t)
    if m:
        return min(12, int(m.group(1)))
    m = re.search(r"(\d+)\s*인승", text)
    if m:
        return min(12, int(m.group(1)))
    if re.search(r"\b(7|8|9)[- ]?seater|minivan|people\s*carrier|mpv\b", t):
        return 7
    if "suv" in t and re.search(r"\b(5|7)\s*seats?\b", t):
        m2 = re.search(r"\b(5|7)\s*seats?\b", t)
        if m2:
            return int(m2.group(1))
    return None


def _organic_results_to_cards(
    organic: list,
    *,
    iata: str,
    pickup_date: str,
    return_date: str,
    days: int,
    passengers: int,
    query_tag: str,
    max_take: int,
) -> list[dict]:
    cards: list[dict] = []
    seen: set[str] = set()
    days = max(1, days)

    for i, item in enumerate(organic):
        if not isinstance(item, dict):
            continue
        link = (item.get("link") or "").strip()
        title = (item.get("title") or "").strip()
        snippet = (item.get("snippet") or "").strip()
        if not link or not title:
            continue
        dom = _domain(link)
        if not dom or dom in seen:
            continue
        if any(s in dom for s in _SKIP_SUBSTR):
            continue
        seen.add(dom)

        blob = f"{title} {snippet}"
        amt, cur, per_day = _extract_price_eur_usd_krw(blob)
        krw: int | None = None
        price_note = ""
        if amt is not None and cur:
            if per_day:
                total = amt * days
                krw = _to_krw(total, cur)
                price_note = f"스니펫 기준 일당 추정 × {days}일 → 환산"
            else:
                krw = _to_krw(amt, cur)
                price_note = "스니펫에 보인 금액(총액일 수 있음) 환산"

        seats = _guess_seats(blob)
        fits = seats is None or seats >= passengers

        cards.append(
            {
                "rental_id": f"SERP-{iata}-{query_tag}-{i}-{dom.replace('.', '-')[:20]}",
                "offer_kind": "serpapi_self_drive",
                "provider": dom,
                "car_type": "comparison" if "kayak" in dom or "skyscanner" in dom else "ota",
                "seats": seats,
                "vehicle_name": title[:200],
                "description": (snippet[:500] + "…") if len(snippet) > 500 else snippet or title,
                "features": [
                    f"일정 {pickup_date} ~ {return_date}",
                    f"일행 {passengers}명 검색어 반영",
                ],
                "luggage_capacity": "",
                "image_url": None,
                "pickup_location": iata,
                "dropoff_location": iata,
                "price_total_krw": krw,
                "price_is_estimate": True,
                "price_snippet_raw": f"{amt} {cur}" + (" /day" if per_day else "") if amt and cur else None,
                "price_basis": (
                    f"{price_note}. "
                    "Google 검색 요약(SerpApi) 기반이며 세금·보험·현지 수수료·실제 차종과 다를 수 있습니다. "
                    "최종 요금·약관은 링크 사이트에서 확인하세요."
                ),
                "recommended": fits,
                "booking_url": link,
                "source_label": "SerpApi · Google Search",
            }
        )
        if len(cards) >= max_take:
            break
    return cards


def _serpapi_google_organic(
    api_key: str, q: str, gl: str, num: int
) -> list | None:
    params = {
        "engine": "google",
        "q": q,
        "api_key": api_key,
        "hl": "en",
        "gl": gl,
        "num": num,
    }
    try:
        with httpx.Client(timeout=40.0) as client:
            r = client.get("https://serpapi.com/search.json", params=params)
    except Exception as e:
        logger.warning("SerpApi rental GET failed: %s", e)
        return None
    if r.status_code != 200:
        logger.warning("SerpApi rental HTTP %s", r.status_code)
        return None
    try:
        data = r.json()
    except Exception:
        return None
    if data.get("error"):
        logger.warning("SerpApi rental: %s", data.get("error"))
        return None
    return data.get("organic_results") or []


def search_serpapi_rental_offers(
    api_key: str,
    airport_iata: str,
    city_name: str | None,
    country_gl: str,
    pickup_date: str,
    return_date: str,
    days: int,
    passengers: int,
    max_results: int = 12,
    local_rental_keyword: str | None = None,
) -> list[dict]:
    """Google organic 결과 → 선택 가능한 카드(링크 + 가능 시 가격 힌트).

    영문·현지어 검색을 각각 한 번씩 호출해 도메인 기준 병합합니다(가격 힌트가 있는 쪽을 우선).
    """
    key = (api_key or "").strip()
    if not key:
        return []
    iata = (airport_iata or "").strip().upper()[:3]
    if len(iata) != 3:
        return []

    loc = f"{city_name.strip()} {iata} airport" if city_name and city_name.strip() else f"{iata} airport"
    seat_q = f"{passengers} passengers" if passengers else "passengers"
    extra = " 7 seater minivan" if passengers >= 6 else ""
    q_en = f"car hire {loc} pickup {pickup_date} dropoff {return_date} {seat_q} price{extra}"

    queries: list[tuple[str, str]] = [("en", q_en)]
    lk = (local_rental_keyword or "").strip()
    if lk and lk.lower() not in {"car hire", "car rental"}:
        city_bit = (city_name or "").strip()
        if city_bit:
            q_loc = f"{lk} {city_bit} {pickup_date} {return_date}"
        else:
            q_loc = f"{lk} {iata} {pickup_date} {return_date}"
        if q_loc.casefold() != q_en.casefold():
            queries.append(("loc", q_loc))

    gl = (country_gl or "us").strip().lower()[:2]
    num = min(20, max_results + 8)
    merged: dict[str, dict] = {}

    for tag, q in queries:
        organic = _serpapi_google_organic(key, q, gl, num)
        if organic is None:
            continue
        batch = _organic_results_to_cards(
            organic,
            iata=iata,
            pickup_date=pickup_date,
            return_date=return_date,
            days=days,
            passengers=passengers,
            query_tag=tag,
            max_take=max_results + 4,
        )
        for c in batch:
            link = (c.get("booking_url") or "").strip()
            dom = _domain(link)
            if not dom:
                continue
            prev = merged.get(dom)
            if prev is None:
                merged[dom] = c
                continue
            pk = prev.get("price_total_krw")
            ck = c.get("price_total_krw")
            if ck and not pk:
                merged[dom] = c
            elif pk == ck and not pk:
                if len((c.get("description") or "")) > len((prev.get("description") or "")):
                    merged[dom] = c

    cards = list(merged.values())
    cards.sort(
        key=lambda c: (
            0 if c.get("price_total_krw") else 1,
            0 if c.get("recommended") else 1,
        )
    )
    return cards[:max_results]

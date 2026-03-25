"""EconomyBookings 공개 목록 HTML에서 'From € X per day' 형태 일당 최저가 추출 (표시용 힌트).

실시간 예약 API가 없을 때 목록에 숫자 힌트를 주기 위한 보조. 고정 환율·일당×대여일이므로 최종 결제액과 다를 수 있습니다.
"""

from __future__ import annotations

import logging
import re

import httpx

logger = logging.getLogger(__name__)

EUR_TO_KRW_DISPLAY = 1580.0

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

# From € 5.65 per day / &euro;12.88 / € 10/day 등
_PAT_EUR_DAY = re.compile(
    r"(?:from|da|ab|desde)?\s*(?:€|&euro;)\s*([\d.,]+)\s*(?:per\s*day|/day|a\s*giorno)",
    re.I,
)
_PAT_EUR_DAY_ALT = re.compile(
    r"(?:€|&euro;)\s*([\d.,]+)\s*/\s*day",
    re.I,
)
# 일반 금액(일당 문구 없음) — 카드·위젯에 산재한 €만 모아 최저 후보로 사용
_PAT_EUR_TOKEN = re.compile(
    r"(?:€|&euro;)\s*([\d.,]+)|([\d.,]+)\s*(?:€|&euro;)",
    re.I,
)


def _parse_lowest_daily_eur(html: str) -> float | None:
    if not html or len(html) < 200:
        return None
    html = html.replace("&#8364;", "€").replace("&euro;", "€")
    vals: list[float] = []
    for pat in (_PAT_EUR_DAY, _PAT_EUR_DAY_ALT):
        for m in pat.finditer(html):
            try:
                v = float(m.group(1).replace(",", "."))
                if 1.0 <= v <= 5000.0:
                    vals.append(v)
            except ValueError:
                continue
    if vals:
        return min(vals)
    # 폴백: 렌트 카테고리·랜딩 페이지에서 흔한 € 표기만 수집(총액이 섞일 수 있어 상한 보수적)
    loose: list[float] = []
    for m in _PAT_EUR_TOKEN.finditer(html):
        raw = m.group(1) or m.group(2)
        if not raw:
            continue
        try:
            v = float(raw.replace(",", "."))
            if 3.0 <= v <= 400.0:
                loose.append(v)
        except ValueError:
            continue
    return min(loose) if loose else None


def fetch_lowest_daily_eur(url: str, timeout: float = 12.0) -> float | None:
    u = (url or "").strip()
    if not u.startswith("http"):
        return None
    try:
        with httpx.Client(timeout=timeout, headers={"User-Agent": _USER_AGENT, "Accept-Language": "en"}) as client:
            r = client.get(u, follow_redirects=True)
    except Exception as e:
        logger.debug("EconomyBookings fetch failed: %s", e)
        return None
    if r.status_code != 200:
        return None
    return _parse_lowest_daily_eur(r.text)


def daily_to_total_krw_hint(daily_eur: float, days: int) -> int:
    d = max(1, days)
    return int(round(daily_eur * d * EUR_TO_KRW_DISPLAY))

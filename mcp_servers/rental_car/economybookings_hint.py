"""EconomyBookings 공개 목록 HTML에서 'From € X per day' 형태 일당 추정 (표시용 힌트).

마케팅용 극저가(예: From €9/day)만 있으면 실제 장기·대형차 요금과 수십 배 차이가 나므로,
**일당 후보는 하한(기본 15€)과 중앙값**으로 보수적으로 잡습니다. 고정 환율·일당×대여일이므로 최종 결제액과 다릅니다.
"""

from __future__ import annotations

import logging
import re
import statistics

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
# 일반 금액(일당 문구 없음) — 문맥 없이 최저만 쓰면 마케팅 €9 등이 선택됨 → 구간 필터 후 중앙값
_PAT_EUR_TOKEN = re.compile(
    r"(?:€|&euro;)\s*([\d.,]+)|([\d.,]+)\s*(?:€|&euro;)",
    re.I,
)
_PAT_NUM_EUR_SUFFIX = re.compile(r"\b([\d.,]+)\s*EUR\b", re.I)

# 유럽 렌트 일당으로 그나마 신뢰할 만한 범위(마케팅 최저·총액 혼입 완화)
_MIN_RELIABLE_DAILY_EUR = 15.0
_MAX_REASONABLE_DAILY_EUR = 350.0


def _strip_html_noise_for_price(html: str) -> str:
    """스크립트·스타일 제거로 무관한 숫자 감소."""
    h = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.I | re.S)
    h = re.sub(r"<style[^>]*>.*?</style>", " ", h, flags=re.I | re.S)
    return h


def _floats_in_range(vals: list[float], lo: float, hi: float) -> list[float]:
    return [v for v in vals if lo <= v <= hi]


def _median(vals: list[float]) -> float | None:
    if not vals:
        return None
    return float(statistics.median(vals))


def _parse_lowest_daily_eur(html: str) -> float | None:
    if not html or len(html) < 200:
        return None
    html = _strip_html_noise_for_price(html)
    html = html.replace("&#8364;", "€").replace("&euro;", "€")

    strict: list[float] = []
    for pat in (_PAT_EUR_DAY, _PAT_EUR_DAY_ALT):
        for m in pat.finditer(html):
            try:
                v = float(m.group(1).replace(",", "."))
                if 1.0 <= v <= 5000.0:
                    strict.append(v)
            except ValueError:
                continue

    # 1) 'per day' 문구가 붙은 값 중, 현실적인 일당 구간만 (마케팅 €9 제외)
    good_strict = _floats_in_range(strict, _MIN_RELIABLE_DAILY_EUR, _MAX_REASONABLE_DAILY_EUR)
    if good_strict:
        return _median(good_strict)

    # 2) per day 값은 있으나 모두 15€ 미만(전형적 배너) → 사용하지 않음
    if strict and max(strict) < _MIN_RELIABLE_DAILY_EUR:
        pass
    elif strict:
        # 일부만 낮고 일부는 높음 → 낮은 쪽 제외 후 중앙값
        high = [v for v in strict if v >= _MIN_RELIABLE_DAILY_EUR]
        if high:
            return _median(high)

    # 3) 느슨한 € 토큰: 최저가 아니라 [15,350] 구간 중앙값 (총액·보증금 혼입 가능성은 여전히 있음)
    loose: list[float] = []
    for m in _PAT_EUR_TOKEN.finditer(html):
        raw = m.group(1) or m.group(2)
        if not raw:
            continue
        try:
            v = float(raw.replace(",", "."))
            if _MIN_RELIABLE_DAILY_EUR <= v <= _MAX_REASONABLE_DAILY_EUR:
                loose.append(v)
        except ValueError:
            continue
    for m in _PAT_NUM_EUR_SUFFIX.finditer(html):
        try:
            v = float(m.group(1).replace(",", "."))
            if _MIN_RELIABLE_DAILY_EUR <= v <= _MAX_REASONABLE_DAILY_EUR:
                loose.append(v)
        except ValueError:
            continue
    return _median(loose) if loose else None


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

"""EconomyBookings `/[lang]/cars/results` 딥링크 — plc/dlc·연월일·시각·나이 쿼리.

공항 랜딩 페이지 `__NEXT_DATA__`의 `mergedLocationId`를 읽어 plc/dlc에 넣습니다.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def _parse_merged_location_id(html: str) -> int | None:
    m = re.search(r'"mergedLocationId"\s*:\s*(\d+)', html)
    if m:
        return int(m.group(1))
    return None


@lru_cache(maxsize=128)
def fetch_merged_location_id_for_airport_url(airport_car_rental_url: str) -> int | None:
    """예: https://www.economybookings.com/car-rental/europe/italy/milan/mxp → 2042 (MXP)."""
    u = (airport_car_rental_url or "").strip()
    if not u.startswith("http"):
        return None
    try:
        with httpx.Client(timeout=20.0, headers={"User-Agent": _USER_AGENT}) as client:
            r = client.get(u, follow_redirects=True)
    except Exception as e:
        logger.debug("EB location id fetch failed: %s", e)
        return None
    if r.status_code != 200:
        return None
    lid = _parse_merged_location_id(r.text)
    return lid


def build_cars_results_url(
    merged_location_id: int,
    pickup_date: str,
    dropoff_date: str,
    pickup_time_hhmm: str,
    dropoff_time_hhmm: str,
    *,
    driver_age: int = 35,
    lang: str = "en",
) -> str:
    """EconomyBookings 검색 결과 진입용 URL (클라이언트가 쿼리로 폼을 채움)."""
    d1 = pickup_date.strip()[:10]
    d2 = dropoff_date.strip()[:10]
    y1, m1, day1 = (int(x) for x in d1.split("-"))
    y2, m2, day2 = (int(x) for x in d2.split("-"))
    q = {
        "plc": str(merged_location_id),
        "dlc": str(merged_location_id),
        "py": str(y1),
        "pm": str(m1),
        "pd": str(day1),
        "dy": str(y2),
        "dm": str(m2),
        "dd": str(day2),
        "pt": pickup_time_hhmm.strip() or "10:00",
        "dt": dropoff_time_hhmm.strip() or "10:00",
        "age": str(driver_age),
    }
    base = f"https://www.economybookings.com/{lang.strip().lower()}/cars/results"
    return f"{base}?{urlencode(q)}"


def build_airport_landing_url(
    region: str,
    country: str,
    city: str,
    airport: str,
    pickup_date: str,
    dropoff_date: str,
    pickup_time_hhmm: str,
    dropoff_time_hhmm: str,
) -> str:
    """매핑 없는 공항용 폴백(구 SEO 랜딩)."""
    base = f"https://www.economybookings.com/car-rental/{region}/{country}/{city}/{airport}"
    if len(pickup_date) >= 10 and len(dropoff_date) >= 10:
        q = urlencode({
            "pickup_date": pickup_date[:10],
            "dropoff_date": dropoff_date[:10],
            "pickup_time": pickup_time_hhmm or "10:00",
            "dropoff_time": dropoff_time_hhmm or "10:00",
            "return_time": dropoff_time_hhmm or "10:00",
        })
        return f"{base}?{q}"
    return base

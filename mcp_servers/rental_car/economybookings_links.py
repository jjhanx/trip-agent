"""EconomyBookings 공항 랜딩 URL 빌더.

`build_cars_results_url` 은 공항 HTML의 `mergedLocationId`로 검색 결과 화면을 엽니다.
빈 결과가 나올 수 있어 공항 랜딩 URL과 함께 제공합니다.
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
    """예: https://www.economybookings.com/en/car-rental/europe/italy/milan/mxp → mergedLocationId."""
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
    """공항 랜딩(영문 경로). 쿼리로 일시를 붙이면 사이트 폼에 반영되는 경우가 많습니다."""
    base = f"https://www.economybookings.com/en/car-rental/{region}/{country}/{city}/{airport}"
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

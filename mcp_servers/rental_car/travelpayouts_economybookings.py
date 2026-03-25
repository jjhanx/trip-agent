"""Travelpayouts → EconomyBookings 제휴: 리다이렉트 Location의 btag·tpo_uid를 공식 EB 딥링크에 합칩니다.

`https://economybookings.tpk.ro/…` 는 302로 `https://www.economybookings.com?btag=…&tpo_uid=…` 로 이어집니다.
이 쿼리를 `/car-rental/...` URL에 붙이면 동일 일정 링크가 제휴 추적을 유지합니다.
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx

logger = logging.getLogger(__name__)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def is_travelpayouts_economybookings_gateway(url: str) -> bool:
    u = (url or "").strip().lower()
    return "economybookings.tpk.ro" in u


def _first_redirect_location(affiliate_url: str) -> str | None:
    u = (affiliate_url or "").strip()
    if not u.startswith("http"):
        return None
    try:
        with httpx.Client(timeout=12.0, headers={"User-Agent": _USER_AGENT}) as client:
            r = client.request("HEAD", u, follow_redirects=False)
            if r.status_code in (301, 302, 303, 307, 308):
                loc = (r.headers.get("location") or "").strip()
                if loc:
                    return loc
            r2 = client.get(u, follow_redirects=False)
            if r2.status_code in (301, 302, 303, 307, 308):
                loc = (r2.headers.get("location") or "").strip()
                if loc:
                    return loc
    except Exception as e:
        logger.debug("TP EB affiliate HEAD/GET failed: %s", e)
    return None


def fetch_economybookings_tracking_params(affiliate_url: str) -> dict[str, str]:
    """제휴 진입 URL의 첫 리다이렉트에서 btag, tpo_uid 등 추출."""
    loc = _first_redirect_location(affiliate_url)
    if not loc:
        return {}
    # 상대 경로 → 절대
    if loc.startswith("/"):
        from urllib.parse import urljoin

        loc = urljoin(affiliate_url, loc)
    if "economybookings.com" not in loc.lower():
        return {}
    parsed = urlparse(loc)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    out: dict[str, str] = {}
    for k, v in qs.items():
        if v and v[0] is not None:
            out[k] = v[0]
    return out


def merge_economybookings_affiliate_query(
    economybookings_target_url: str,
    affiliate_entry_url: str | None,
) -> str:
    """direct EB URL에 제휴 쿼리(btag, tpo_uid) 병합. 실패 시 원본 반환."""
    target = (economybookings_target_url or "").strip()
    aff = (affiliate_entry_url or "").strip()
    if not target or not aff or not is_travelpayouts_economybookings_gateway(aff):
        return target
    if "economybookings.com" not in target.lower():
        return target
    tracking = fetch_economybookings_tracking_params(aff)
    if not tracking:
        return target
    p = urlparse(target)
    existing = parse_qs(p.query, keep_blank_values=True)
    merged: dict[str, str] = {}
    for k, vals in existing.items():
        if vals:
            merged[k] = vals[0]
    for k, v in tracking.items():
        merged[k] = v
    new_q = urlencode(merged)
    return urlunparse((p.scheme, p.netloc, p.path, p.params, new_q, p.fragment))

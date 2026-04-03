"""명소 후보에서 투어·여행사·현지 가이드 업체 등 비방문지 항목 제외."""

from __future__ import annotations

import re
from typing import Any

# Places API types — 방문 명소가 아니라 예약·안내 업무가 본업인 경우
_EXCLUDE_PRIMARY_TYPES = frozenset(
    {
        "travel_agency",
    }
)

# 자연 경관·공원 등은 이름에 outdoor가 있어도 업체로 보지 않음
_KEEP_NATURAL_TYPES = frozenset(
    {
        "natural_feature",
        "park",
        "campground",
        "national_park",
    }
)

# 이름만으로 가이드·투어 업체로 볼 때 (대소문자 무시)
_NAME_GUIDE_TOUR_RE: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\b(travel|tour)\s+agency\b"),
    re.compile(r"(?i)\b(tour|walking)\s+(guide|guides|operator|company|agency)\b"),
    re.compile(r"(?i)\blocal\s+guide\b"),
    re.compile(r"(?i)\bguided\s+(tours?|hikes?|excursions?)\b"),
    re.compile(r"(?i)\b(tour|trekking)\s+(agency|company|operator|service)\b"),
    re.compile(r"(?i)\bescursioni\s+(con\s+guida|guidate)\b"),
    re.compile(r"(?i)\bguida\s+(locale|alpina|montagna)\b"),
    re.compile(r"(?i)(현지\s*)?가이드|투어\s*(업체|회사|센터)"),
    re.compile(r"(?i)\bvercelli\s*outdoor\b"),
    re.compile(r"(?i)\boutdoor\s+(guide|guides|tours?|trek|team|experience|agency)\b"),
)

# 한 단어로 붙은 브랜드명 (예: Vercellioutdoor)
_COMPOUND_ENDS_WITH_OUTDOOR = re.compile(r"(?i)[a-z]{3,}outdoor$")


def is_guide_or_tour_operator_place(
    name: str | None,
    types: list[str] | None,
) -> bool:
    """
    투어·여행사·가이드 업체 등 방문 목적지가 아닌 장소면 True (후보에서 제외).
    """
    tset = {str(x) for x in (types or []) if x}
    if tset.intersection(_EXCLUDE_PRIMARY_TYPES):
        return True
    if tset.intersection(_KEEP_NATURAL_TYPES):
        return False

    raw = (name or "").strip()
    if not raw:
        return False

    for pat in _NAME_GUIDE_TOUR_RE:
        if pat.search(raw):
            return True
    if _COMPOUND_ENDS_WITH_OUTDOOR.search(raw):
        return True
    return False


def filter_attractions_drop_guide_services(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """명소 dict 리스트에서 가이드·투어 업체 항목을 제거."""
    out: list[dict[str, Any]] = []
    for a in items:
        if not isinstance(a, dict):
            continue
        nm = a.get("name")
        raw_typ = a.get("place_types") or a.get("types")
        if isinstance(raw_typ, str):
            typ: list[str] | None = [raw_typ]
        elif isinstance(raw_typ, list):
            typ = [str(x) for x in raw_typ]
        else:
            typ = None
        if is_guide_or_tour_operator_place(
            str(nm) if nm is not None else None,
            typ,
        ):
            continue
        out.append(a)
    return out

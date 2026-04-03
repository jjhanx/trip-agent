"""명소 후보에서 투어·여행사·현지 가이드 업체 등 비방문지 항목 제외."""

from __future__ import annotations

import re
from datetime import date
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


# 따뜻한 계절(고산 하이킹·드라이브)에는 스키 전용 시설을 추천하지 않음 — 5~9월
_WARM_SEASON_NO_SKI_MONTHS = frozenset({5, 6, 7, 8, 9})

# Places 타입: 스키장 단지
_SKI_PRIMARY_TYPES = frozenset({"ski_resort"})


def _name_suggests_summer_mountain_lift_or_viewpoint(name: str | None) -> bool:
    """돌로미티 등: Funivia·Marmolada·Tofana 등은 ski_resort 태그여도 여름 명소로 유지."""
    raw = (name or "").strip()
    if not raw:
        return False
    n = raw.lower()
    needles = (
        "funivia",
        "funicular",
        "telecabina",
        "gondola",
        "seilbahn",
        "bergbahn",
        "freccia nel cielo",
        "marmolada",
        "tofana",
        "sassolungo",
        "sasso lungo",
        "langkofel",
        "passo pordoi",
        "lagazuoi",
        "cinque torri",
        "col raiser",
        "seceda",
        "alpe di siusi",
        "seiser alm",
    )
    return any(x in n for x in needles)

# 박물관·전시 등 이름에 'ski'가 있어도 제외하지 않음
_SKIP_SKI_NAME_FILTER_TYPES = frozenset(
    {
        "museum",
        "art_gallery",
        "library",
    }
)

_SKI_ONLY_NAME_RE = re.compile(
    r"(?i)(\bski\s+(school|area|resort|station|park|rental|lesson|lessons)\b|"
    r"\b(scuola|scuole)\s+sci\b|"
    r"\bskischule\b|"
    r"\bécole\s+(de\s+)?ski\b|"
    r"\bsnow\s*park\b|"
    r"\bimpianti\s+sciistici\b|"
    r"\bcomprensorio\s+sciistico\b|"
    r"\bpiste\s+da\s+sci\b|"
    r"\bsci\s+club\b|"
    r"\b(ski\s*tour|skitour|sellaronda|sella\s*ronda|panorama\s+sellaronda)\b|"
    r"스키장\b|"
    r"스키\s*학교\b)"
)

# 소개 문구에 스키 투어·셀라론다 등이 드러나면 이름만으로는 걸러지지 않는 경우 보완
_SKI_MARKETING_IN_DESCRIPTION_RE = re.compile(
    r"(?i)(\bski\s*tour\b|\bskitour\b|\bsellaronda\b|\bsella\s*ronda\b|\bpanorama\s+sellaronda\b)"
)


def _months_in_trip_range(start_iso: str, end_iso: str) -> set[int]:
    """여행 기간에 포함되는 달(1~12) 집합(시작~종료 월 사이 전부)."""
    try:
        d0 = date.fromisoformat((start_iso or "")[:10])
        d1 = date.fromisoformat((end_iso or "")[:10])
    except ValueError:
        return set()
    if d1 < d0:
        d0, d1 = d1, d0
    months: set[int] = set()
    y, m = d0.year, d0.month
    ey, em = d1.year, d1.month
    while (y, m) <= (ey, em):
        months.add(m)
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def trip_overlaps_warm_season_no_ski_months(start_iso: str, end_iso: str) -> bool:
    """여행 일정이 5~9월 중 하루라도 겹치면 True (스키 전용 시설 필터 적용)."""
    ts = (start_iso or "").strip()
    te = (end_iso or "").strip() or ts
    if not ts:
        return False
    months = _months_in_trip_range(ts, te)
    return bool(months & _WARM_SEASON_NO_SKI_MONTHS)


def should_exclude_warm_season_ski_place(
    name: str | None,
    types: list[str] | None,
    trip_start: str,
    trip_end: str,
    description: str | None = None,
) -> bool:
    """
    따뜻한 계절(5~9월) 여행에 스키장·스키 학교 등 겨울 전용 시설이면 True(후보 제외).
    겨울 스키 목적 여행(기간이 5~9월과 안 겹침)에는 적용하지 않는다.
    Places가 케이블카·빙하역을 ski_resort로만 태그하는 경우가 있어, Funivia·Marmolada 등 이름은 제외하지 않는다.
    """
    if not trip_overlaps_warm_season_no_ski_months(trip_start, trip_end):
        return False

    tset = {str(x) for x in (types or []) if x}
    if tset.intersection(_SKIP_SKI_NAME_FILTER_TYPES):
        return False

    if tset.intersection(_SKI_PRIMARY_TYPES):
        # Places가 리프트역을 ski_resort로만 태그하는 경우가 많아 이름으로 여름 명소 여부를 완화
        if _name_suggests_summer_mountain_lift_or_viewpoint(name):
            return False
        return True

    raw = (name or "").strip()
    desc = (description or "").strip()
    if desc and _SKI_MARKETING_IN_DESCRIPTION_RE.search(desc):
        return True

    if not raw:
        return False
    if _SKI_ONLY_NAME_RE.search(raw):
        return True

    nl = raw.lower()
    if "ski" in nl and any(
        w in nl
        for w in (
            " school",
            " scuola",
            " lesson",
            " lezione",
            " rental",
            " noleggio sci",
            "skischule",
        )
    ):
        return True
    return False


def filter_attractions_warm_season_no_ski(
    items: list[dict[str, Any]],
    trip_start: str,
    trip_end: str,
) -> list[dict[str, Any]]:
    """여행 기간이 따뜻한 계절이면 스키 전용 시설 항목 제거."""
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
        if should_exclude_warm_season_ski_place(
            str(nm) if nm is not None else None,
            typ,
            trip_start,
            trip_end,
            str(a.get("description") or "").strip() or None,
        ):
            continue
        out.append(a)
    return out

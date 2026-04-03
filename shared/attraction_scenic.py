"""전역: 전망대·케이블카·케이블웨이 등 전형적 관광 명소 판별(특정 지역 전용 아님).

Places 검색 키워드·정렬 보정·여름 스키 필터 예외에서 공통으로 사용한다."""

from __future__ import annotations

from typing import Any

# 이름에 자주 붙는 표기(영어·유럽 위주). Places keyword는 영어가 많음.
VIEWPOINT_CABLE_LIFT_SUBSTRINGS: tuple[str, ...] = (
    "viewpoint",
    "lookout",
    "observation deck",
    "observation tower",
    "panorama",
    "vista",
    "overlook",
    "skydeck",
    "sky deck",
    "cable car",
    "cableway",
    "aerial tram",
    "funicular",
    "gondola",
    "ropeway",
    "tramway",
    "chairlift",
    "chair lift",
    "teleferico",
    "teleférico",
    "telepherique",
    "téléphérique",
    "telecabina",
    "funivia",
    "seilbahn",
    "bergbahn",
    "seggiovia",
    "aussichtspunkt",
    "aussicht",
    "mirador",
    "belvedere",
    "punto panoramico",
    "punto panorámico",
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


def name_suggests_viewpoint_cable_or_lift(name: str | None) -> bool:
    """이름만으로 전망·케이블카·리프트류 관광지로 볼 수 있으면 True."""
    raw = (name or "").strip()
    if not raw:
        return False
    n = raw.lower()
    return any(s in n for s in VIEWPOINT_CABLE_LIFT_SUBSTRINGS)


def place_has_scenic_lift_priority(p: dict[str, Any]) -> bool:
    """Places 결과에 대해 동일 평점 티어 안에서 앞쪽(우선)으로 둘지.

    자연 지형·공원·전망형 POI와 이름상 전망·리프트류를 넓게 포함한다.
    """
    types = {str(x).lower() for x in (p.get("types") or [])}
    if types.intersection({"natural_feature", "park"}):
        return True
    if name_suggests_viewpoint_cable_or_lift(p.get("name")):
        return True
    return False


def scenic_rank_bias(p: dict[str, Any]) -> int:
    """동일 티어 정렬용: 0이면 전망·리프트·자연 명소 우선, 1이면 그 외."""
    return 0 if place_has_scenic_lift_priority(p) else 1

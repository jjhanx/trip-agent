"""Itinerary Planner Agent — 명소 후보 → 경로·동네·맛집 → 식사 선택 → 최종 일정."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any

from a2a.server.agent_execution import RequestContext
from a2a.server.events import EventQueue

from agents.base_agent import BaseAgentExecutor
from config import Settings
from shared.attraction_filters import (
    filter_attractions_drop_guide_services,
    filter_attractions_warm_season_no_ski,
    is_guide_or_tour_operator_place,
    should_exclude_warm_season_ski_place,
)
from shared.directions_parking import enrich_attractions_parking_directions
from shared.google_place_details import (
    enrich_attractions_with_place_details,
    polish_practical_details_with_llm,
    sanitize_attraction_description_for_catalog,
    walking_hiking_clamp_smart,
)
from shared.place_images import enrich_attractions_images
from shared.utils import new_agent_text_message

logger = logging.getLogger(__name__)


def _trip_inclusive_days(start_date: str, end_date: str) -> int:
    d1 = datetime.strptime(start_date[:10], "%Y-%m-%d").date()
    d2 = datetime.strptime(end_date[:10], "%Y-%m-%d").date()
    return max(1, (d2 - d1).days + 1)


def _date_list(start_date: str, end_date: str) -> list[str]:
    d1 = datetime.strptime(start_date[:10], "%Y-%m-%d").date()
    d2 = datetime.strptime(end_date[:10], "%Y-%m-%d").date()
    out: list[str] = []
    cur = d1
    while cur <= d2:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


# 여행 일수×3 후보 상한(과도한 Places·LLM 부하 방지). 30일×3=90, 45일까지는 200까지 허용.
MAX_ITINERARY_ATTRACTION_CANDIDATES = 200


def _attraction_target_count(trip_days: int) -> int:
    """명소 후보 목표 개수 = 포함 일수 × 3 (상한 적용)."""
    return max(1, min(trip_days * 3, MAX_ITINERARY_ATTRACTION_CANDIDATES))

PRACTICAL_DETAIL_KEYS: tuple[str, ...] = (
    "parking",
    "cable_car_lift",
    "walking_hiking",
    "fees_other",
    "reservation_note",
    "tips",
)


def _looks_like_dolomites(destination: str) -> bool:
    d = (destination or "").lower()
    keys = (
        "dolomit",
        "dolomiti",
        "dolomiten",
        "tre cime",
        "braies",
        "siusi",
        "seceda",
        "ortisei",
        "cortina",
        "bolzano",
        "불차노",
        "도로미티",
        "돌로미티",
        "라고 디 브라이에스",
        "브라이에스",
    )
    return any(k in d for k in keys)


def _merge_practical_details(raw: Any) -> dict[str, str]:
    base = {k: "" for k in PRACTICAL_DETAIL_KEYS}
    if isinstance(raw, dict):
        for k in PRACTICAL_DETAIL_KEYS:
            v = raw.get(k)
            if v is not None and str(v).strip():
                base[k] = str(v).strip()
    _strip_cable_if_absent(base)
    return base


def _strip_cable_if_absent(pr: dict[str, str]) -> None:
    """케이블·리프트가 없을 때는 빈 문자열로 두어 UI에서 항목을 숨긴다."""
    v = (pr.get("cable_car_lift") or "").strip()
    if not v:
        return
    compact = v.replace(" ", "")
    if "해당없음" in compact or "해당 없음" in v:
        pr["cable_car_lift"] = ""


def _default_practical_block() -> dict[str, str]:
    """빈 칸은 보강 단계에서 채움. 사용자에게 지시문처럼 보이는 문장은 넣지 않는다."""
    return {
        "parking": "",
        "cable_car_lift": "",
        "walking_hiking": "",
        "fees_other": "",
        "reservation_note": "",
        "tips": "",
    }


_META_INSTRUCTION_SUBSTRINGS = (
    "명시한다",
    "채운다",
    "요약한다",
    "기재한다",
    "€ 또는 현지 통화로 명시",
    "예약 경로를 명시",
    "확인하십시오",
    "확인하세요",
)


def _prune_rating_only_tips(pr: dict[str, str]) -> None:
    """준비·팁에 평점·리뷰 수만 반복된 경우 제거(상단 소개와 중복)."""
    t = (pr.get("tips") or "").strip()
    if not t or len(t) > 180:
        return
    if re.search(r"Google\s*Maps\s*(기준\s*)?평점", t, re.I) and re.search(
        r"리뷰\s*약\s*\d+", t
    ):
        if not re.search(
            r"준비|물|재킷|등산|주차|인파|혼잡|시간|아침|저녁|날씨|계절|일출|일몰|산장|트레일",
            t,
        ):
            pr["tips"] = ""


def _strip_duplicate_maps_line_from_reservation(pr: dict[str, str]) -> None:
    """예약·운영 칸에 카드 상단과 동일한 Google Maps URL 줄 제거."""
    r = (pr.get("reservation_note") or "").strip()
    if not r or "Google Maps" not in r:
        return
    chunks = [p.strip() for p in r.split("|")]
    filtered = [
        c
        for c in chunks
        if c and not re.match(r"^Google\s*Maps\s*:\s*https?://", c.strip(), re.I)
    ]
    if len(filtered) < len(chunks):
        if filtered:
            pr["reservation_note"] = " | ".join(filtered)
        elif chunks and all(
            re.match(r"^Google\s*Maps\s*:\s*https?://", c.strip(), re.I) for c in chunks
        ):
            pr["reservation_note"] = "지도 링크는 카드 상단을 참고."


def _sanitize_meta_instruction_practical(pr: dict[str, str]) -> None:
    """LLM이 프롬프트 지시문을 그대로 붙여넣은 경우 비워 후속 보강·재시도 유도."""
    for k in PRACTICAL_DETAIL_KEYS:
        v = (pr.get(k) or "").strip()
        if not v:
            continue
        if any(s in v for s in _META_INSTRUCTION_SUBSTRINGS) and len(v) < 200:
            pr[k] = ""
            continue
        if k == "fees_other" and v.startswith("입장료·톨·보트") and "명시" in v:
            pr[k] = ""
        if k == "reservation_note" and "개방·운영 시간" in v and "명시" in v:
            pr[k] = ""
    _prune_rating_only_tips(pr)
    _strip_duplicate_maps_line_from_reservation(pr)


def _dedupe_attractions_by_canonical_name(attractions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """동일·유사 명소명 중복 제거(정규화 키 + 토큰 유사도, place_id·image가 있는 쪽 우선)."""
    if not attractions:
        return attractions

    def score(x: dict[str, Any]) -> tuple[int, int, int]:
        # 대표 사진이 있는 카드가 설명만 긴 카드보다 우선(이전에는 설명 길이만으로 이미지 없는 쪽이 남는 경우가 있었음)
        has_img = 1 if str(x.get("image_url") or "").strip().startswith("https://") else 0
        pid = 1 if (x.get("place_id") or "").strip() else 0
        return (has_img, pid, len(str(x.get("description") or "")))

    merged: list[dict[str, Any]] = []
    for a in attractions:
        if not isinstance(a, dict):
            continue
        nm = (a.get("name") or "").strip()
        key = _normalize_attraction_key(nm)
        found = -1
        for i, m in enumerate(merged):
            mn = (m.get("name") or "").strip()
            if key and key == _normalize_attraction_key(mn):
                found = i
                break
            if nm and mn and _names_likely_same(nm, mn):
                found = i
                break
        if found < 0:
            merged.append(dict(a))
            continue
        cur = merged[found]
        if score(a) > score(cur):
            oid = cur.get("id")
            new = dict(a)
            if oid:
                new["id"] = oid
            merged[found] = new
        elif len(nm) > len((cur.get("name") or "")):
            merged[found]["name"] = nm
            cu = str(merged[found].get("image_url") or "").strip()
            au = str(a.get("image_url") or "").strip()
            if not cu.startswith("https://") and au.startswith("https://"):
                merged[found]["image_url"] = au
                merged[found]["image_credit"] = a.get("image_credit", "")
                merged[found]["image_source"] = a.get("image_source", "")
    return merged


def _renumber_attraction_ids(attractions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i, a in enumerate(attractions):
        if not isinstance(a, dict):
            continue
        item = dict(a)
        item["id"] = f"attr_{i + 1:03d}"
        out.append(item)
    return out


def _order_attractions_https_image_first(attractions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """https 대표 이미지가 있는 카드를 앞에 두되, 후보 개수는 줄이지 않는다(없으면 빈 이미지·플레이스홀더)."""
    with_h: list[dict[str, Any]] = []
    without: list[dict[str, Any]] = []
    for a in attractions:
        if not isinstance(a, dict):
            continue
        u = str(a.get("image_url") or "").strip()
        if u.startswith("https://"):
            with_h.append(a)
        else:
            without.append(a)
    return with_h + without


def _ensure_attraction_record(a: dict[str, Any], idx: int, destination: str) -> dict[str, Any]:
    out = dict(a)
    out.setdefault("id", f"attr_{idx + 1:03d}")
    out.setdefault("name", f"{destination} 명소 {idx + 1}")
    out.setdefault("category", "관광")
    out.setdefault("description", "")
    out.setdefault("image_url", "")
    out.setdefault("image_credit", "")
    pr = _merge_practical_details(out.get("practical_details"))
    _sanitize_meta_instruction_practical(pr)
    defaults = _default_practical_block()
    for k in PRACTICAL_DETAIL_KEYS:
        if not pr[k]:
            pr[k] = defaults[k]
    out["practical_details"] = pr
    url = str(out.get("image_url") or "").strip()
    if url and not url.startswith("https://"):
        out["image_url"] = ""
    return out


def _dolomites_attraction_templates() -> list[dict[str, Any]]:
    """실제 관광지명·실무 정보 예시(한국어). 이미지는 Wikimedia Commons 링크 예시(서버 enrich로 검증·중복 제거)."""
    w = "Wikimedia Commons"
    result = [
        {
            "name": "Tre Cime di Lavaredo (Drei Zinnen)",
            "category": "하이킹·전망",
            "description": "돌로미티 상징 봉우리 세 개를 도보로 돌아보는 대표 코스. 오비스터리 산장·라바레도 산장 방향 루프가 유명합니다.",
            "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/1/1e/Drei_Zinnen_2010.jpg/800px-Drei_Zinnen_2010.jpg",
            "image_credit": f"{w} · Drei Zinnen",
            "practical_details": {
                "parking": "아우론조(Auronzo) 유료 주차장 이용. 성수기(여름·주말)에는 온라인 사전 예약이 사실상 필수인 경우가 많고, 일당 대략 €30~45 전후(연도·시즌·시간대별 상이). 차량으로 아우론조 주차장까지 진입 후 도보(해당 구간은 유료 도로·입장 개념이 붙는 시즌이 있음—현지 표지 확인).",
                "cable_car_lift": "",
                "walking_hiking": "오비스터리(Refugio Auronzo) 방향으로 이어지는 루프 왕복 보통 3~4시간 안팎(체력·사진·휴식에 따라 더 길어질 수 있음).",
                "fees_other": "유료 도로·환경 관련 요금이 붙는 구간이 있을 수 있음(시즌별).",
                "reservation_note": "주차 예약·입장 제한은 공식 파르체지오/지자체 페이지를 출발 전에 확인.",
                "tips": "이른 아침 출발, 방풍 재킷·물·간식, 날씨 급변 대비.",
            },
        },
        {
            "name": "Seceda",
            "category": "케이블카·전망",
            "description": "오르티세이에서 케이블카로 올라 날카로운 초원 능선과 기암을 한눈에 보는 명소.",
            "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/8/8a/Seceda_Gruppe_von_St.Ulrich_aus.jpg/800px-Seceda_Gruppe_von_St.Ulrich_aus.jpg",
            "image_credit": f"{w} · Seceda",
            "practical_details": {
                "parking": "오르티세이(Ortisei/St. Ulrich) 시내·외곽 유료 주차. 성수기에는 주차장 포화—셔틀·도보 접근 검토.",
                "cable_car_lift": "Furnes–Seceda 등 구간 조합(리프트·케이블카) 성인 편도 대략 €10~25대(시즌·노선·요금제 변동). 공식 가격표로 확인.",
                "walking_hiking": "정상부 전망 포인트까지 왕복 40분~1시간 30분(눈·진흙에 따라 더 걸릴 수 있음).",
                "fees_other": "멀티데이 패스·그룹 할인 여부는 현지 리프트 사이트 확인.",
                "reservation_note": "케이블카 시간대 예약이 필요한 성수기가 있음.",
                "tips": "운동화/등산화, 기온 차 큼, 안개 낀 날 시야 확인.",
            },
        },
        {
            "name": "Alpe di Siusi (Seiser Alm)",
            "category": "고원·가벼운 하이킹",
            "description": "유럽 최대 고산 목초지 중 하나로 평탄한 둘레 산책과 사진 명소가 많습니다.",
            "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e5/Seiser_Alm_2010.jpg/800px-Seiser_Alm_2010.jpg",
            "image_credit": f"{w} · Seiser Alm",
            "practical_details": {
                "parking": "Compatsch 등 접근 지점 주차는 성수기·환경 규제로 **일반 차량 진입 제한**이 있는 시간대가 많음. 지정 주차 후 셔틀·버스 또는 곤돌라 이용 안내를 따름.",
                "cable_car_lift": "오르티세이 등에서 Alpe로 올라가는 곤돌라·리프트(편도 약 €10~20대, 시즌별 변동).",
                "walking_hiking": "Compatsch 주변 평지 산책 1~2시간, 길게는 반나절 루프 가능.",
                "fees_other": "호텔 투숙객 전용 도로·예외 규정이 있을 수 있음.",
                "reservation_note": "고원 진입·셔틀은 사전 예약이 필요한 경우가 있음.",
                "tips": "자전거·패밀리 동반 시 셔틀 시간표 필수 확인.",
            },
        },
        {
            "name": "Lago di Braies (Pragser Wildsee)",
            "category": "호수·산책",
            "description": "에메랄드빛 호수와 산 능선이 어우러진 돌로미티 대표 호수. 둘레 산책과 보트가 인기입니다.",
            "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/9/91/Lago_di_Braies_panorama.jpg/800px-Lago_di_Braies_panorama.jpg",
            "image_credit": f"{w} · Lago di Braies",
            "practical_details": {
                "parking": "호수 인근 주차장은 **매우 혼잡**. 이른 아침 도착 또는 지정 셔틀·버스 이용 권장. 주차 요금은 시간제 € 수준(현지 표지).",
                "cable_car_lift": "",
                "walking_hiking": "호수 둘레 산책 약 1~1.5시간(평탄, 사진·휴식 제외).",
                "fees_other": "보트 렌탈·일부 구간 입장료가 별도일 수 있음.",
                "reservation_note": "성수기 보트·주차는 예약 또는 시간 제한이 붙는 경우가 있음.",
                "tips": "일출·일몰 시간대 인파—안전·환경 규칙 준수.",
            },
        },
        {
            "name": "Val di Funes (푸네스 계곡)",
            "category": "전망·드라이브",
            "description": "산타 마달레나 교회 등으로 유명한 사진 명소가 많은 계곡.",
            "image_url": "",
            "image_credit": "",
            "practical_details": {
                "parking": "뷰포인트·교회 인근 유료·시간제 주차. 성수기 혼잡.",
                "cable_car_lift": "",
                "walking_hiking": "교회·전망 포인트까지 짧은 산책 20~60분 코스 여러 개.",
                "fees_other": "일부 사진 스팟은 사유지·입장 안내 준수.",
                "reservation_note": "특별 행사 시 도로 통제 가능.",
                "tips": "이른 시간 방문 권장, 망원 렌즈·삼각대 예절.",
            },
        },
        {
            "name": "Cortina d'Ampezzo & Passo Giau",
            "category": "드라이브·전망",
            "description": "코티나 주변 고개와 전망 도로. 겨울 스키·여름 드라이브 모두 인기.",
            "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3a/Cortina_d%27Ampezzo_view.jpg/800px-Cortina_d%27Ampezzo_view.jpg",
            "image_credit": f"{w} · Cortina",
            "practical_details": {
                "parking": "코티나 시내·고개 주차장 유료. 겨울·성수기 포화.",
                "cable_car_lift": "스키 시즌 리프트 요금 별도(여름 패스와 상이).",
                "walking_hiking": "고개 주변 짧은 전망 산책 30분~2시간.",
                "fees_other": "톨·환경 통행 제한 구간 확인.",
                "reservation_note": "대회·이벤트 시 교통 통제.",
                "tips": "고산 날씨·눈길 대비.",
            },
        },
        {
            "name": "Lago di Misurina",
            "category": "호수",
            "description": "트레 치메 근처 고산 호수. 산책과 카페가 있는 휴식 지점.",
            "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/2/2f/Misurina_2007.jpg/800px-Misurina_2007.jpg",
            "image_credit": f"{w} · Misurina",
            "practical_details": {
                "parking": "호수 주변 유료 주차(시간·일당).",
                "cable_car_lift": "",
                "walking_hiking": "둘레 산책 30분~1시간.",
                "fees_other": "인근 리조트 이용 시 주차 혜택 가능.",
                "reservation_note": "성수기 주차 대기 가능.",
                "tips": "트레 치메 일정과 묶기 좋음.",
            },
        },
        {
            "name": "Cadini di Misurina 전망 포인트",
            "category": "짧은 하이킹",
            "description": "짧은 오르막 후 드라마틱한 봉우리 전망을 보는 인기 포인트.",
            "image_url": "",
            "image_credit": "",
            "practical_details": {
                "parking": "미수리나 또는 근처 주차 후 도보 접근.",
                "cable_car_lift": "",
                "walking_hiking": "왕복 1~2시간(길·날씨에 따라 상이), 난이도 중간.",
                "fees_other": "일부 구간 입장 제한 가능.",
                "reservation_note": "위험 구간 표지 준수.",
                "tips": "등산화 권장, 날씨 악화 시 중단.",
            },
        },
        {
            "name": "Ortisei 마을 산책",
            "category": "마을·문화",
            "description": "목조 장식과 숍·레스토랑이 있는 발가르데나 계곡 거점 마을.",
            "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/5/5e/Ortisei_St_Ulrich.jpg/800px-Ortisei_St_Ulrich.jpg",
            "image_credit": f"{w} · Ortisei",
            "practical_details": {
                "parking": "시내 유료 주차장 다수, 시간제.",
                "cable_car_lift": "Seceda 등 리프트는 별도.",
                "walking_hiking": "마을 중심 산책 1~2시간.",
                "fees_other": "박물관·교회 입장료 선택.",
                "reservation_note": "숙소 주차 문의.",
                "tips": "저녁 식사 예약 권장(성수기).",
            },
        },
        {
            "name": "Bolzano (볼차노) 시내",
            "category": "도시",
            "description": "남티롤의 중심 도시. Ötzi 박물관·시장·카페.",
            "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/0/0e/Bolzano_panorama.jpg/800px-Bolzano_panorama.jpg",
            "image_credit": f"{w} · Bolzano",
            "practical_details": {
                "parking": "시내 지하·외곽 유료 주차, ZTL(차량 제한 구역) 주의.",
                "cable_car_lift": "",
                "walking_hiking": "구시가지 산책 반나절.",
                "fees_other": "박물관 입장료.",
                "reservation_note": "인기 박물관 사전 예약.",
                "tips": "대중교통·도보 병행.",
            },
        },
        {
            "name": "Castelrotto (Kastelruth) & 알프 분위기 마을",
            "category": "마을",
            "description": "알페 디 시우시 접근 거점 마을 중 하나.",
            "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a1/Kastelruth_-_panoramio.jpg/800px-Kastelruth_-_panoramio.jpg",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "마을 외곽 주차 후 버스.",
                "cable_car_lift": "Alpe 연결 셔틀·리프트와 연계.",
                "walking_hiking": "마을·교회 주변 1시간 내외.",
                "fees_other": "셔틀 요금.",
                "reservation_note": "숙소별 셔틀 정보 확인.",
                "tips": "시장일·축제 캘린더 확인.",
            },
        },
        {
            "name": "Lago di Carezza (Karersee)",
            "category": "호수",
            "description": "에메랄드 물과 라티마르 봉우리 배경의 짧은 산책 코스.",
            "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/7/7d/Karersee_01.jpg/800px-Karersee_01.jpg",
            "image_credit": f"{w} · Karersee",
            "practical_details": {
                "parking": "호수 인근 유료 주차, 짧은 체류.",
                "cable_car_lift": "",
                "walking_hiking": "둘레 산책 20~40분.",
                "fees_other": "보호 구역 규칙 준수.",
                "reservation_note": "성수기 주차 제한.",
                "tips": "일출 시간 인기.",
            },
        },
        {
            "name": "Passo Gardena & 그란 라세타",
            "category": "고개·드라이브",
            "description": "Sella 루프와 연결되는 고개 드라이브·전망.",
            "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/2/2b/Passo_Gardena.jpg/800px-Passo_Gardena.jpg",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "고개 정상 인근 유료·시간 제한.",
                "cable_car_lift": "겨울 스키 리프트 별도.",
                "walking_hiking": "짧은 전망 산책 30분~1시간.",
                "fees_other": "톨·겨울 장비 의무.",
                "reservation_note": "눈길 통제.",
                "tips": "날씨·도로 상황 실시간 확인.",
            },
        },
        {
            "name": "Canazei & Fassa 계곡",
            "category": "베이스 타운",
            "description": "셀라 루프·마무올 주변 등산·스키 거점.",
            "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/f/f0/Canazei.jpg/800px-Canazei.jpg",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "리조트 주차·숙소 연계.",
                "cable_car_lift": "스키/하이킹 리프트 패스.",
                "walking_hiking": "계곡 트레일 다양.",
                "fees_other": "멀티데이 패스.",
                "reservation_note": "성수기 리프트 예약.",
                "tips": "트레 치메·펠레 그룹 일정과 동선 연계.",
            },
        },
        {
            "name": "Marmolada 그룹 (펠레 지역)",
            "category": "케이블카·빙하",
            "description": "이탈리아 최고봉 일대 빙하·전망(리프트 이용).",
            "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/8/8d/Marmolada_from_Canazei.jpg/800px-Marmolada_from_Canazei.jpg",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "케이블카역 주차 유료.",
                "cable_car_lift": "빙하 지대까지 복수 구간, 성인 왕복 수십 유로대(시즌별).",
                "walking_hiking": "정상부 짧은 산책 + 리프트 이동.",
                "fees_other": "고도·날씨로 운휴 가능.",
                "reservation_note": "운행 시간·기상 확인.",
                "tips": "추위·자외선 대비.",
            },
        },
        {
            "name": "Sass Pordoi",
            "category": "케이블카·전망",
            "description": "케이블카로 2,900m 이상 고도에 쉽게 오를 수 있는 돌로미티 테라스.",
            "image_url": "",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "Passo Pordoi 주차장 (유료).",
                "cable_car_lift": "Passo Pordoi 패소 케이블카로 2,950m 부근 전망대까지, 성인 왕복 수십 €대(시즌·요금제 변동).",
                "walking_hiking": "전망대 주변 짧은 산책.",
                "fees_other": "고산 지대 방한 의복 필수.",
            },
        },
        {
            "name": "Cinque Torri",
            "category": "하이킹",
            "description": "5개의 거대한 바위 탑이 장관을 이루는 명소.",
            "image_url": "",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "Bai de Dones 리프트 주차장.",
                "cable_car_lift": "Bai de Dones 곤돌라·리프트로 접근, 상·하행 편도 €대(시즌별).",
                "walking_hiking": "타워 주변을 도는 왕복 1-2시간 코스.",
                "tips": "스코이아톨리 산장 배경 사진이 유명합니다.",
            },
        },
        {
            "name": "Passo Sella",
            "category": "드라이브·고개",
            "description": "사솔룬고 바위산을 아주 가까이서 볼 수 있는 환상적인 산악 도로.",
            "image_url": "",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "고개 주변 유료 주차 구간.",
                "walking_hiking": "주변에 다양한 트레일 코스 존재.",
                "tips": "자전거 통행이 많아 운전 시 주의 필요.",
            },
        },
        {
            "name": "Lago di Sorapis",
            "category": "호수·하이킹",
            "description": "우유색 에메랄드 물빛으로 유명한 신비로운 고산 호수.",
            "image_url": "",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "Passo Tre Croci 갓길 주차 (매우 혼잡).",
                "cable_car_lift": "",
                "walking_hiking": "왕복 4~5시간, 철제 사다리 및 절벽 구간 있어 주의.",
                "tips": "물과 행동식 충분히 지참, 비가 온 후에는 미끄러움.",
            },
        },
        {
            "name": "Rifugio Lagazuoi",
            "category": "산장·전망",
            "description": "세계대전 벙커 터와 최고의 파노라마 전망을 자랑하는 고산 산장.",
            "image_url": "",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "Passo Falzarego 리프트 역 주차장.",
                "cable_car_lift": "파소 팔차레고에서 케이블카 이용 가능.",
                "walking_hiking": "세계대전 터널을 통한 도보 하산/등산 가능(라이트 장비 필수).",
            },
        },
        {
            "name": "Catinaccio (Rosengarten)",
            "category": "하이킹",
            "description": "석양을 받으면 장미빛으로 붉게 물드는 기암 괴석 산군.",
            "image_url": "",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "Vigo di Fassa 또는 Carezza 주변의 리프트 주차장.",
                "cable_car_lift": "여름 시즌 리프트 이용 확인.",
                "tips": "Enrosadira(장미빛 석양) 시간대 방문 권장.",
            },
        },
        {
            "name": "Sassolungo (Langkofel)",
            "category": "산악경관",
            "description": "발가르데나와 발디파사 사이에 우뚝 솟은 거대한 바위산.",
            "image_url": "",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "Passo Sella 구간 리프트 터미널.",
                "cable_car_lift": "곤돌라 운행.",
                "walking_hiking": "산 주위를 크게 도는 종주 트레킹 4-6시간.",
            },
        },
        {
            "name": "Passo delle Erbe (Würzjoch)",
            "category": "전망·드라이브",
            "description": "Sass de Putia (Peitlerkofel)의 웅장한 북벽을 볼 수 있는 조용한 고개.",
            "image_url": "",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "고개 정상 유료 주차.",
                "walking_hiking": "산봉우리를 도는 3-4시간 둘레길 추천.",
                "tips": "중심부보다 비교적 인적이 드물어 평화로움.",
            },
        },
        {
            "name": "Lago di Dobbiaco (Toblacher See)",
            "category": "호수",
            "description": "잔잔한 숲속 호수와 오리배, 편안한 산책로.",
            "image_url": "",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "호수 주변 주차.",
                "walking_hiking": "호수 도는 데 40분 정도 평지길.",
                "tips": "브라이에스 호수가 붐빌 때 좋은 차선책.",
            },
        },
        {
            "name": "Lago di Landro (Dürrensee)",
            "category": "호수",
            "description": "트레치메를 멀리서 조망할 수 있는 또 다른 조용한 호수.",
            "image_url": "",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "호수 바로 옆 무료/갓길 주차.",
                "tips": "석양 시간대 봉우리가 붉게 물드는 뷰 포인트.",
            },
        },
        {
            "name": "Santa Maddalena 교회 (Val di Funes)",
            "category": "포토스팟·마을",
            "description": "푸네스 계곡을 상징하는 작은 성당과 뒤로 펼쳐지는 가이스들러 산맥의 완벽한 엽서 구도.",
            "image_url": "",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "마을 공영 주차장 (유료).",
                "walking_hiking": "주차장에서 뷰포인트까지 도보 약 20분 오르막.",
                "tips": "오후 늦은 시간이나 석양 때 산맥에 빛이 들어옵니다.",
            },
        },
        {
            "name": "Tofana di Mezzo (Freccia nel Cielo)",
            "category": "케이블카·고산",
            "description": "코르티나 담페초에서 가장 높은 고도(3,244m)까지 올라가는 짜릿한 케이블카.",
            "image_url": "",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "코르티나 담페초 올림픽 빙상 경기장 인근 케이블카역 주차장.",
                "cable_car_lift": "3단계 연장 운행 여부 필수 확인.",
                "tips": "한여름에도 정상은 매우 추울 수 있으므로 두꺼운 외투 필수.",
            },
        },
        {
            "name": "Col Raiser",
            "category": "케이블카·하이킹",
            "description": "오데를 산군과 푸에즈 고원을 병풍처럼 둘러볼 수 있는 넓은 초원 지대.",
            "image_url": "",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "산타 크리스티나(St. Cristina) 케이블카 역 하단 유료 주차.",
                "cable_car_lift": "왕복 곤돌라 운행.",
                "walking_hiking": "Seceda로 넘어가는 트래킹 루트가 유명합니다.",
            },
        },
        {
            "name": "Bressanone (Brixen)",
            "category": "주변 도시",
            "description": "아름다운 돔 광장과 중세풍 골목, 화려한 벽화가 눈길을 끄는 주교 도시.",
            "image_url": "",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "구시가지 외곽 공영 주차 타워 이용 추천.",
                "walking_hiking": "평지 위주의 편안한 시내 산책 2~3시간.",
                "tips": "돌로미티 서쪽 코스를 짤 때 숙박이나 점심 식사로 훌륭한 기점.",
            },
        },
        {
            "name": "Brunico (Bruneck)",
            "category": "주변 도시",
            "description": "무지카 산맥 입구에 있는 활기찬 도시, 브루니코 성과 메스너 산악 박물관 소재지.",
            "image_url": "",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "시내 곳곳의 공영 주차장.",
                "fees_other": "메스너 산악 박물관 RIPA 입장료 별도.",
                "tips": "아기자기한 구시가지 쇼핑과 산책이 매력적임.",
            },
        },
        {
            "name": "Merano (Meran)",
            "category": "주변 도시·온천",
            "description": "알프스의 지중해라 불리는 우아한 온천 휴양 도시, 트라우트만스도르프 정원.",
            "image_url": "",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "시내 온천 주차장 및 정원 전용 주차장.",
                "fees_other": "테르메(온천) 및 정원 입장료 별도.",
                "tips": "여행 후반부 피로를 풀기에 완벽한 럭셔리 온천 도시.",
            },
        },
        {
            "name": "Trento (트렌토)",
            "category": "주변 도시",
            "description": "이탈리아 르네상스의 흔적이 짙게 남은 트렌티노 주의 중심 도시, 부온콘실리오 성.",
            "image_url": "",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "시내 ZTL(차량진입제한) 구역 주의, 플라차 주차장 추천.",
                "tips": "가르다 호수로 넘어가는 길목에 들르기 좋습니다.",
            },
        },
        {
            "name": "Belluno (벨루노)",
            "category": "주변 도시",
            "description": "피아베 강이 흐르고 남쪽 돌로미티를 병풍처럼 두른 조용하고 매력적인 소도시.",
            "image_url": "",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "에스컬레이터로 연결되는 무료/유료 대형 주차장 이용.",
                "tips": "돌로미티의 남쪽 관문 명성을 지니고 있어 베네치아로 가는 길목에 알맞음.",
            },
        },
        {
            "name": "Chiusa (Klausen)",
            "category": "주변 소도시",
            "description": "강변을 따라 형성된 좁고 긴 아기자기한 중세풍 골목의 아름다운 마을.",
            "image_url": "",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "구시가지 북/남쪽 주차장 이용.",
                "walking_hiking": "가파른 돌계단을 올라 사비오나 수도원까지 도보 30-40분 산책 가능.",
                "tips": "A22 고속도로에서 바로 진입 가능해 접근성이 뛰어남.",
            },
        },
        {
            "name": "Passo Falzarego",
            "category": "고개·전망",
            "description": "라가주오이와 친퀘토리를 잇는 돌로미티 교통의 핵심 고개이자 전망 포인트.",
            "image_url": "",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "고개 정상 주차장 (성수기 매우 혼잡).",
                "tips": "코르티나 담페초에서 알타 바디아로 넘어갈 때 지나가는 환상적인 드라이브 코스.",
            },
        },
        {
            "name": "Lago di Fedaia",
            "category": "호수·드라이브",
            "description": "마르몰라다 빙하 바로 아래 눈부신 절경을 자랑하는 인공 호수 댐.",
            "image_url": "",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "호수 댐 양 끝 무료/유료 주차 공간.",
                "tips": "바람이 불지 않을 때 호수에 비치는 마르몰라다 산군이 장관.",
            },
        },
        {
            "name": "Lago di Alleghe",
            "category": "호수·마을",
            "description": "치베타(Civetta) 산군의 산사태로 형성된 짙푸른 호반과 평화로운 마을.",
            "image_url": "",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "알레게 마을 진입로 및 곤돌라 역 주차장.",
                "walking_hiking": "호수 둘레를 한 바퀴 도는 평탄한 산책가 매우 인기 (약 2시간).",
            },
        },
        {
            "name": "Monte Elmo (Helm)",
            "category": "케이블카·전망",
            "description": "오스트리아 국경과 가까운 산칸디도 윗자락의 훌륭한 드라이 진넨(북쪽) 조망대.",
            "image_url": "",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "발푸스테리아(Versciaco/Vierschach) 곤돌라 승강장.",
                "cable_car_lift": "가족 친화적인 곤돌라 탑승.",
                "tips": "오를리 스톤(Olperl's) 가족 산책 테마파크가 있어 아이와 함께 가기 좋음.",
            },
        },
        {
            "name": "San Candido (Innichen)",
            "category": "주변 소도시",
            "description": "볼거리와 쇼핑, 먹거리가 풍성한 남티롤 동부 트라이 진넨 지역 중심 마을.",
            "image_url": "",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "마을 중심 외곽 곳곳에 유료 주차기 편비.",
                "tips": "자전거 대여소가 많으며 드라바 강 자전거 길의 출발점으로 인기가 높습니다.",
            },
        },
        {
            "name": "Val Fiscalina (Fischleintal)",
            "category": "하이킹·자연",
            "description": "세계에서 가장 아름다운 골짜기 중 하나로 불리는 웅장한 바위산의 좁은 계곡.",
            "image_url": "",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "계곡 입구 유료 주차장 (조기 만차 잦음).",
                "walking_hiking": "평탄하고 걷기 쉬운 길을 따라 Talschlusshütte 산장까지 약 1시간.",
                "tips": "트레 치메를 밑에서 올려다보는 환상적인 뷰포인트를 제공합니다.",
            },
        },
        {
            "name": "Corvara in Badia",
            "category": "베이스 타운",
            "description": "알타 바디아(Alta Badia) 지역의 거점으로 고급 리조트와 맛집이 몰려 있는 세련된 마을.",
            "image_url": "",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "각 숙소 및 시내 공영 주차.",
                "cable_car_lift": "보에(Boe) 케이블카, 콜알토(Col Alto) 등 주요 리프트 집결지.",
                "tips": "셀라 론다(Sella Ronda) 스키 및 사이클링의 거점 역할을 합니다.",
            },
        },
    ]
    return result


def _generic_spot(destination: str, i: int) -> dict[str, Any]:
    """목적지 일반: 구체적 이름 대신 실무 항목을 채운 예시 카드. 사진은 enrich에서만 붙이거나 비움."""
    return {
        "name": f"{destination} 주변 추천 스팟 {i + 1}",
        "category": ["전망", "마을", "호수", "하이킹", "박물관"][i % 5],
        "description": f"{destination}에서 이동 시간과 체력에 맞춰 고를 수 있는 후보입니다. 실제 명칭·요금은 최신 가이드와 지도로 확인하세요.",
        "image_url": "",
        "image_credit": "",
        "practical_details": {
            "parking": "",
            "cable_car_lift": "",
            "walking_hiking": "",
            "fees_other": "",
            "reservation_note": "",
            "tips": "물·방풍·막바람에 대비. 일몰 전 하산 및 혼잡도 회피 계획.",
        },
    }


def _build_mock_attraction_list(destination: str, n: int) -> list[dict[str, Any]]:
    if _looks_like_dolomites(destination):
        pool = _dolomites_attraction_templates()
    else:
        pool = [_generic_spot(destination, j) for j in range(max(n, 12))]
    out: list[dict[str, Any]] = []
    for i in range(n):
        base = dict(pool[i % len(pool)])
        base["id"] = f"attr_{i + 1:03d}"
        if _looks_like_dolomites(destination) and i >= len(pool):
            base["name"] = base.get("name", "") + f" (코스 변형 {i // len(pool) + 1})"
        out.append(_ensure_attraction_record(base, i, destination))
    return out


def _extract_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    t = text.strip()
    if "```" in t:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", t)
        if m:
            t = m.group(1).strip()
    start = t.find("{")
    end = t.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(t[start : end + 1])
    except json.JSONDecodeError:
        return None


def _mock_attractions(destination: str, trip_days: int, preference: dict) -> dict[str, Any]:
    n = _attraction_target_count(trip_days)
    attractions = _build_mock_attraction_list(destination, n)
    return {
        "itinerary_step": "select_attractions",
        "trip_days": trip_days,
        "time_ratio_note": (
            "이상적인 여행에서는 공항↔목적지 이동과 목적지 체류 시간 비율이 대략 4:1이 되도록 "
            "이동·관광을 배분하는 것을 권장합니다. 실제 항공·도로 상황에 맞게 조정하세요."
        ),
        "attractions": attractions,
        "design_notes": (
            f"{destination} 일정: 각 후보는 실제 방문지 이름·사진·주차·리프트·도보 시간 등을 함께 제시합니다. "
            "표시된 요금(€ 등)은 참고용이며 연도·시즌·환율에 따라 달라지므로 출발 전 공식 사이트로 반드시 확인하세요. "
            "오전·오후로 하루 약 두 곳을 기준으로 고르고, 숙소에서 차로 1시간을 넘기면 동선상 숙소 이동을 검토하되 한 거점 유지를 우선하세요."
        ),
    }


def _mock_route_and_restaurants(
    destination: str,
    trip_days: int,
    dates: list[str],
    selected: list[dict[str, Any]],
    preference: dict,
) -> dict[str, Any]:
    ids = [a["id"] for a in selected]
    daily_schedule = []
    for i, d in enumerate(dates):
        am = ids[(i * 2) % len(ids)] if ids else "attr_001"
        pm = ids[(i * 2 + 1) % len(ids)] if len(ids) > 1 else am
        daily_schedule.append(
            {
                "date": d,
                "morning_attraction_id": am,
                "afternoon_attraction_id": pm,
                "overnight_area_hint": f"{destination} 중심부 또는 인접 동네",
            }
        )
    restaurants_by_attraction: dict[str, list[dict[str, Any]]] = {}
    for a in selected:
        aid = a["id"]
        restaurants_by_attraction[aid] = [
            {
                "id": f"{aid}_r1",
                "name": f"{a['name']} 근처 맛집 A",
                "rating": 4.6,
                "description": "현지인 단골, 점심·저녁 모두 가능.",
            },
            {
                "id": f"{aid}_r2",
                "name": f"{a['name']} 근처 맛집 B",
                "rating": 4.4,
                "description": "평점 좋은 브런치·라이트 저녁.",
            },
            {
                "id": f"{aid}_r3",
                "name": f"{a['name']} 근처 맛집 C",
                "rating": 4.2,
                "description": "가성비 좋은 현지 요리.",
            },
        ]
    return {
        "itinerary_step": "select_meals",
        "route_plan": {
            "destination_base_days": dates,
            "transit_legs": [
                {
                    "leg": "outbound",
                    "notes": "공항에서 목적지로 이동하는 동선에 볼거리가 있으면 하루 묵고 가는 형태로 넣을 수 있습니다.",
                    "suggested_overnight": None,
                    "sights_along_route": [],
                },
                {
                    "leg": "return",
                    "notes": "귀국 시에도 중간 도시에 중요한 관광지가 있으면 경유·숙박을 고려하세요.",
                    "suggested_overnight": None,
                    "sights_along_route": [],
                },
            ],
            "daily_schedule": daily_schedule,
            "lodging_strategy": (
                "가능하면 목적지 주변 한 거점에 머물고, 차로 1시간 초과 구간이 반복되면 동네 이동을 검토합니다."
            ),
        },
        "neighborhoods": [
            {
                "area_id": "nb_1",
                "name": f"{destination} 시내·중심가",
                "description": "교통·식사 접근성이 좋고 주요 명소와의 이동이 수월한 동네입니다.",
                "reachable_attraction_ids": ids[: min(8, len(ids))],
                "lodging_notes": "첫 숙박 후보로 적합합니다.",
            },
            {
                "area_id": "nb_2",
                "name": f"{destination} 인근 조용한 주거·관광지 일대",
                "description": "붐비는 시내를 피하고 싶을 때, 렌트 이용 시 주차 여유가 있는 편입니다.",
                "reachable_attraction_ids": ids[min(4, len(ids) - 1) :] if len(ids) > 4 else ids,
                "lodging_notes": "장기 체류·가족 여행에 맞출 수 있습니다.",
            },
        ],
        "restaurants_by_attraction": restaurants_by_attraction,
        "trip_dates": dates,
    }


def _normalize_attraction_key(name: str) -> str:
    """괄호 별칭 제거 후 정규화 — 'Tre Cime … (Drei Zinnen)' vs 'Tre Cime …' 중복 병합용."""
    s = name or ""
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"（[^）]*）", "", s)
    s = s.lower()
    s = re.sub(r"[\s\(\)\[\]'\"`·\-_,./]+", "", s)
    return s


def _tokens_for_overlap(s: str) -> list[str]:
    s = re.sub(r"[^\w\s가-힣]", " ", (s or "").lower())
    return [w for w in s.split() if len(w) >= 3]


def _names_likely_same(a: str, b: str) -> bool:
    """템플릿·구글 결과 중복 병합용(완전 일치에 가까운 수준)."""
    na, nb = _normalize_attraction_key(a), _normalize_attraction_key(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if len(na) >= 8 and (na in nb or nb in na):
        return True
    ta, tb = set(_tokens_for_overlap(a)), set(_tokens_for_overlap(b))
    if not ta or not tb:
        return False
    inter = ta.intersection(tb)
    return len(inter) >= 2 and len(inter) >= min(len(ta), len(tb)) * 0.5


def _google_attraction_score(row: dict[str, Any]) -> float:
    """구글 후보 정렬·낮은 점수 슬롯 교체용(평점·리뷰 수 반영)."""
    r = float(row.get("rating") or 0.0)
    rev = int(row.get("user_ratings_total") or 0)
    return r * (1.0 + (max(rev, 0) ** 0.5) / 40.0)


def _region_curated_attraction_templates(destination: str) -> list[dict[str, Any]]:
    """목적지별 큐레이션 오프라인 풀(있을 때만). 검색어가 아니라 병합·보충용."""
    if _looks_like_dolomites(destination):
        return _dolomites_attraction_templates()
    return []


def _merge_google_with_region_templates(
    google_list: list[dict[str, Any]],
    destination: str,
    n_attr: int,
) -> list[dict[str, Any]]:
    """구글 Places 후보를 평점·리뷰 기준으로 우선하되, 큐레이션 풀이 있으면
    상한만 채워진 경우에도 풀에만 있는 대표 랜드마크가 빠지지 않게 낮은 점수 후보와 교체한다."""
    pool = _region_curated_attraction_templates(destination)
    generic_pool = [_generic_spot(destination, j) for j in range(max(n_attr, 12))]
    merged: list[dict[str, Any]] = []
    existing: set[str] = set()

    def _append_candidate(row: dict[str, Any]) -> None:
        if len(merged) >= n_attr:
            return
        tn = (row.get("name") or "").strip()
        if not tn:
            return
        nk = _normalize_attraction_key(tn)
        if nk in existing:
            return
        if any(_names_likely_same(tn, g.get("name", "")) for g in merged):
            return
        existing.add(nk)
        item = dict(row)
        item["id"] = f"attr_{len(merged) + 1:03d}"
        merged.append(item)

    g_sorted = sorted(google_list, key=_google_attraction_score, reverse=True)

    if len(g_sorted) >= n_attr:
        if pool:
            missing: list[dict[str, Any]] = []
            for t in pool:
                tn = (t.get("name") or "").strip()
                if not tn:
                    continue
                if any(_names_likely_same(tn, x.get("name", "")) for x in g_sorted):
                    continue
                missing.append(dict(t))
            k_max = min(len(missing), max(2, min(8, n_attr // 4)))
            if k_max > 0:
                base = [dict(x) for x in g_sorted[:n_attr]]
                worst_idx = sorted(
                    range(n_attr),
                    key=lambda i: _google_attraction_score(base[i]),
                )[:k_max]
                for j, wi in enumerate(worst_idx):
                    if j < len(missing):
                        base[wi] = dict(missing[j])
                for i, row in enumerate(base):
                    row["id"] = f"attr_{i + 1:03d}"
                    merged.append(row)
                return merged[:n_attr]
        for g in g_sorted[:n_attr]:
            _append_candidate(g)
        return merged[:n_attr]

    for g in g_sorted:
        _append_candidate(g)
        if len(merged) >= n_attr:
            return merged[:n_attr]

    fill_pool = pool if pool else generic_pool
    for t in fill_pool:
        if len(merged) >= n_attr:
            break
        tn = t.get("name") or ""
        nk = _normalize_attraction_key(tn)
        if nk in existing:
            continue
        if any(_names_likely_same(tn, g.get("name", "")) for g in merged):
            continue
        existing.add(nk)
        item = dict(t)
        item["id"] = f"attr_{len(merged) + 1:03d}"
        merged.append(item)
    gi = 0
    while len(merged) < n_attr and pool:
        base = dict(pool[gi % len(pool)])
        suf = gi // len(pool) + 1
        base["name"] = (base.get("name") or "") + (f" · 동선 {suf}" if suf > 1 else "")
        nk = _normalize_attraction_key(base["name"])
        if nk not in existing:
            existing.add(nk)
            base["id"] = f"attr_{len(merged) + 1:03d}"
            merged.append(base)
        gi += 1
        if gi > len(pool) * 5:
            break
    # 큐레이션 풀만으로 상한 미달 시 일반 템플릿으로 반드시 채움(구글 후보가 40개 등으로 짧을 때).
    gix = 0
    while len(merged) < n_attr and gix < n_attr * 4:
        base = _generic_spot(destination, gix)
        gix += 1
        tn = (base.get("name") or "").strip()
        nk = _normalize_attraction_key(tn)
        if not nk or nk in existing:
            continue
        if any(_names_likely_same(tn, (g.get("name") or "").strip()) for g in merged):
            continue
        existing.add(nk)
        base["id"] = f"attr_{len(merged) + 1:03d}"
        merged.append(_ensure_attraction_record(base, len(merged), destination))
    return merged[:n_attr]


def _place_itinerary_rank_key(p: dict[str, Any]) -> tuple[int, float, int]:
    """Places 후보 정렬: 4.3+ 품질 통과(0) → 4.0대 → 3.5대 → 3.0대 → 2.5대(최후). 낮은 튜플이 우선."""
    r = float(p.get("rating") or 0.0)
    rev = int(p.get("user_ratings_total") or 0)
    if r < 2.5:
        return (99, 0.0, 0)
    if r >= 4.3 and _place_passes_quality_filter(p, 4.3):
        return (0, -r, -rev)
    if r >= 4.0:
        return (1, -r, -rev)
    if r >= 3.5:
        return (2, -r, -rev) if rev >= 2 else (99, 0.0, 0)
    if r >= 3.0:
        return (3, -r, -rev) if rev >= 3 else (99, 0.0, 0)
    return (4, -r, -rev) if rev >= 8 else (99, 0.0, 0)


def _fill_attraction_catalog_to_count(
    current: list[dict[str, Any]],
    n_target: int,
    merged_pre_llm: list[dict[str, Any]] | None,
    destination: str,
) -> list[dict[str, Any]]:
    """일수×3개가 되도록 merged_pre_llm(구글·템플릿)에서 부족분을 평점 순으로 채운다."""
    if n_target <= 0:
        return current
    out = [dict(x) for x in current if isinstance(x, dict)]
    if len(out) >= n_target:
        return out[:n_target]

    def _sort_key(row: dict[str, Any]) -> tuple[float, int]:
        r = float(row.get("rating") or 0.0)
        rev = int(row.get("user_ratings_total") or 0)
        return (-r, -rev)

    seen: set[str] = set()
    for a in out:
        nk = _normalize_attraction_key((a.get("name") or "").strip())
        if nk:
            seen.add(nk)

    pool = sorted(
        [dict(x) for x in (merged_pre_llm or []) if isinstance(x, dict)],
        key=_sort_key,
    )
    for row in pool:
        if len(out) >= n_target:
            break
        nm = (row.get("name") or "").strip()
        nk = _normalize_attraction_key(nm)
        if not nk or nk in seen:
            continue
        if any(_names_likely_same(nm, (o.get("name") or "").strip()) for o in out):
            continue
        seen.add(nk)
        copy = dict(row)
        copy["id"] = f"attr_{len(out) + 1:03d}"
        out.append(_ensure_attraction_record(copy, len(out), destination))

    gi = 0
    while len(out) < n_target:
        base = _generic_spot(destination, gi)
        gi += 1
        nm = (base.get("name") or "").strip()
        nk = _normalize_attraction_key(nm)
        if nk in seen:
            base["name"] = (base.get("name") or "") + f" · 보충 {gi}"
            nk = _normalize_attraction_key(base["name"])
        seen.add(nk)
        base["id"] = f"attr_{len(out) + 1:03d}"
        out.append(_ensure_attraction_record(base, len(out), destination))
        if gi > n_target * 3:
            logger.warning("명소 목표 %d개 채우기에 제한 초과 — %d개에서 중단", n_target, len(out))
            break
    return out


def _place_passes_quality_filter(p: dict[str, Any], min_rating: float) -> bool:
    """전역: 케이블카·전망·자연 등 고평점·대표 관광지가 리뷰 수만 적다고 제외되지 않게 완화."""
    rating = float(p.get("rating") or 0.0)
    reviews = int(p.get("user_ratings_total") or 0)
    if rating < min_rating:
        return False
    ptypes = set(p.get("types") or [])
    nature = ptypes.intersection({"natural_feature", "park", "campground"})
    scenic = ptypes.intersection({"tourist_attraction", "point_of_interest"})
    if nature:
        return reviews >= 10 or (rating >= 4.5 and reviews >= 6)
    if scenic:
        return reviews >= 14 or (rating >= 4.5 and reviews >= 8)
    return reviews >= 20


def _match_google_attraction_row(name: str, catalog: list[dict[str, Any]]) -> dict[str, Any] | None:
    """LLM이 약간 바꾼 명소명도 구글 메타(place_id·사진)와 연결."""
    if not catalog:
        return None
    nl = (name or "").strip()
    if not nl:
        return None
    for gs in catalog:
        gn = (gs.get("name") or "").strip()
        if not gn:
            continue
        if nl.lower() == gn.lower():
            return gs
        if nl.lower() in gn.lower() or gn.lower() in nl.lower():
            return gs
        if _names_likely_same(nl, gn):
            return gs
    return None


def _filter_llm_attractions_require_indoor_details(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """박물관·공연장 등 내부 관람형인데 입장 정보가 비면 제외."""
    indoor_cats = ("박물관", "미술관", "공연", "오페라", "극장", "스칼라", "museum", "theater", "opera")
    out: list[dict[str, Any]] = []
    for a in items:
        if not isinstance(a, dict):
            continue
        cat = (a.get("category") or "") + " " + (a.get("name") or "")
        cat_l = cat.lower()
        if not any(k in cat_l for k in indoor_cats):
            out.append(a)
            continue
        pr = _merge_practical_details(a.get("practical_details"))
        fees = (pr.get("fees_other") or "").strip()
        resv = (pr.get("reservation_note") or "").strip()
        if len(fees) < 8 and len(resv) < 8:
            continue
        out.append(a)
    return out


def _resolve_restaurant_name(
    rid: str,
    restaurants_by_attraction: dict[str, list[dict[str, Any]]],
) -> str:
    for _aid, lst in restaurants_by_attraction.items():
        for r in lst:
            if r.get("id") == rid:
                return r.get("name") or rid
    return rid


async def _fetch_top_attractions_from_google(
    origin: str,
    destination: str,
    local_transport: str,
    multi_cities: list,
    api_key: str,
    start_date: str = "",
    end_date: str = "",
    max_count: int = 200,
) -> tuple[list[dict[str, Any]], str | None]:
    """Places Nearby + Text Search로 경로 1 : 목적지 4 비율.
    4.3+ 품질 통과 장소를 우선하되, 상한 채우기에 부족하면 낮은 평점(높은 순)으로 보강한다."""
    import asyncio
    import httpx
    from urllib.parse import urlencode

    dest_places: list[str] = []
    for pt in destination.replace(" 및 ", ",").replace(" 등", "").split(","):
        if pt.strip() and pt.strip() not in dest_places:
            dest_places.append(pt.strip())

    for mc in multi_cities:
        for pt in mc.get("destination", "").replace(" 및 ", ",").split(","):
            if pt.strip() and pt.strip() not in dest_places:
                dest_places.append(pt.strip())

    if not dest_places:
        dest_places = [destination]

    route_points: list[str] = []
    dest_points: list[str] = []
    primary_bias: str | None = None

    async def get_lat_lng(client: httpx.AsyncClient, addr: str) -> str | None:
        try:
            url = "https://maps.googleapis.com/maps/api/geocode/json?" + urlencode(
                {"address": addr, "key": api_key}
            )
            r = await client.get(url, timeout=10)
            if r.status_code == 200:
                results = r.json().get("results", [])
                if results:
                    loc = results[0].get("geometry", {}).get("location", {})
                    lat, lng = loc.get("lat"), loc.get("lng")
                    if lat and lng:
                        return f"{lat},{lng}"
        except Exception:
            pass
        return None

    async def get_route_waypoints(client: httpx.AsyncClient, o: str, d: str) -> list[str]:
        try:
            url = "https://maps.googleapis.com/maps/api/directions/json?" + urlencode(
                {"origin": o, "destination": d, "key": api_key}
            )
            r = await client.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                if data.get("routes"):
                    steps = data["routes"][0]["legs"][0]["steps"]
                    pts = [f"{s['end_location']['lat']},{s['end_location']['lng']}" for s in steps]
                    if len(pts) > 4:
                        indices = [int(i * len(pts) / 4) for i in range(4)]
                        return [pts[i] for i in indices]
                    return pts
        except Exception:
            pass
        return []

    async with httpx.AsyncClient(timeout=15) as client:
        d_locs = await asyncio.gather(*(get_lat_lng(client, p) for p in dest_places))
        for loc in d_locs:
            if loc:
                dest_points.append(loc)
        if dest_points:
            primary_bias = dest_points[0]
        if local_transport == "rental_car" and origin:
            wpts = await get_route_waypoints(client, origin, dest_places[0])
            route_points.extend(wpts)

    if not dest_points:
        return [], None

    route_target = max_count // 5 if route_points else 0
    dest_target = max_count - route_target

    bad_types = {
        "hospital",
        "health",
        "dentist",
        "doctor",
        "lodging",
        "real_estate_agency",
        "travel_agency",
        "gym",
        "spa",
        "hair_care",
        "laundry",
        "car_repair",
        "pharmacy",
        "bank",
        "atm",
        "gas_station",
    }

    type_keyword_pairs = [
        ("tourist_attraction", ""),
        ("tourist_attraction", "hiking"),
        ("tourist_attraction", "trail"),
        ("park", ""),
        ("park", "lake"),
        ("natural_feature", ""),
        ("natural_feature", "viewpoint"),
        ("point_of_interest", "panorama"),
        ("tourist_attraction", "cable car"),
        ("point_of_interest", "funicular"),
        ("tourist_attraction", "gondola"),
    ]
    route_jobs: list[tuple[str, str, str]] = []
    dest_jobs: list[tuple[str, str, str]] = []
    for loc in route_points:
        for typ, kw in type_keyword_pairs[:8]:
            route_jobs.append((loc, typ, kw))
    for loc in dest_points:
        for typ, kw in type_keyword_pairs:
            dest_jobs.append((loc, typ, kw))

    text_queries: list[str] = []
    head = dest_places[0]
    text_queries.extend(
        [
            f"{head} scenic viewpoint",
            f"{head} cable car",
            f"{head} famous lake",
            f"{head} hiking trail",
            f"{head} nature hiking scenic",
            f"{head} tourist viewpoint",
        ]
    )

    async def nearby_one(
        client: httpx.AsyncClient, loc: str, typ: str, kw: str
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {
            "location": loc,
            "radius": "45000",
            "type": typ,
            "key": api_key,
            "language": "en",
        }
        if kw:
            params["keyword"] = kw
        url = "https://maps.googleapis.com/maps/api/place/nearbysearch/json?" + urlencode(params)
        try:
            r = await client.get(url, timeout=15)
            if r.status_code == 200:
                return r.json().get("results", [])
        except Exception:
            pass
        return []

    async def text_search_one(client: httpx.AsyncClient, query: str, loc: str) -> list[dict[str, Any]]:
        params = {
            "query": query,
            "location": loc,
            "radius": "45000",
            "key": api_key,
            "language": "en",
        }
        url = "https://maps.googleapis.com/maps/api/place/textsearch/json?" + urlencode(params)
        try:
            r = await client.get(url, timeout=15)
            if r.status_code == 200:
                return r.json().get("results", [])
        except Exception:
            pass
        return []

    async with httpx.AsyncClient(timeout=25) as client:
        r_tasks = [nearby_one(client, loc, typ, kw) for loc, typ, kw in route_jobs]
        d_tasks = [nearby_one(client, loc, typ, kw) for loc, typ, kw in dest_jobs]
        bias = dest_points[0]
        t_tasks = [text_search_one(client, q, bias) for q in text_queries]
        parts = r_tasks + d_tasks + t_tasks
        gathered = await asyncio.gather(*parts) if parts else []
        nr, nd, nt = len(r_tasks), len(d_tasks), len(t_tasks)
        route_pages = gathered[:nr] if nr else []
        dest_pages = gathered[nr : nr + nd] if nd else []
        text_pages = gathered[nr + nd : nr + nd + nt] if nt else []

    route_res: list[list[dict[str, Any]]] = list(route_pages)
    dest_res: list[list[dict[str, Any]]] = list(dest_pages) + list(text_pages)

    def ingest_pool_tiered(lists: list[list[dict]]) -> list[dict]:
        combined: list[dict] = []
        seen: set[str] = set()
        for lst in lists:
            for p in lst:
                pid = p.get("place_id")
                if not pid or pid in seen:
                    continue
                if _place_itinerary_rank_key(p)[0] >= 99:
                    continue
                ptypes = set(p.get("types", []))
                if ptypes.intersection(bad_types):
                    continue
                if is_guide_or_tour_operator_place(p.get("name"), p.get("types")):
                    continue
                if should_exclude_warm_season_ski_place(
                    p.get("name"),
                    p.get("types"),
                    start_date,
                    end_date or start_date,
                ):
                    continue
                seen.add(pid)
                combined.append(p)
        combined.sort(key=_place_itinerary_rank_key)
        return combined

    pool_route = ingest_pool_tiered(route_res) if route_res else []
    pool_dest = ingest_pool_tiered(dest_res) if dest_res else []

    route_spots = pool_route[:route_target]
    route_ids = {s.get("place_id") for s in route_spots}
    dest_pool = [p for p in pool_dest if p.get("place_id") not in route_ids]
    dest_spots = dest_pool[:dest_target]

    results = route_spots + dest_spots

    out: list[dict[str, Any]] = []
    for i, p in enumerate(results):
        name = p.get("name", f"추천 스팟 {i + 1}")
        address = p.get("formatted_address", "")
        types = p.get("types", [])
        category = "명소"
        if "natural_feature" in types or "park" in types:
            category = "자연·공원"
        elif "museum" in types:
            category = "박물관"
        elif "church" in types or "place_of_worship" in types:
            category = "종교·유적"

        r_val = p.get("rating", 0.0)
        rc_val = p.get("user_ratings_total", 0)
        desc = (
            f"구글맵 기준 평점 {r_val}★(리뷰 약 {rc_val}건), {address or '주소 정보는 현지에서 확인'}. "
            "아래 카드의 본문·실무 정보는 별도로 보강됩니다."
        )

        image_url = ""
        photos = p.get("photos", [])
        if photos:
            pref = photos[0].get("photo_reference")
            if pref:
                image_url = (
                    f"https://maps.googleapis.com/maps/api/place/photo?"
                    f"maxwidth=960&photoreference={pref}&key={api_key}"
                )

        out.append(
            {
                "id": f"attr_{i + 1:03d}",
                "name": name,
                "place_id": p.get("place_id"),
                "category": category,
                "description": desc,
                "image_url": image_url,
                "image_credit": "Google Maps",
                "practical_details": {"tips": ""},
                "types": list(types or []),
                "rating": float(r_val) if r_val is not None else 0.0,
                "user_ratings_total": int(rc_val) if rc_val is not None else 0,
            }
        )

    return out, primary_bias


async def postprocess_attraction_list_for_catalog(
    atts: list[dict[str, Any]],
    *,
    settings: Settings,
    destination: str,
    start_date: str,
    end_date: str,
    merged_pre_llm: list[dict[str, Any]] | None = None,
    location_bias: str | None = None,
    response_out: dict[str, Any] | None = None,
    target_count: int | None = None,
) -> list[dict[str, Any]]:
    """Places 상세 → LLM practical 보강 → 이미지. Session 폴백·Itinerary 본 경로 공통."""
    if not atts:
        if target_count and merged_pre_llm:
            atts = _fill_attraction_catalog_to_count([], target_count, merged_pre_llm, destination)
        elif target_count:
            atts = _fill_attraction_catalog_to_count([], target_count, None, destination)
        if not atts:
            return atts
    for i, a in enumerate(atts):
        if isinstance(a, dict):
            atts[i] = _ensure_attraction_record(a, i, destination)
    atts = filter_attractions_drop_guide_services(atts)
    atts = filter_attractions_warm_season_no_ski(atts, start_date, end_date)
    if not atts:
        if target_count and merged_pre_llm:
            atts = _fill_attraction_catalog_to_count([], target_count, merged_pre_llm, destination)
            atts = filter_attractions_drop_guide_services(atts)
            atts = filter_attractions_warm_season_no_ski(atts, start_date, end_date)
        if not atts:
            logger.warning("명소 후보가 가이드·투어 업체 또는 계절 필터로 모두 제외되었습니다.")
            return []
    if merged_pre_llm:
        for a in atts:
            if not isinstance(a, dict):
                continue
            gs = _match_google_attraction_row(a.get("name") or "", merged_pre_llm)
            if gs:
                if gs.get("place_id"):
                    a["place_id"] = gs.get("place_id")
                if gs.get("image_url"):
                    a["image_url"] = gs.get("image_url")
                    a["image_credit"] = gs.get("image_credit")
                    a["image_source"] = gs.get("image_source")

    if settings.google_places_api_key:
        atts = await enrich_attractions_with_place_details(
            atts,
            settings.google_places_api_key,
            destination,
        )
        atts = filter_attractions_drop_guide_services(atts)
        atts = filter_attractions_warm_season_no_ski(atts, start_date, end_date)
        if not atts:
            logger.warning(
                "Places 상세 후 가이드·투어 또는 계절 필터로 명소가 모두 제외되었습니다."
            )
            return []
    else:
        logger.warning(
            "GOOGLE_PLACES_API_KEY 없음: 명소 주소·Maps 링크 Places 보강 생략(.env / docker-compose)."
        )

    if (settings.openai_api_key or "").strip():
        try:
            from openai import AsyncOpenAI

            pol_client = AsyncOpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
            )
            atts = await polish_practical_details_with_llm(
                atts,
                client=pol_client,
                model=settings.llm_model,
                destination=destination,
                start_date=start_date,
                end_date=end_date,
                serpapi_key=settings.serpapi_api_key or "",
                google_api_key=settings.google_places_api_key or "",
                google_cse_cx=settings.google_cse_cx or "",
            )
        except Exception as e:
            logger.warning(
                "polish_practical_details_with_llm failed (parking·거점 보강 생략): %s",
                e,
            )
    else:
        logger.warning(
            "OPENAI_API_KEY 없음: 거점·parking LLM 보강(polish_practical_details_with_llm)을 실행하지 않습니다. "
            "서버 .env에 설정 후 itinerary 컨테이너 재시작 필요."
        )
        if (settings.serpapi_api_key or "").strip() or (
            (settings.google_cse_cx or "").strip() and (settings.google_places_api_key or "").strip()
        ):
            try:
                from shared.fees_web_search import enrich_attractions_google_search_snippets

                await enrich_attractions_google_search_snippets(
                    atts,
                    destination,
                    google_api_key=settings.google_places_api_key or "",
                    google_cse_cx=settings.google_cse_cx or "",
                    serpapi_key=settings.serpapi_api_key or "",
                )
                for a in atts:
                    if not isinstance(a, dict):
                        continue
                    snip = a.pop("_google_web_search_snippets", None)
                    if not isinstance(a.get("practical_details"), dict) or not snip:
                        continue
                    pr = a["practical_details"]
                    pr["fees_other"] = str(snip)[:4000]
            except Exception as e:
                logger.warning("Google web search snippets (no LLM) failed: %s", e)

    for a in atts:
        if isinstance(a, dict):
            pr = a.get("practical_details")
            if isinstance(pr, dict):
                w = str(pr.get("walking_hiking") or "")
                if w:
                    pr["walking_hiking"] = walking_hiking_clamp_smart(w, 1000)
                    a["practical_details"] = pr

    if (settings.google_places_api_key or "").strip():
        try:
            atts = await enrich_attractions_parking_directions(
                atts,
                destination,
                settings.google_places_api_key,
            )
        except Exception as e:
            logger.warning("enrich_attractions_parking_directions failed: %s", e)

    for a in atts:
        if isinstance(a, dict):
            pr = _merge_practical_details(a.get("practical_details"))
            _sanitize_meta_instruction_practical(pr)
            a["practical_details"] = pr

    if target_count:
        atts = _fill_attraction_catalog_to_count(
            list(atts), target_count, merged_pre_llm, destination
        )
        if len(atts) > target_count:
            atts = atts[:target_count]

    ats_enriched = await enrich_attractions_images(
        atts,
        destination,
        serpapi_key=settings.serpapi_api_key or "",
        use_serpapi=settings.place_images_use_serpapi,
        google_places_api_key=settings.google_places_api_key or "",
        location_bias=location_bias,
    )
    ats_enriched = _dedupe_attractions_by_canonical_name(ats_enriched)
    if target_count and len(ats_enriched) < target_count:
        ats_enriched = _fill_attraction_catalog_to_count(
            list(ats_enriched), target_count, merged_pre_llm, destination
        )
        if len(ats_enriched) > target_count:
            ats_enriched = ats_enriched[:target_count]
        ats_enriched = await enrich_attractions_images(
            ats_enriched,
            destination,
            serpapi_key=settings.serpapi_api_key or "",
            use_serpapi=settings.place_images_use_serpapi,
            google_places_api_key=settings.google_places_api_key or "",
            location_bias=location_bias,
        )
        ats_enriched = _dedupe_attractions_by_canonical_name(ats_enriched)
        if target_count and len(ats_enriched) > target_count:
            ats_enriched = ats_enriched[:target_count]
    catalog_ordered = _order_attractions_https_image_first(ats_enriched)
    for a in catalog_ordered:
        if not isinstance(a, dict):
            continue
        desc = a.get("description")
        if isinstance(desc, str) and desc.strip():
            a["description"] = sanitize_attraction_description_for_catalog(
                desc,
                str(a.get("google_maps_url") or ""),
            )
    # 이미지·중복 제거 후에도 일수×3 미달이면 merged_pre_llm 없이도 일반 템플릿으로 최종 채움
    if target_count and len(catalog_ordered) < target_count:
        catalog_ordered = _fill_attraction_catalog_to_count(
            list(catalog_ordered), target_count, merged_pre_llm, destination
        )
        if len(catalog_ordered) > target_count:
            catalog_ordered = catalog_ordered[:target_count]
    return _renumber_attraction_ids(catalog_ordered)


def _finalize_merge(
    destination: str,
    route_bundle: dict[str, Any],
    meal_choices: dict[str, Any],
) -> dict[str, Any]:
    route_plan = route_bundle.get("route_plan") or {}
    restaurants_by_attraction = route_bundle.get("restaurants_by_attraction") or {}
    dates = route_bundle.get("trip_dates") or []
    daily_plan = []
    for d in dates:
        day_meals = meal_choices.get(d) or {}
        lunch = day_meals.get("lunch") or {}
        dinner = day_meals.get("dinner") or {}
        lunch_first = lunch.get("first")
        lunch_second = lunch.get("second")
        dinner_first = dinner.get("first")
        dinner_second = dinner.get("second")
        ds = next(
            (x for x in (route_plan.get("daily_schedule") or []) if x.get("date") == d),
            {},
        )
        daily_plan.append(
            {
                "date": d,
                "morning_attraction_id": ds.get("morning_attraction_id"),
                "afternoon_attraction_id": ds.get("afternoon_attraction_id"),
                "lunch": {
                    "first_choice_id": lunch_first,
                    "first_choice_name": _resolve_restaurant_name(
                        lunch_first, restaurants_by_attraction
                    )
                    if lunch_first
                    else None,
                    "second_choice_id": lunch_second,
                    "second_choice_name": _resolve_restaurant_name(
                        lunch_second, restaurants_by_attraction
                    )
                    if lunch_second
                    else None,
                },
                "dinner": {
                    "first_choice_id": dinner_first,
                    "first_choice_name": _resolve_restaurant_name(
                        dinner_first, restaurants_by_attraction
                    )
                    if dinner_first
                    else None,
                    "second_choice_id": dinner_second,
                    "second_choice_name": _resolve_restaurant_name(
                        dinner_second, restaurants_by_attraction
                    )
                    if dinner_second
                    else None,
                },
            }
        )
    return {
        "itinerary_step": "complete",
        "final_itinerary": {
            "title": f"{destination} 맞춤 일정",
            "summary": (
                f"{destination} 일정: 선택한 명소·동선·맛집 우선순위를 반영했습니다. "
                "숙소는 다음 단계에서 예약합니다."
            ),
            "route_plan": route_plan,
            "neighborhoods": route_bundle.get("neighborhoods") or [],
            "daily_plan": daily_plan,
            "meal_choices_raw": meal_choices,
        },
    }


class ItineraryPlannerExecutor(BaseAgentExecutor):
    """다단계 일정: 명소 후보 → 경로·맛집 → 식사 선택 → 완료."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        user_input = context.get_user_input()
        if not user_input:
            await event_queue.enqueue_event(new_agent_text_message("입력이 없습니다."))
            return
        try:
            data = json.loads(user_input)
        except Exception as e:
            await event_queue.enqueue_event(new_agent_text_message(f"입력 오류: {e}"))
            return

        destination = data.get("destination", "")
        origin = data.get("origin", "")
        local_transport = data.get("local_transport", "")
        multi_cities = data.get("multi_cities", [])
        start_date = data.get("start_date", "")
        end_date = data.get("end_date", "")
        preference = data.get("preference") or {}
        selected_flight = data.get("selected_flight") or {}
        phase = (data.get("itinerary_phase") or "attractions").strip().lower()

        trip_days = _trip_inclusive_days(start_date, end_date)
        dates = _date_list(start_date, end_date)

        if phase == "attractions":
            out = _mock_attractions(destination, trip_days, preference)
            n_attr = _attraction_target_count(trip_days)
            merged_pre_llm: list[dict[str, Any]] = []
            location_bias: str | None = None

            if self.settings.google_places_api_key:
                raw_google, location_bias = await _fetch_top_attractions_from_google(
                    origin,
                    destination,
                    local_transport,
                    multi_cities,
                    self.settings.google_places_api_key,
                    start_date=start_date,
                    end_date=end_date,
                    max_count=n_attr,
                )
                if raw_google:
                    merged_pre_llm = _merge_google_with_region_templates(
                        raw_google, destination, n_attr
                    )
                    merged_pre_llm = _dedupe_attractions_by_canonical_name(merged_pre_llm)
                    merged_pre_llm = _fill_attraction_catalog_to_count(
                        list(merged_pre_llm), n_attr, merged_pre_llm, destination
                    )[:n_attr]
                    out["attractions"] = merged_pre_llm
                    out["design_notes"] = (
                        f"{destination} 일정: 구글 Places(주변 검색·전망·케이블카·호수·트레일 등 키워드와 "
                        "목적지 반경 텍스트 검색으로 후보를 모은 뒤, **4.3★ 이상·품질 통과**를 우선하고 "
                        "부족하면 **낮은 평점(높은 순)**으로 상한을 채웁니다. "
                        "지역 큐레이션 풀이 있으면 구글만으로 상한이 채워져도 대표 명소가 빠지지 않게 낮은 점수 후보와 교체·"
                        f"부족 시 오프라인 풀로 여행 일수×3(최대 {n_attr}곳)까지 보충합니다. "
                        "출발지~목적지 차량 동선과 목적지 주변을 약 1:4로 나눕니다."
                    )

            if self.settings.openai_api_key:
                try:
                    from openai import AsyncOpenAI

                    client = AsyncOpenAI(
                        api_key=self.settings.openai_api_key,
                        base_url=self.settings.openai_base_url,
                    )
                    import asyncio
                    
                    chunk_size = 15
                    all_chunks = []
                    
                    if merged_pre_llm:
                        names_only = [s["name"] for s in merged_pre_llm[:n_attr]]
                        for i in range(0, len(names_only), chunk_size):
                            all_chunks.append(names_only[i:i+chunk_size])
                    else:
                        for i in range(0, n_attr, chunk_size):
                            all_chunks.append(min(chunk_size, n_attr - i))
                            
                    async def fetch_chunk(chunk_data, chunk_idx):
                        if isinstance(chunk_data, list):
                            target_n = len(chunk_data)
                            req_names = f"\n- **필수 준수사항**: 반드시 다음 구글맵 검증 명소 리스트에 대해서만 구체적인 가치와 실무 정보를 상세히 작성할 것 (다른 장소 임의 추가 절대 금지): {', '.join(chunk_data)}"
                        else:
                            target_n = chunk_data
                            req_names = ""
                            
                        route_hint = ""
                        if local_transport == "rental_car":
                            route_hint = f"\n- **렌트카 이동 동선 주의**: 출발지({origin})에서 주요 거점({destination})들을 오가는 경로 상에 위치한 명소와 목적지 내부 명소를 포함한다."

                        prompt = f"""당신은 여행 일정 설계 전문가입니다. (Chunk {chunk_idx+1}/{len(all_chunks)})
- 목적지 주변 실제 방문 가능한 구체적 명소만 나열한다.{route_hint}{req_names}
- **[중요] 투어·여행사·현지 가이드 업체·아웃도어 예약만 하는 상점 등은 명소가 아니다.** 산·호수·전망·산장·박물관·마을 등 **실제로 이동해 볼 수 있는 장소**만 넣는다(이름에 Outdoor/Guide/Tour agency만 있는 업체 제외).
- 각 명소는 사용자가 비용·시간·예약을 비교해 고를 수 있게 실무 정보를 반드시 채운다. **입장료·개방·운영 시간·주차 요금·예약 필요 여부**는 빠지면 안 된다(미확인 시 "관련 정보 없음").
- **[parking의 목적]** 사용자는 **전체 일정·숙소**를 정할 때 **어느 거점 도시에서 몇 분 거리인지**를 근거로 삼는다. **내비 검색어만** 적는 것은 **허용하지 않는다**. 반드시 **가장 가까운 인구 3천 이상 거점 지명·인구·승용차 ○분**을 적는다.
- **[절대 금지] 프롬프트 지시문 복사**: "…명시한다" "…채운다" "€ 또는 현지 통화로 명시" 같은 **메타 문구**를 응답에 넣지 말 것. **실제 도시명·€ 금액·분·시간**만 적는다.
- **[이름] 위 명소 리스트가 있으면 `name`은 반드시 그 목록의 문자열을 **글자 단위로 그대로** 복사한다(번역·축약·치환 금지).
- **[설명 description]**: "구글맵 평점 기반" 같은 메타 문구는 절대 쓰지 말 것. 각 장소마다 **지명·지형·대표 루트·다른 명소와의 관계·역사·감상 포인트**를 바탕으로 2~4문장으로 **직접 조사한 것처럼** 구체적으로 서술한다(일반적인 관광 소개문 금지).
- **[중요] 계절·여행 기간**: 일정 **{start_date} ~ {end_date}**에 포함된 **월**을 기준으로 추천한다. **5~9월(또는 그중 일부)이면** 스키장 단지(`ski_resort`)·스키 학교·스키 전용 슬로프·스노우파크 등 **겨울 스키 목적 시설은 넣지 않는다.** 여름에도 운영하는 **전망 케이블카·고산 호수·하이킹 트레일·리프지오** 등은 넣는다. **10~4월 위주 스키 여행**이면 스키 리조트가 핵심일 수 있으므로 그에 맞춘다.
- **[중요] 내부 관람 필수형(박물관·오페라·극장·스칼라 등)**: 입장·공연 예약이 핵심인 곳은 `fees_other`와 `reservation_note`에 **요금·예약 경로·운영 시간**을 숫자와 절차로 구체적으로 적는다. 알 수 없으면 "관련 정보 없음". **외관만 보는 것으로 의미 없는 곳은 넣지 않는다.**
- **[중요] 도보/하이킹·호수(예: Lago di Sorapis, Cadini, 고산 루프)**: 주차(또는 셔틀)·트레일 초입부터 왕복 시간·난이도·철제 구간 여부를 `walking_hiking`에 필수 기재한다. **총 1000자 이내**로 요약·정리한다(서버 보강 단계에서 방문자 리뷰 발췌가 있으면 잘라 붙이지 않고 요약해 넣는다).
- **[중요] 답변 회피 금지**: "확인하십시오", "확인하세요", "현지 안내를 확인하세요", "공식 사이트에서 확인" 등 **사용자에게 확인을 떠넘기는** 문구는 **절대 금지**. 모르면 "관련 정보 없음"이라고 명시하되, 당신의 지식으로 **이미 조사한 것처럼** 구체적인 소요시간·거리·요금(숫자)·도시명을 적는다.

목적지: {destination}
여행 일수: {trip_days}일
취향: {json.dumps(preference, ensure_ascii=False)}

JSON 객체 하나만 출력:
- itinerary_step: "select_attractions"
- trip_days: {trip_days}
- time_ratio_note: (첫 번째 Chunk에만 작성 요망, 나머지는 빈 문자열)
- design_notes: (첫 번째 Chunk에만 작성)
- attractions: **정확히 {target_n}개** 배열(청크별로 개수를 맞출 것. **덜 채우거나 넘기면 안 됨**). 각 항목 필수:
  - id: attr_{chunk_idx}_001 형식의 고유 순번
  - name: 위 필수 리스트가 있으면 그대로 복사. 없으면 공식에 가까운 명소명(한글 병기 가능)
  - category: 짧은 분류
  - description: 2~4문장, 현장 경험자 수준의 구체 서술(지형·동선·소요·비교 포인트). 평점·'자동 추천' 언급 금지
  - image_url: 비워둘 것
  - image_credit: 출처. 없으면 빈 문자열
  - practical_details: 객체(모두 한국어, 구체적 수치·절차):
    - parking: **주차·도로(필수)** — 일정·숙소 판단용 **거점+분**이 본문이다. **한 문단 안에** ① 거점 **지명**+**인구(명)** ② **승용차 약 ○분** ③ **주차·톨 €** (서버 보강 단계에서 `○○에서 승용차 약 N분 (Google Maps …)` 한 줄로 고정될 수 있음). **내비 검색어 단독 금지**. **등록 주소 금지**.
    - cable_car_lift: **케이블카·곤돌라·리프트가 있을 때만** 노선·대략 요금(€) 기재. **없으면 빈 문자열 ""** (키는 두되 내용 비움 — UI에서 항목 숨김). "해당 없음" 문구 금지.
    - walking_hiking: 대표 루프·왕복 예상 시간·난이도·주차~트레일 헤드·철제 구간 등, **총 1000자 이내** 요약(과도한 축약 금지).
    - fees_other: **입장료**·톨·보트·환경세 등 — 금액·통화로 명확히 기재(미확인 시 "관련 정보 없음").
    - reservation_note: **개방·운영 시간**, **예약 필수 여부**, 예약 링크·전화·성수기 제한
    - tips: 준비물·최적 시간대(날씨·혼잡 회피). **평점·리뷰 수는 description에 넣지 말 것**(중복). 비어 있어도 됨.
"""
                        max_retries = 2
                        for attempt in range(max_retries):
                            try:
                                resp = await client.chat.completions.create(
                                    model=self.settings.llm_model,
                                    messages=[{"role": "user", "content": prompt}],
                                )
                                content = resp.choices[0].message.content or ""
                                parsed = _extract_json_object(content)
                                if parsed and parsed.get("itinerary_step") == "select_attractions":
                                    return parsed
                            except Exception:
                                pass
                        return None
                        
                    # 병렬 실행
                    chunk_results = await asyncio.gather(*(fetch_chunk(chunk, idx) for idx, chunk in enumerate(all_chunks)))
                    
                    merged_ats: list[dict[str, Any]] = []
                    valid_json = False
                    
                    for idx, res_chunk in enumerate(chunk_results):
                        if not res_chunk:
                            continue
                        valid_json = True
                        if idx == 0:
                            out["time_ratio_note"] = res_chunk.get("time_ratio_note", "")
                            out["design_notes"] = res_chunk.get("design_notes", out.get("design_notes", ""))
                            
                        ats = res_chunk.get("attractions", [])
                        if isinstance(ats, list):
                            for item in ats:
                                if isinstance(item, dict):
                                    merged_ats.append(_ensure_attraction_record(item, len(merged_ats), destination))
                                    
                    if valid_json and merged_ats:
                        merged_ats = _dedupe_attractions_by_canonical_name(merged_ats)
                        merged_ats = filter_attractions_drop_guide_services(merged_ats)
                        merged_ats = filter_attractions_warm_season_no_ski(
                            merged_ats, start_date, end_date
                        )
                        filtered = _filter_llm_attractions_require_indoor_details(merged_ats)
                        if len(filtered) >= max(6, len(merged_ats) * 2 // 3):
                            merged_ats = filtered
                        merged_ats = _fill_attraction_catalog_to_count(
                            merged_ats, n_attr, merged_pre_llm or None, destination
                        )
                        merged_ats = merged_ats[:n_attr]
                        out["attractions"] = merged_ats
                        out["trip_days"] = trip_days
                except Exception:
                    pass
            atts = out.get("attractions")
            if not isinstance(atts, list):
                atts = []
            atts = _fill_attraction_catalog_to_count(atts, n_attr, merged_pre_llm or None, destination)
            atts = atts[:n_attr]
            out["trip_days"] = trip_days
            if atts:
                out["attractions"] = await postprocess_attraction_list_for_catalog(
                    atts,
                    settings=self.settings,
                    destination=destination,
                    start_date=start_date,
                    end_date=end_date,
                    merged_pre_llm=merged_pre_llm if merged_pre_llm else None,
                    location_bias=location_bias,
                    response_out=out,
                    target_count=n_attr,
                )
            else:
                out["attractions"] = []
            await event_queue.enqueue_event(
                new_agent_text_message(json.dumps(out, ensure_ascii=False))
            )
            return

        if phase == "route_restaurants":
            catalog = data.get("itinerary_attraction_catalog")
            selected_ids = data.get("selected_attraction_ids") or []
            if not isinstance(catalog, list):
                catalog = []
            id_set = {a.get("id") for a in catalog if isinstance(a, dict)}
            selected_objs = [a for a in catalog if isinstance(a, dict) and a.get("id") in selected_ids]
            if not selected_objs:
                for sid in selected_ids:
                    if sid in id_set:
                        selected_objs.append(next(x for x in catalog if x.get("id") == sid))
            if not selected_objs:
                await event_queue.enqueue_event(
                    new_agent_text_message(
                        json.dumps(
                            {
                                "error": "선택한 명소가 없습니다. 최소 한 곳 이상 선택해 주세요.",
                            },
                            ensure_ascii=False,
                        )
                    )
                )
                return
            out = _mock_route_and_restaurants(
                destination, trip_days, dates, selected_objs, preference
            )
            if self.settings.openai_api_key:
                try:
                    from openai import AsyncOpenAI

                    client = AsyncOpenAI(
                        api_key=self.settings.openai_api_key,
                        base_url=self.settings.openai_base_url,
                    )
                    prompt = f"""여행 일정 2단계. 한국어 JSON만 출력.

목적지: {destination}
일수: {trip_days}, 날짜 목록: {json.dumps(dates, ensure_ascii=False)}
선택된 명소: {json.dumps(selected_objs, ensure_ascii=False)}
취향: {json.dumps(preference, ensure_ascii=False)}
항공: {json.dumps(selected_flight, ensure_ascii=False)}

요구:
1) 동선을 고려해 일자별 오전·오후 명소 id를 배정. 숙소에서 차로 1시간 초과 거리면 숙소 이동을 검토하되 한 거점 유지를 우선.
2) 목적지 주변 추천 동네(숙소 후보 지역) 2~4개: area_id, name, description, reachable_attraction_ids, lodging_notes.
3) 공항↔목적지 구간에 볼거리가 있으면 transit_legs에 leg(outbound|return), notes, suggested_overnight(도시명 또는 null), sights_along_route(짧은 배열).
4) 각 선택 명소마다 식당 3곳: rating 내림차순, id는 고유문자열, description 짧게.

출력 JSON 키:
- itinerary_step: "select_meals"
- route_plan: daily_schedule( date, morning_attraction_id, afternoon_attraction_id, overnight_area_hint ), transit_legs, lodging_strategy, destination_base_days
- neighborhoods: 배열
- restaurants_by_attraction: 객체, 키는 명소 id, 값은 길이 3 배열 {{id,name,rating,description}}
- trip_dates: {json.dumps(dates, ensure_ascii=False)}"""
                    resp = await client.chat.completions.create(
                        model=self.settings.llm_model,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    content = resp.choices[0].message.content or ""
                    parsed = _extract_json_object(content)
                    if (
                        parsed
                        and parsed.get("itinerary_step") == "select_meals"
                        and isinstance(parsed.get("restaurants_by_attraction"), dict)
                    ):
                        parsed["trip_dates"] = dates
                        out = parsed
                except Exception:
                    pass
            await event_queue.enqueue_event(
                new_agent_text_message(json.dumps(out, ensure_ascii=False))
            )
            return

        if phase == "finalize":
            meal_choices = data.get("meal_choices") or {}
            route_bundle = data.get("route_plan_bundle") or {}
            if not isinstance(meal_choices, dict):
                meal_choices = {}
            out = _finalize_merge(destination, route_bundle, meal_choices)
            if self.settings.openai_api_key:
                try:
                    from openai import AsyncOpenAI

                    client = AsyncOpenAI(
                        api_key=self.settings.openai_api_key,
                        base_url=self.settings.openai_base_url,
                    )
                    prompt = f"""아래 데이터로 여행 일정 최종 요약을 한국어로 다듬는다. JSON만 출력.

목적지: {destination}
route_plan_bundle: {json.dumps(route_bundle, ensure_ascii=False)[:12000]}
meal_choices: {json.dumps(meal_choices, ensure_ascii=False)}

출력:
{{"itinerary_step":"complete","final_itinerary":{{"title","summary","route_plan","neighborhoods","daily_plan"(날짜별 점심·저녁 식당 이름 포함), "meal_choices_raw"}}}}"""
                    resp = await client.chat.completions.create(
                        model=self.settings.llm_model,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    content = resp.choices[0].message.content or ""
                    parsed = _extract_json_object(content)
                    if parsed and parsed.get("itinerary_step") == "complete":
                        out = parsed
                except Exception:
                    pass
            await event_queue.enqueue_event(
                new_agent_text_message(json.dumps(out, ensure_ascii=False))
            )
            return

        await event_queue.enqueue_event(
            new_agent_text_message(
                json.dumps({"error": f"알 수 없는 itinerary_phase: {phase}"}, ensure_ascii=False)
            )
        )

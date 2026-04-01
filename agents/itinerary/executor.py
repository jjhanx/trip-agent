"""Itinerary Planner Agent — 명소 후보 → 경로·동네·맛집 → 식사 선택 → 최종 일정."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any

from a2a.server.agent_execution import RequestContext
from a2a.server.events import EventQueue

from agents.base_agent import BaseAgentExecutor
from config import Settings
from shared.place_images import enrich_attractions_images
from shared.utils import new_agent_text_message


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
    return base


def _default_practical_block() -> dict[str, str]:
    return {
        "parking": "주차장 위치·요금·예약 필요 여부는 방문 시즌마다 바뀌므로 현지 공식 안내·내비를 확인하세요.",
        "cable_car_lift": "케이블카·리프트가 없거나 미이용 시 도보·셔틀만 해당됩니다. 있을 경우 공식 요금표로 확인하세요.",
        "walking_hiking": "예상 도보·트레일 시간과 난이도는 코스 선택에 따라 다릅니다. 지도·현지 표지를 기준으로 하세요.",
        "fees_other": "입장료·환경세·톨게이트 등은 연도별로 달라질 수 있습니다.",
        "reservation_note": "성수기·주말에는 주차·입장·보트 등 사전 예약이 필요할 수 있습니다.",
        "tips": "날씨·일몰 시각·개장 시간을 출발 전에 확인하세요.",
    }


def _ensure_attraction_record(a: dict[str, Any], idx: int, destination: str) -> dict[str, Any]:
    out = dict(a)
    out.setdefault("id", f"attr_{idx + 1:03d}")
    out.setdefault("name", f"{destination} 명소 {idx + 1}")
    out.setdefault("category", "관광")
    out.setdefault("description", "")
    out.setdefault("image_url", "")
    out.setdefault("image_credit", "")
    pr = _merge_practical_details(out.get("practical_details"))
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
                "parking": "아우론조(Auronzo) 유료 주차장 이용. 성수기(여름·주말)에는 온라인 사전 예약이 사실상 필수인 경우가 많고, 일당 대략 €30~45 전후(연도·시즌·시간대별 상이).",
                "cable_car_lift": "차량으로 아우론조 주차장까지 진입 후 도보(해당 구간은 유료 도로·입장 개념이 붙는 시즌이 있음—현지 표지 확인).",
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
                "cable_car_lift": "해당 없음(호수 주변 도보).",
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
            "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/6/6e/St._Johann_in_Ranui_mit_Geislergruppe.jpg/800px-St._Johann_in_Ranui_mit_Geislergruppe.jpg",
            "image_credit": f"{w} · Val di Funes",
            "practical_details": {
                "parking": "뷰포인트·교회 인근 유료·시간제 주차. 성수기 혼잡.",
                "cable_car_lift": "해당 없음.",
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
                "cable_car_lift": "해당 없음.",
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
            "image_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/4/4f/Cadini_di_Misurina.jpg/800px-Cadini_di_Misurina.jpg",
            "image_credit": f"{w}",
            "practical_details": {
                "parking": "미수리나 또는 근처 주차 후 도보 접근.",
                "cable_car_lift": "해당 없음.",
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
                "cable_car_lift": "해당 없음.",
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
                "cable_car_lift": "해당 없음.",
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
                "cable_car_lift": "왕복 요금 확인 필요.",
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
                "cable_car_lift": "리프트 운영 기간 확인.",
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
                "cable_car_lift": "도보로만 접근 가능.",
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
            "parking": "시내·관광지 주차장 위치와 요금(시간/일당)은 현지 표지와 앱으로 확인. 성수기에는 예약·제한 구역(ZTL) 주의.",
            "cable_car_lift": "리프트·케이블카가 있으면 공식 사이트 요금·마지막 운행 시각 확인. 없으면 해당 없음.",
            "walking_hiking": "왕복 예상 도보 시간은 코스마다 다름(1~4시간). 난이도·날씨를 고려해 여유 있게 잡을 것.",
            "fees_other": "입장료·톨·환경세는 연도별로 변동.",
            "reservation_note": "인기 명소·전시는 사전 예약 권장.",
            "tips": "물·방풍·막바람에 대비. 일몰 전 하산.",
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
    n = min(trip_days * 3, 42)
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
    origin: str, destination: str, local_transport: str, multi_cities: list,
    api_key: str, min_rating: float = 4.3, max_count: int = 42
) -> list[dict[str, Any]]:
    """Google Places API (Text Search)를 사용해 경로 1 : 목적지 4 비율로 명소를 탐색합니다."""
    import httpx
    import asyncio
    from urllib.parse import urlencode

    # 목적지 주소들
    dest_places = []
    for pt in destination.replace(" 및 ", ",").replace(" 등", "").split(","):
        if pt.strip() and pt.strip() not in dest_places:
            dest_places.append(pt.strip())
            
    for mc in multi_cities:
        for pt in mc.get("destination", "").replace(" 및 ", ",").split(","):
            if pt.strip() and pt.strip() not in dest_places:
                dest_places.append(pt.strip())
    
    if not dest_places:
        dest_places = [destination]

    route_points = []
    dest_points = []

    async def get_lat_lng(client, addr):
        try:
            url = "https://maps.googleapis.com/maps/api/geocode/json?" + urlencode({
                "address": addr,
                "key": api_key
            })
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

    async def get_route_waypoints(client, o, d):
        try:
            url = "https://maps.googleapis.com/maps/api/directions/json?" + urlencode({
                "origin": o,
                "destination": d,
                "key": api_key
            })
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
        # 1. 목적지 Geocoding
        d_locs = await asyncio.gather(*(get_lat_lng(client, p) for p in dest_places))
        for loc in d_locs:
            if loc:
                dest_points.append(loc)

        # 2. 렌터카일 경우 경로 Waypoint 계산
        if local_transport == "rental_car" and origin:
            # 첫번째 목적지까지의 경로만 간단히 확인.
            wpts = await get_route_waypoints(client, origin, dest_places[0])
            route_points.extend(wpts)
            
    if not dest_points:
        return []

    # 비율 계산 & 할당
    # 5개의 구간: route에 1, dest에 4를 할당. (총 max_count개)
    route_target = max_count // 5 if route_points else 0
    dest_target = max_count - route_target

    async def fetch_places(client, loc, is_route: bool) -> list[dict[str, Any]]:
        if not loc:
            return []
        
        # nearbysearch를 사용해 확실하게 반경 내 다수의 명소를 확보
        # 다양한 키워드로 병렬 호출하여 20개 이상의 충분한 POI 풀을 만듦
        keywords = ["관광 명소", "자연", "파크", "랜드마크"]
        if is_route:
            keywords = ["관광 명소", "랜드마크"]
            
        async def _search(kw):
            params = {
                "location": loc,
                "radius": "45000",
                "type": "tourist_attraction",
                "key": api_key,
                "language": "ko"
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
            
        tasks = [_search(kw) for kw in keywords]
        tasks.append(_search("")) # 키워드 없는 기본 type 검색 추가
        
        pages = await asyncio.gather(*tasks)
        combined = []
        for page in pages:
            combined.extend(page)
        return combined

    async with httpx.AsyncClient(timeout=20) as client:
        # 경로 수집
        route_tasks = []
        for loc in route_points:
            route_tasks.append(fetch_places(client, loc, True))
        route_res = await asyncio.gather(*route_tasks) if route_tasks else []

        # 목적지 수집
        dest_tasks = []
        for loc in dest_points:
            dest_tasks.append(fetch_places(client, loc, False))
        dest_res = await asyncio.gather(*dest_tasks) if dest_tasks else []

    # 병원, 치과, 숙박 등 불필요 장소 필터링
    bad_types = {"hospital", "health", "dentist", "doctor", "lodging", "real_estate_agency", "gym", "spa", "hair_care", "laundry", "car_repair", "pharmacy", "bank", "atm"}

    def filter_and_sort(lists: list[list[dict]], target_cnt: int) -> list[dict]:
        combined = []
        seen = set()
        for lst in lists:
            for p in lst:
                pid = p.get("place_id")
                if not pid or pid in seen:
                    continue
                rating = p.get("rating", 0.0)
                reviews = p.get("user_ratings_total", 0)
                if rating < min_rating or reviews < 50:
                    continue
                # 타입 필터
                ptypes = set(p.get("types", []))
                if ptypes.intersection(bad_types):
                    continue
                
                seen.add(pid)
                combined.append(p)
                
        # 평점, 리뷰수로 정렬
        combined.sort(key=lambda x: (x.get("rating", 0.0), x.get("user_ratings_total", 0)), reverse=True)
        return combined[:target_cnt]

    route_spots = filter_and_sort(route_res, route_target)
    # 이미 선택된 `route_spots`에 포함된 ID는 `dest_spots`에서 제거하기 위해 `seen_places` 활용
    route_ids = {s.get("place_id") for s in route_spots}
    
    # dest_spots 처리 (route_spots 중복 방지 필요)
    dest_combined = []
    dest_seen = set(route_ids)
    for lst in dest_res:
        for p in lst:
            pid = p.get("place_id")
            if not pid or pid in dest_seen:
                continue
            rating = p.get("rating", 0.0)
            reviews = p.get("user_ratings_total", 0)
            if rating < min_rating or reviews < 50:
                continue
            ptypes = set(p.get("types", []))
            if ptypes.intersection(bad_types):
                continue
            
            dest_seen.add(pid)
            dest_combined.append(p)
            
    dest_combined.sort(key=lambda x: (x.get("rating", 0.0), x.get("user_ratings_total", 0)), reverse=True)
    dest_spots = dest_combined[:dest_target]

    results = route_spots + dest_spots

    out: list[dict[str, Any]] = []
    for i, p in enumerate(results):
        name = p.get("name", f"추천 스팟 {i+1}")
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
        desc = f"구글맵 평점 {r_val}★ ({rc_val}개 리뷰). {address}"
        
        image_url = ""
        photos = p.get("photos", [])
        if photos:
            pref = photos[0].get("photo_reference")
            if pref:
                image_url = f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=960&photoreference={pref}&key={api_key}"
                
        out.append({
            "id": f"attr_{i+1:03d}",
            "name": name,
            "category": category,
            "description": desc,
            "image_url": image_url,
            "image_credit": "Google Maps",
            "practical_details": {
                "tips": "구글맵 공식 리뷰와 평점을 기반으로 자동 추천된 명소입니다.",
            }
        })
        
    return out


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
            n_attr = trip_days * 3
            if n_attr > 45:
                n_attr = 45 # 너무 방대한 데이터 방지
            google_spots = []
            
            # 구글 Places API가 존재하면, 목적지와 무관하게 해당 지역의 평점 높은 명소를 구글맵에서 동적으로 검색해 교체합니다.
            if self.settings.google_places_api_key:
                google_spots = await _fetch_top_attractions_from_google(
                    origin, destination, local_transport, multi_cities, self.settings.google_places_api_key, max_count=n_attr
                )
                if google_spots:
                    out["attractions"] = google_spots
                    out["design_notes"] = f"{destination} 일정: 구글맵 기반으로 출발지~목적지의 차량 이동 경로 및 목적지 반경 45km(약 1시간 거리) 이내의 검증된 우수 명소들을 1:4 비율로 동적 분석하여 추천합니다."


            if self.settings.openai_api_key:
                try:
                    from openai import AsyncOpenAI

                    client = AsyncOpenAI(
                        api_key=self.settings.openai_api_key,
                        base_url=self.settings.openai_base_url,
                    )
                    
                    route_hint = ""
                    if local_transport == "rental_car":
                        route_hint = f"\n- **렌트카 이동 동선 주의**: 출발지({origin})에서 주요 거점({destination})들을 오가는 경로 상에 위치한 명소와 목적지 내부 명소를 포함한다."
                        
                    target_n = n_attr
                    if google_spots:
                        names_only = [s["name"] for s in google_spots[:n_attr]]
                        route_hint += f"\n- **필수 준수사항**: 반드시 다음 구글맵 검증 명소 리스트에 대해서만 여행지로서의 구체적인 가치와 실무 정보(주차, 요금, 트래킹 시간 등)를 상세히 작성할 것 (다른 장소 임의 추가 금지): {', '.join(names_only)}"
                        target_n = len(names_only)

                    prompt = f"""당신은 여행 일정 설계 전문가입니다.
- 목적지 주변 **실제 방문 가능한 구체적 명소**만 나열한다(유형만이 아니라 정식 명칭: 예 Tre Cime, Seceda, Lago di Braies).{route_hint}
- 각 명소는 사용자가 **비용·시간·예약**을 비교해 고를 수 있게 **실무 정보**를 반드시 채운다.
- 공항↔목적지 이동과 현지 체류 균형(이상적 비율 약 4:1)을 time_ratio_note에 반영한다.

목적지: {destination}
여행 일수(포함): {trip_days}일
취향: {json.dumps(preference, ensure_ascii=False)}
선택 항공: {json.dumps(selected_flight, ensure_ascii=False)}

JSON 객체 하나만 출력:
- itinerary_step: "select_attractions"
- trip_days: {trip_days}
- time_ratio_note: 한국어
- design_notes: 한국어(요금은 참고용·현지 확인 필요 등 면책 한 줄 포함)
- attractions: 정확히 {target_n}개 배열. 각 항목 필수:
  - id: attr_001부터 순번
  - name: 공식에 가까운 명소명(한글 병기 가능)
  - category: 짧은 분류
  - description: 2~3문장, 이 명소가 여행지로서 왜 가치 있고 꼭 가봐야 하는 곳인지 구체적인 매력(풍경, 역사, 활동 등)을 설명
  - image_url: 비워도 됨(서버가 영문·이탈 위키백과 썸네일·Commons 파일로 자동 매칭). 직접 넣을 때만 https 공개 링크.
  - image_credit: 출처(photographer·라이선스). 없으면 빈 문자열
  - practical_details: 객체(모두 한국어, 구체적 수치·절차):
    - parking: 주차장명·유료 여부·대략 요금(€)·사전 예약 필요 여부
    - cable_car_lift: 케이블카/리프트 구간·편도·왕복 대략 요금(€)·없으면 "해당 없음" 또는 차량 접근만
    - walking_hiking: 대표 루프·왕복 예상 시간·난이도
    - fees_other: 입장료·톨·보트 등 기타
    - reservation_note: 예약 링크·성수기 제한 요약
    - tips: 준비물·최적 시간대
"""
                    resp = await client.chat.completions.create(
                        model=self.settings.llm_model,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    content = resp.choices[0].message.content or ""
                    parsed = _extract_json_object(content)
                    if parsed and parsed.get("itinerary_step") == "select_attractions":
                        ats = parsed.get("attractions")
                        if isinstance(ats, list) and len(ats) >= 3:
                            merged: list[dict[str, Any]] = []
                            for i, item in enumerate(ats):
                                if isinstance(item, dict):
                                    merged.append(
                                        _ensure_attraction_record(item, i, destination)
                                    )
                            parsed["attractions"] = merged
                            out = parsed
                            out["trip_days"] = trip_days
                except Exception:
                    pass
            atts = out.get("attractions")
            if isinstance(atts, list) and atts:
                if google_spots:
                    gmap = { gs["name"].lower(): gs for gs in google_spots }
                    for a in atts:
                        n_lower = (a.get("name") or "").lower()
                        if n_lower in gmap:
                            gs = gmap[n_lower]
                            if gs.get("place_id"):
                                a["place_id"] = gs.get("place_id")
                            if gs.get("image_url"):
                                a["image_url"] = gs.get("image_url")
                                a["image_credit"] = gs.get("image_credit")
                                a["image_source"] = gs.get("image_source")

                out["attractions"] = await enrich_attractions_images(
                    atts,
                    destination,
                    serpapi_key=self.settings.serpapi_api_key or "",
                    use_serpapi=self.settings.place_images_use_serpapi,
                    google_places_api_key=self.settings.google_places_api_key or "",
                )
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

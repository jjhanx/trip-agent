"""Hotel search logic - shared by MCP server and agents."""

from datetime import datetime
from urllib.parse import quote_plus

ACCOMMODATION_TYPES = [
    "hotel", "guesthouse", "hostel", "apartment", "resort",
    "villa", "bnb", "hotel_with_kitchen", "mountain_lodge",
]


def _stay_nights(check_in: str | None, check_out: str | None) -> int:
    try:
        a = datetime.strptime((check_in or "")[:10], "%Y-%m-%d").date()
        b = datetime.strptime((check_out or "")[:10], "%Y-%m-%d").date()
        n = (b - a).days
        return max(1, n)
    except (ValueError, TypeError):
        return 1


def _itinerary_title(itin: dict | None) -> str:
    if not itin or not isinstance(itin, dict):
        return ""
    return str(itin.get("title") or "").strip()


def mock_search_hotels(
    location: str,
    accommodation_type: str = "hotel",
    accommodation_priority: list[str] | None = None,
    travelers_total: int | None = None,
    selected_itinerary: dict | None = None,
    check_in: str | None = None,
    check_out: str | None = None,
) -> list[dict]:
    """Generate mock hotel results.

    accommodation_priority: 선호 3순위, 혼합 후보 제시.
    travelers_total / selected_itinerary: UI·선정 근거 문구용(실제 지도·가격 API는 별도).
    """
    priority = accommodation_priority or [accommodation_type]
    valid = [p for p in priority if p in ACCOMMODATION_TYPES] or ["hotel"]
    types_for_results = (valid * 2)[:5]
    guests = max(1, travelers_total or 2)
    nights = _stay_nights(check_in, check_out)
    it_title = _itinerary_title(selected_itinerary)
    rationale_base = (
        f"일행 {guests}명 수용·선호 숙소 형태를 반영한 혼합 후보입니다."
        if guests
        else "선호 숙소 형태를 반영한 혼합 후보입니다."
    )
    if it_title:
        rationale_base += f" 일정「{it_title}」동선을 고려해 거점·이동 부담을 줄이는 쪽으로 구성했습니다."

    base_hotels: list[dict] = [
        {
            "hotel_id": "HT001",
            "name": "Central Plaza Hotel",
            "location": f"{location} 중심가 인근",
            "price_per_night_krw": 120000,
            "rating": 4.5,
            "amenities": ["wifi", "breakfast", "parking"],
            "breakfast_included": True,
            "kitchen": False,
            "bedroom_summary": "침실 2 · 욕실 2 · 거실 1",
            "parking_fee_text": "숙소 지하 주차 1대 무료(추가 차량 1일 약 15€)",
            "feature_highlights": ["실내 수영장", "사우나", "피트니스"],
            "fit_notes": (
                "주요 명소 구간은 렌트로 이동 시 주차장이 넓은 편입니다. "
                "케이블카·리프트역은 도보 12~18분 또는 근처 셔틀 버스 노선이 있습니다(현지 앱으로 확인)."
            ),
            "booking_url": (
                f"https://www.booking.com/searchresults.html?ss={quote_plus(location)}"
                f"&checkin={check_in or ''}&checkout={check_out or ''}&group_adults={guests}"
            ),
        },
        {
            "hotel_id": "HT002",
            "name": "Riverside Inn",
            "location": f"{location} 강변 조용한 거리",
            "price_per_night_krw": 95000,
            "rating": 4.2,
            "amenities": ["wifi", "breakfast"],
            "breakfast_included": True,
            "kitchen": False,
            "bedroom_summary": "침실 1 · 욕실 1",
            "parking_fee_text": "인근 공영 주차(숙소 할인권, 1일 약 12€)",
            "feature_highlights": ["조식 뷔페", "테라스"],
            "fit_notes": "관광지 방문 시 도심 혼잡 구간은 대중교통·도보 연계를 권장합니다.",
            "booking_url": (
                f"https://www.booking.com/searchresults.html?ss={quote_plus(location + ' riverside')}"
                f"&checkin={check_in or ''}&checkout={check_out or ''}&group_adults={guests}"
            ),
        },
        {
            "hotel_id": "HT003",
            "name": "Sunset Resort",
            "location": f"{location} 교외 리조트 존",
            "price_per_night_krw": 180000,
            "rating": 4.8,
            "amenities": ["wifi", "breakfast", "pool", "spa"],
            "breakfast_included": True,
            "kitchen": False,
            "bedroom_summary": "침실 3 · 욕실 3 · 발코니",
            "parking_fee_text": "부지 내 주차 무료",
            "feature_highlights": ["야외 수영장", "스파·자쿠지", "키즈 클럽"],
            "fit_notes": (
                "명소가 퍼져 있을 때 숙소 이동을 줄이려면 리조트를 거점으로 두고 당일 왕복 동선을 짜기 좋습니다. "
                "케이블카 스테이션은 주차 후 도보 8분 안팎인 날과, 셔틀을 쓰는 날을 나누는 식으로 선택할 수 있습니다."
            ),
            "booking_url": (
                f"https://www.booking.com/searchresults.html?ss={quote_plus(location + ' resort')}"
                f"&checkin={check_in or ''}&checkout={check_out or ''}&group_adults={guests}"
            ),
        },
        {
            "hotel_id": "HT004",
            "name": "City Stay Apartments",
            "location": f"{location} 시티 아파트",
            "price_per_night_krw": 145000,
            "rating": 4.3,
            "amenities": ["wifi", "kitchen"],
            "breakfast_included": False,
            "kitchen": True,
            "bedroom_summary": "침실 2 · 욕실 2 · 주방(식기·쿡탑)",
            "parking_fee_text": "건물 지하 유료(1일 약 18€), 인근 거리 주차 대안 안내",
            "feature_highlights": ["주방", "세탁기", "거실"],
            "fit_notes": "가족·장기 체류에 적합합니다. 주차는 입구 협소 구간이 있어 짐 실을 앞두고 확인하세요.",
            "booking_url": (
                f"https://www.booking.com/searchresults.html?ss={quote_plus(location + ' apartment')}"
                f"&checkin={check_in or ''}&checkout={check_out or ''}&group_adults={guests}"
            ),
        },
        {
            "hotel_id": "HT005",
            "name": "Mountain View Lodge",
            "location": f"{location} 산악 게이트웨이",
            "price_per_night_krw": 150000,
            "rating": 4.6,
            "amenities": ["wifi", "breakfast", "parking", "garden"],
            "breakfast_included": True,
            "kitchen": True,
            "bedroom_summary": "침실 2 · 욕실 1 · 간이 주방",
            "parking_fee_text": "무료 야외 주차(눈·진입로 시즌 확인)",
            "feature_highlights": ["정원", "테라스 바베큐", "사우나"],
            "fit_notes": (
                "케이블카·리프트 승강장까지 도보 가능 거리(약 10~15분)인 날을 고르면 "
                "협소 주차장·회전 교통 구간 스트레스를 줄일 수 있습니다."
            ),
            "booking_url": (
                f"https://www.booking.com/searchresults.html?ss={quote_plus(location + ' mountain lodge')}"
                f"&checkin={check_in or ''}&checkout={check_out or ''}&group_adults={guests}"
            ),
        },
    ]

    out: list[dict] = []
    for h, t in zip(base_hotels, types_for_results):
        hid = h["hotel_id"]
        imgs = [
            f"https://picsum.photos/seed/{hid}-a/800/600",
            f"https://picsum.photos/seed/{hid}-b/800/600",
            f"https://picsum.photos/seed/{hid}-c/800/600",
            f"https://picsum.photos/seed/{hid}-d/800/600",
            f"https://picsum.photos/seed/{hid}-e/800/600",
        ]
        ppn = int(h["price_per_night_krw"])
        row = {
            **h,
            "accommodation_type": t,
            "image_urls": imgs,
            "stay_nights": nights,
            "total_stay_estimate_krw": ppn * nights,
            "selection_rationale": rationale_base,
        }
        out.append(row)
    return out

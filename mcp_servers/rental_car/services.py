"""Rental car search logic - shared by MCP server and agents."""

import math

# 차급별 최대 탑승 인원 (compact=4, sedan=5, suv=7, van=8)
_CAR_SEATS = {"compact": 4, "sedan": 5, "suv": 7, "van": 8, "minivan": 8}

# 여행 가방 고려: 일행 x 1.5 좌석 → "추천" 배지. 최소 seats >= passengers 인 차량은 모두 표시
_CAPACITY_MULTIPLIER = 1.5

# 공항코드 → economybookings.com 경로 (region, country, city, airport_slug)
# 사용자 선호: economybookings.com. 실시간 가격은 해당 사이트에서 확인.
_AIRPORT_TO_ECONOMYBOOKINGS = {
    "MXP": ("europe", "italy", "milan", "mxp"),
    "FCO": ("europe", "italy", "rome", "fco"),
    "NAP": ("europe", "italy", "naples", "nap"),
    "ICN": ("asia", "south-korea", "seoul", "icn"),
    "GMP": ("asia", "south-korea", "seoul", "gmp"),
    "NRT": ("asia", "japan", "tokyo", "nrt"),
    "HND": ("asia", "japan", "tokyo", "hnd"),
    "KIX": ("asia", "japan", "osaka", "kix"),
    "LHR": ("europe", "united-kingdom", "london", "lhr"),
    "LGW": ("europe", "united-kingdom", "london", "lgw"),
    "CDG": ("europe", "france", "paris", "cdg"),
    "ORY": ("europe", "france", "paris", "ory"),
    "FRA": ("europe", "germany", "frankfurt", "fra"),
    "MUC": ("europe", "germany", "munich", "muc"),
    "BCN": ("europe", "spain-mainland", "barcelona", "bcn"),
    "MAD": ("europe", "spain-mainland", "madrid", "mad"),
    "AGP": ("europe", "spain-mainland", "malaga", "agp"),
    "AMS": ("europe", "netherlands", "amsterdam", "ams"),
    "SIN": ("asia", "singapore", "singapore", "sin"),
    "BKK": ("asia", "thailand", "bangkok", "bkk"),
    "DUB": ("europe", "ireland", "dublin", "dub"),
    "DXB": ("asia", "united-arab-emirates", "dubai", "dxb"),
    "MCO": ("north-america", "usa-florida", "orlando", "mco"),
    "MIA": ("north-america", "usa-florida", "miami", "mia"),
    "LAX": ("north-america", "usa-california", "los-angeles", "lax"),
    "JFK": ("north-america", "usa-new-york", "new-york-city", "jfk"),
    "MEL": ("oceania", "australia", "melbourne", "mel"),
    "SYD": ("oceania", "australia", "sydney", "syd"),
    "LIS": ("europe", "portugal", "lisbon", "lis"),
}


def _min_car_type_for_passengers(required_seats: int) -> str:
    """필요 좌석 수에 맞는 최소 차급."""
    if required_seats <= 4:
        return "compact"
    if required_seats <= 5:
        return "sedan"
    if required_seats <= 7:
        return "suv"
    return "van"


def _build_economybookings_url(
    pickup: str,
    dropoff: str,
    start_date: str,
    end_date: str,
) -> str:
    """economybookings.com 예약 검색 URL (사용자 선호 사이트).
    검색 조건(픽업·반납·날짜) 반영. 실시간 가격은 사이트에서 확인.
    """
    pickup_upper = (pickup or "").strip().upper()[:3]
    path = _AIRPORT_TO_ECONOMYBOOKINGS.get(pickup_upper)
    if path:
        region, country, city, airport = path
        base = f"https://www.economybookings.com/car-rental/{region}/{country}/{city}/{airport}"
    else:
        base = "https://www.economybookings.com/car-rental/all"
    # economybookings 날짜 파라미터 (지원 시 폼 자동 채움)
    if start_date and len(start_date) >= 10 and end_date and len(end_date) >= 10:
        from urllib.parse import urlencode
        q = urlencode({
            "pickup_date": start_date[:10],
            "dropoff_date": end_date[:10],
        })
        return f"{base}?{q}"
    return base


def mock_search_rentals(
    pickup: str,
    dropoff: str,
    car_type: str,
    days: int = 3,
    passengers: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    travelpayouts_rental_booking_url: str | None = None,
) -> list[dict]:
    """Generate rental car options (차급별 참고 카드).
    - 일행이 탑승 가능한(seats >= passengers) 차량 모두 표시
    - 일행 x 1.5 좌석 이상은 recommended 표시 (여행가방 여유)
    - 가격: 근거 없는 추정 가격은 표시하지 않음. 실시간 가격은 예약 사이트(EconomyBookings 등)에서 확인.
    """
    raw_seats = passengers or 1
    min_seats = raw_seats
    recommended_seats = max(min_seats, math.ceil(raw_seats * _CAPACITY_MULTIPLIER))
    start_d = start_date or ""
    end_d = end_date or start_d
    eb_url = _build_economybookings_url(pickup, dropoff, start_d, end_d)

    tp_rental = (travelpayouts_rental_booking_url or "").strip()
    tp_card = {
        "rental_id": "TP-AFFILIATE",
        "provider": "Travelpayouts 제휴 렌트카",
        "car_type": "다양",
        "seats": 9,
        "vehicle_name": "제휴 파트너 검색 (픽업·날짜는 링크에서 확인)",
        "description": "Travelpayouts 대시보드에서 생성한 렌트카 제휴 링크입니다. 실시간 가격·차종은 해당 사이트에서 확인하세요.",
        "features": ["제휴 링크", "실시간 가격"],
        "luggage_capacity": "차종별 상이",
        "image_url": "https://images.unsplash.com/photo-1449965408869-eaa3f722e40d?w=400&h=260&fit=crop",
        "pickup_location": pickup,
        "dropoff_location": dropoff,
        "price_total_krw": None,
        "price_basis": "실시간 가격은 제휴 사이트에서 확인",
        "recommended": True,
        "booking_url": tp_rental,
    }

    # EconomyBookings 선호: 600+ 업체 비교, 실시간 가격. 상단에 포함.
    economy_card = {
        "rental_id": "EB-COMPARE",
        "provider": "EconomyBookings",
        "car_type": "다양",
        "seats": 9,
        "vehicle_name": "600+ 렌트카 업체 비교",
        "description": "실시간 가격·가용성 확인. Hertz, Avis, Sixt, Europcar 등.",
        "features": ["실시간 가격", "600+ 업체", "가격 비교"],
        "luggage_capacity": "차종별 상이",
        "image_url": "https://images.unsplash.com/photo-1449965408869-eaa3f722e40d?w=400&h=260&fit=crop",
        "pickup_location": pickup,
        "dropoff_location": dropoff,
        "price_total_krw": None,
        "price_basis": "실시간 가격은 아래 '예약 사이트'에서 확인",
        "recommended": True,
        "booking_url": eb_url,
    }

    # 차량별 참고 카드 (가격 없음 - 근거 없는 추정 제거)
    candidates = [
        {
            "rental_id": "RC001", "provider": "Hertz", "car_type": "compact", "seats": 4,
            "vehicle_name": "Toyota Yaris / VW Polo",
            "description": "소형 세단. 도심 주행에 적합, 연비 우수.",
            "features": ["에어컨", "블루투스", "후방카메라"],
            "luggage_capacity": "중형 수하물 2개",
            "image_url": "https://images.unsplash.com/photo-1552519507-da3b142c6e3d?w=400&h=260&fit=crop",
        },
        {
            "rental_id": "RC002", "provider": "Avis", "car_type": "sedan", "seats": 5,
            "vehicle_name": "Toyota Camry / Honda Accord",
            "description": "중형 세단. 넓은 실내, 안정적인 주행.",
            "features": ["에어컨", "블루투스", "크루즈컨트롤", "가죽시트"],
            "luggage_capacity": "중형 수하물 3개",
            "image_url": "https://images.unsplash.com/photo-1605559424843-9e4c228bf1c2?w=400&h=260&fit=crop",
        },
        {
            "rental_id": "RC003", "provider": "Local Rent", "car_type": "suv", "seats": 7,
            "vehicle_name": "Toyota RAV4 / Kia Sorento",
            "description": "7인승 SUV. 가족 여행, 넉넉한 트렁크.",
            "features": ["에어컨", "블루투스", "3열 시트", "충돌감지"],
            "luggage_capacity": "대형 수하물 4~5개",
            "image_url": "https://images.unsplash.com/photo-1519641471654-76ce0107ad1b?w=400&h=260&fit=crop",
        },
        {
            "rental_id": "RC004", "provider": "Sixt", "car_type": "van", "seats": 8,
            "vehicle_name": "VW Multivan / Mercedes Vito",
            "description": "8인승 밴. 대가족·단체 여행에 최적.",
            "features": ["에어컨", "블루투스", "슬라이딩도어", "대형 트렁크"],
            "luggage_capacity": "대형 수하물 6개 이상",
            "image_url": "https://images.unsplash.com/photo-1533473359331-0135ef1b58bf?w=400&h=260&fit=crop",
        },
    ]
    results = []
    if tp_rental:
        results.append(tp_card)
    results.append(economy_card)
    for i, c in enumerate(candidates):
        if c["seats"] >= min_seats:
            recommended = c["seats"] >= recommended_seats
            results.append({
                "rental_id": c["rental_id"],
                "provider": c["provider"],
                "car_type": c["car_type"],
                "seats": c["seats"],
                "vehicle_name": c["vehicle_name"],
                "description": c["description"],
                "features": c["features"],
                "luggage_capacity": c["luggage_capacity"],
                "image_url": c["image_url"],
                "pickup_location": pickup,
                "dropoff_location": dropoff,
                "price_total_krw": None,
                "price_basis": "실시간 가격은 예약 사이트에서 확인",
                "recommended": recommended,
                "booking_url": eb_url,
            })
    if len(results) <= 1:
        # fallback: economy 카드만 있으면 차급 카드 추가
        fallback = candidates[-1]
        results.append({
            "rental_id": fallback["rental_id"],
            "provider": fallback["provider"],
            "car_type": fallback["car_type"],
            "seats": fallback["seats"],
            "vehicle_name": fallback["vehicle_name"],
            "description": fallback["description"],
            "features": fallback["features"],
            "luggage_capacity": fallback["luggage_capacity"],
            "image_url": fallback["image_url"],
            "pickup_location": pickup,
            "dropoff_location": dropoff,
            "price_total_krw": None,
            "price_basis": "실시간 가격은 예약 사이트에서 확인",
            "recommended": True,
            "booking_url": eb_url,
        })
    return results

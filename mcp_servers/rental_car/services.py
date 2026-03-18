"""Rental car search logic - shared by MCP server and agents."""

import math

# 차급별 최대 탑승 인원 (compact=4, sedan=5, suv=7, van=8)
_CAR_SEATS = {"compact": 4, "sedan": 5, "suv": 7, "van": 8, "minivan": 8}

# 여행 가방 고려: 일행 x 1.5 좌석 → "추천" 배지. 최소 seats >= passengers 인 차량은 모두 표시
_CAPACITY_MULTIPLIER = 1.5

# Mock 가격: 일당 8만원 기준 예상 (실제 예약 시 사이트별 상이)
_PRICE_PER_DAY_KRW = 80000

# 공항코드 → Rentalcars 경로 (나라/공항코드)
_AIRPORT_TO_RENTALCARS = {
    "MXP": ("it", "mxp"), "FCO": ("it", "fco"), "NAP": ("it", "nap"),
    "ICN": ("kr", "icn"), "GMP": ("kr", "gmp"),
    "NRT": ("jp", "nrt"), "HND": ("jp", "hnd"), "KIX": ("jp", "kix"),
    "LHR": ("gb", "lhr"), "LGW": ("gb", "lgw"),
    "CDG": ("fr", "cdg"), "ORY": ("fr", "ory"),
    "FRA": ("de", "fra"), "MUC": ("de", "muc"),
    "BCN": ("es", "bcn"), "MAD": ("es", "mad"), "AGP": ("es", "agp"),
    "AMS": ("nl", "ams"), "SIN": ("sg", "sin"), "BKK": ("th", "bkk"),
}
DEFAULT_COUNTRY = "us"  # Rentalcars 기본


def _min_car_type_for_passengers(required_seats: int) -> str:
    """필요 좌석 수에 맞는 최소 차급."""
    if required_seats <= 4:
        return "compact"
    if required_seats <= 5:
        return "sedan"
    if required_seats <= 7:
        return "suv"
    return "van"


def _build_booking_url(
    pickup: str,
    dropoff: str,
    start_date: str,
    end_date: str,
    travelers: int = 1,
) -> str:
    """검색 조건(픽업·반납·날짜·인원)이 반영된 예약 사이트 URL.
    Rentalcars.com 공항 페이지 + 날짜 파라미터 시도.
    """
    pickup_upper = (pickup or "").strip().upper()[:3]
    country, code = _AIRPORT_TO_RENTALCARS.get(
        pickup_upper, (DEFAULT_COUNTRY, pickup_upper.lower() if pickup_upper else "search")
    )
    rc_base = f"https://www.rentalcars.com/us/airport/{country}/{code}/"
    # 날짜가 있으면 쿼리 파라미터 추가 (사이트 지원 시 검색 폼 자동 채움)
    if start_date and len(start_date) >= 10 and end_date and len(end_date) >= 10:
        from urllib.parse import urlencode
        q = urlencode({
            "pickupDate": start_date[:10],
            "dropoffDate": end_date[:10],
            "driverAge": 30,
        })
        return f"{rc_base}?{q}"
    return rc_base


def mock_search_rentals(
    pickup: str,
    dropoff: str,
    car_type: str,
    days: int = 3,
    passengers: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    """Generate mock rental car results.
    - 일행이 탑승 가능한(seats >= passengers) 차량은 모두 표시
    - 일행 x 1.5 좌석 이상은 recommended 표시 (여행가방 여유)
    - 가격: 일당 8만원 기준 예상 (실제 예약 시 사이트별 상이)
    """
    base = _PRICE_PER_DAY_KRW * days
    raw_seats = passengers or 1
    min_seats = raw_seats  # 최소: 일행이 탈 수 있어야 함
    recommended_seats = max(min_seats, math.ceil(raw_seats * _CAPACITY_MULTIPLIER))

    start_d = start_date or ""
    end_d = end_date or start_d

    # 차량별 상세 정보 (모델명, 설명, 특징, 수하물, 사진)
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
    for i, c in enumerate(candidates):
        if c["seats"] >= min_seats:
            price = base + (i * 15000) - (5000 if c["car_type"] == "compact" else 0)
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
                "price_total_krw": price,
                "price_basis": f"일당 약 {_PRICE_PER_DAY_KRW:,}원 기준 예상 (실제 가격과 다를 수 있음)",
                "recommended": recommended,
                "booking_url": _build_booking_url(pickup, dropoff, start_d, end_d, travelers=raw_seats),
            })
    if not results:
        # fallback: 최소 한 건 (가장 큰 차량)
        fallback = candidates[-1]
        results = [{
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
            "price_total_krw": base + 20000,
            "price_basis": f"일당 약 {_PRICE_PER_DAY_KRW:,}원 기준 예상 (실제 가격과 다를 수 있음)",
            "recommended": True,
            "booking_url": _build_booking_url(pickup, dropoff, start_d, end_d, travelers=raw_seats),
        }]
    return results

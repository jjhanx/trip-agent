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

# IATA → (도시명, ISO 국가코드) — SerpApi 검색·현지어 쿼리용
_AIRPORT_TO_CITY: dict[str, tuple[str, str]] = {
    "MXP": ("Milan", "IT"),
    "FCO": ("Rome", "IT"),
    "NAP": ("Naples", "IT"),
    "ICN": ("Seoul", "KR"),
    "GMP": ("Seoul", "KR"),
    "NRT": ("Tokyo", "JP"),
    "HND": ("Tokyo", "JP"),
    "KIX": ("Osaka", "JP"),
    "LHR": ("London", "GB"),
    "LGW": ("London", "GB"),
    "CDG": ("Paris", "FR"),
    "ORY": ("Paris", "FR"),
    "FRA": ("Frankfurt", "DE"),
    "MUC": ("Munich", "DE"),
    "BCN": ("Barcelona", "ES"),
    "MAD": ("Madrid", "ES"),
    "AGP": ("Malaga", "ES"),
    "AMS": ("Amsterdam", "NL"),
    "SIN": ("Singapore", "SG"),
    "BKK": ("Bangkok", "TH"),
    "DUB": ("Dublin", "IE"),
    "DXB": ("Dubai", "AE"),
    "MCO": ("Orlando", "US"),
    "MIA": ("Miami", "US"),
    "LAX": ("Los Angeles", "US"),
    "JFK": ("New York", "US"),
    "MEL": ("Melbourne", "AU"),
    "SYD": ("Sydney", "AU"),
    "LIS": ("Lisbon", "PT"),
}

# ISO 국가 → SerpApi 보조 검색어 (현지어)
_COUNTRY_RENTAL_QUERY: dict[str, str] = {
    "IT": "noleggio auto",
    "FR": "location voiture",
    "DE": "mietwagen",
    "ES": "alquiler coche",
    "KR": "렌트카",
    "JP": "レンタカー",
    "GB": "car hire",
    "NL": "autohuur",
    "PT": "rent a car",
    "TH": "car rental",
    "SG": "car rental",
    "AU": "car hire",
    "US": "car rental",
    "AE": "car rental",
    "IE": "car hire",
}


def _vehicle_class_guide_cards(
    eb_url: str,
    pickup: str,
    dropoff: str,
    passengers: int,
    start_d: str,
    end_d: str,
    days: int,
) -> list[dict]:
    """차급별 대표 스펙(참고). 가격은 API 없이 불가 → 동일 EB URL로 실시간 조회 유도."""
    pax = max(1, passengers)
    need_bags = math.ceil(pax * _CAPACITY_MULTIPLIER)
    tiers: list[dict] = [
        {
            "rental_id": "CLASS-COMPACT",
            "car_type": "compact",
            "seats": 4,
            "vehicle_name": "소형 (Compact / CDMR·ECMR급)",
            "description": (
                "2~4인·가벼운 짐에 적합. 도심 주차·연비 유리. "
                f"대여 {days}일 기준 실제 총액은 차량·보험·옵션별로 사이트에서 확정됩니다."
            ),
            "features": ["에어컨", "일반적으로 4인 정원", "후방센서/카메라(차종별)"],
            "luggage_capacity": "중형 수하물 약 2개",
            "image_url": "https://images.unsplash.com/photo-1552519507-da3b142c6e3d?w=400&h=260&fit=crop",
        },
        {
            "rental_id": "CLASS-SEDAN",
            "car_type": "sedan",
            "seats": 5,
            "vehicle_name": "중형 세단 (Intermediate / IDMR급)",
            "description": (
                "4~5인 가족에 무난. 장거리·고속 안정감. "
                "트렁크는 SUV보다 다소 제한적일 수 있습니다."
            ),
            "features": ["에어컨", "5인 정원", "크루즈(차종별)"],
            "luggage_capacity": "중형 수하물 약 3개",
            "image_url": "https://images.unsplash.com/photo-1605559424843-9e4c228bf1c2?w=400&h=260&fit=crop",
        },
        {
            "rental_id": "CLASS-SUV",
            "car_type": "suv",
            "seats": 7,
            "vehicle_name": "SUV · 7인승 (Fullsize / FVMR급 예시)",
            "description": (
                "3열 또는 넉넉한 5인+짐. 가족·장기 여행에 흔히 선택. "
                "일부 차종은 5인만 가능하므로 필터에서 좌석 수를 확인하세요."
            ),
            "features": ["에어컨", "최대 7인(차종별)", "높은 적재 공간"],
            "luggage_capacity": "대형 수하물 4~5개(2열 사용 시)",
            "image_url": "https://images.unsplash.com/photo-1519641471654-76ce0107ad1b?w=400&h=260&fit=crop",
        },
        {
            "rental_id": "CLASS-VAN",
            "car_type": "van",
            "seats": 8,
            "vehicle_name": "밴 · 8~9인승 (Passenger van)",
            "description": (
                "대가족·단체. 미니밴/패신저 밴. "
                "짐이 많으면 3열 접거나 밴 전용 클래스를 선택하세요."
            ),
            "features": ["에어컨", "슬라이딩 도어(차종별)", "넉넉한 실내 높이"],
            "luggage_capacity": "대형 수하물 6개 이상(좌석 배치에 따라 상이)",
            "image_url": "https://images.unsplash.com/photo-1533473359331-0135ef1b58bf?w=400&h=260&fit=crop",
        },
    ]
    out: list[dict] = []
    for t in tiers:
        seats = t["seats"]
        fits_pax = seats >= pax
        rec_bags = seats >= need_bags
        out.append({
            "rental_id": t["rental_id"],
            "offer_kind": "vehicle_class_guide",
            "provider": "차급 스펙 (가격은 링크에서)",
            "car_type": t["car_type"],
            "seats": seats,
            "vehicle_name": t["vehicle_name"],
            "description": t["description"],
            "features": t["features"],
            "luggage_capacity": t["luggage_capacity"],
            "image_url": t["image_url"],
            "pickup_location": pickup,
            "dropoff_location": dropoff,
            "price_total_krw": None,
            "price_basis": (
                f"픽업 {start_d} ~ 반납 {end_d}({days}일) 동일 조건으로 EconomyBookings에서 "
                "이 차급(또는 유사 ACRISS)을 고르면 실시간 총액·옵션이 표시됩니다."
            ),
            "recommended": rec_bags and fits_pax,
            "booking_url": eb_url,
            "source_label": "차급 참고 · EconomyBookings 동일 검색",
            "fits_passengers": fits_pax,
        })
    out.sort(
        key=lambda c: (
            0 if c.get("fits_passengers") else 1,
            0 if c.get("recommended") else 1,
            -int(c.get("seats") or 0),
        )
    )
    for c in out:
        c.pop("fits_passengers", None)
    return out


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


def search_rentals_combined(
    pickup: str,
    dropoff: str,
    car_type: str,
    days: int = 3,
    passengers: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    travelpayouts_rental_booking_url: str | None = None,
    pickup_datetime: str | None = None,
    dropoff_datetime: str | None = None,
    pickup_airport_iata: str | None = None,
    amadeus_client_id: str | None = None,
    amadeus_client_secret: str | None = None,
    serpapi_api_key: str | None = None,
) -> list[dict]:
    """렌트 단계: SerpApi 후보(가격 힌트 가능) → 차급별 스펙 카드(EB 동일 링크) → 비교·제휴.

    Amadeus 트랜스퍼는 렌트 UX와 겹쳐 혼란을 주어 호출하지 않습니다.
    """
    raw_seats = passengers or 1
    start_d = (start_date or "")[:10]
    end_d = (end_date or start_d)[:10]
    eb_url = _build_economybookings_url(pickup, dropoff, start_d, end_d)

    tp_rental = (travelpayouts_rental_booking_url or "").strip()
    tp_card = {
        "rental_id": "TP-AFFILIATE",
        "offer_kind": "affiliate",
        "provider": "Travelpayouts 제휴 렌트카",
        "car_type": "다양",
        "seats": 9,
        "vehicle_name": "제휴 파트너 검색",
        "description": "대시보드에서 생성한 제휴 링크입니다. 픽업·날짜·실시간 가격은 해당 사이트에서 확인하세요.",
        "features": ["제휴 링크", "실시간 가격"],
        "luggage_capacity": "차종별 상이",
        "image_url": "https://images.unsplash.com/photo-1449965408869-eaa3f722e40d?w=400&h=260&fit=crop",
        "pickup_location": pickup,
        "dropoff_location": dropoff,
        "price_total_krw": None,
        "price_basis": "실시간 가격은 제휴 사이트에서 확인",
        "recommended": False,
        "booking_url": tp_rental,
    }

    economy_card = {
        "rental_id": "EB-COMPARE",
        "offer_kind": "self_drive_compare",
        "provider": "EconomyBookings",
        "car_type": "다양",
        "seats": 9,
        "vehicle_name": "전체 업체 비교 (필터로 차급·가격)",
        "description": (
            f"픽업 {start_d} ~ 반납 {end_d} · URL에 날짜 반영. "
            "차급·인승·보험 필터로 **실시간 총액**을 확인하세요."
        ),
        "features": ["실시간 총액", "600+ 업체", "차급·좌석 필터"],
        "luggage_capacity": "차급별 상이",
        "image_url": "https://images.unsplash.com/photo-1449965408869-eaa3f722e40d?w=400&h=260&fit=crop",
        "pickup_location": pickup,
        "dropoff_location": dropoff,
        "price_total_krw": None,
        "price_basis": "위 차급 카드와 동일 검색 조건입니다. 여기서 전체 최저가를 비교할 수 있습니다.",
        "recommended": False,
        "booking_url": eb_url,
        "source_label": "EconomyBookings",
    }

    results: list[dict] = []
    serpapi_cards: list[dict] = []

    iata = (pickup_airport_iata or "").strip().upper()[:3]
    if len(iata) != 3 and pickup:
        p = pickup.strip().upper()
        if len(p) == 3 and p.isalpha():
            iata = p

    sk = (serpapi_api_key or "").strip()
    if sk and len(iata) == 3 and len(start_d) >= 10 and len(end_d) >= 10:
        from mcp_servers.rental_car.serpapi_rental import search_serpapi_rental_offers

        city_t = _AIRPORT_TO_CITY.get(iata)
        city_name = city_t[0] if city_t else None
        country_gl = (city_t[1] if city_t else "US").lower()
        cc = (city_t[1] if city_t else "US").upper()
        local_kw = _COUNTRY_RENTAL_QUERY.get(cc, "car rental")
        serpapi_cards = search_serpapi_rental_offers(
            sk,
            iata,
            city_name,
            country_gl,
            start_d,
            end_d,
            days=max(1, days),
            passengers=raw_seats,
            max_results=12,
            local_rental_keyword=local_kw,
        )

    vehicle_cards = _vehicle_class_guide_cards(
        eb_url, pickup, dropoff, raw_seats, start_d, end_d, max(1, days)
    )

    results.extend(serpapi_cards)
    results.extend(vehicle_cards)
    results.append(economy_card)
    if tp_rental:
        results.append(tp_card)

    return results


def mock_search_rentals(
    pickup: str,
    dropoff: str,
    car_type: str,
    days: int = 3,
    passengers: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    travelpayouts_rental_booking_url: str | None = None,
    pickup_datetime: str | None = None,
    dropoff_datetime: str | None = None,
    pickup_airport_iata: str | None = None,
    amadeus_client_id: str | None = None,
    amadeus_client_secret: str | None = None,
    serpapi_api_key: str | None = None,
) -> list[dict]:
    """search_rentals_combined 별칭 (기존 호출부 호환)."""
    return search_rentals_combined(
        pickup=pickup,
        dropoff=dropoff,
        car_type=car_type,
        days=days,
        passengers=passengers,
        start_date=start_date,
        end_date=end_date,
        travelpayouts_rental_booking_url=travelpayouts_rental_booking_url,
        pickup_datetime=pickup_datetime,
        dropoff_datetime=dropoff_datetime,
        pickup_airport_iata=pickup_airport_iata,
        amadeus_client_id=amadeus_client_id,
        amadeus_client_secret=amadeus_client_secret,
        serpapi_api_key=serpapi_api_key,
    )

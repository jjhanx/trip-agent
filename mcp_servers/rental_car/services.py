"""Rental car search logic - shared by MCP server and agents."""

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

# IATA → (도시명, ISO 국가코드) — Amadeus Transfer 시내 구간 끝점
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
    """렌트 단계: SerpApi(Google) 셀프 드라이브 후보 링크·가격 힌트, Amadeus 트랜스퍼, 비교·제휴 링크.

    공개 렌트카 JSON 쇼핑 API가 없어, SerpApi로 일정·일행이 반영된 검색의 organic 결과를 카드화합니다.
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
        "vehicle_name": "셀프 드라이브 · 기간 총액 비교",
        "description": (
            f"픽업 {start_d} ~ 반납 {end_d} 일정이 URL에 반영됩니다. "
            "600+ 업체 실시간 가격·차종·가용성을 비교하세요."
        ),
        "features": ["실시간 가격", "600+ 업체", "가격 비교"],
        "luggage_capacity": "차종별 상이",
        "image_url": "https://images.unsplash.com/photo-1449965408869-eaa3f722e40d?w=400&h=260&fit=crop",
        "pickup_location": pickup,
        "dropoff_location": dropoff,
        "price_total_krw": None,
        "price_basis": "셀프 드라이브 렌트의 기간 총액은 예약 사이트에서 확인하세요.",
        "recommended": True,
        "booking_url": eb_url,
    }

    results: list[dict] = []
    amadeus_cards: list[dict] = []
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
        )

    aid = (amadeus_client_id or "").strip()
    asec = (amadeus_client_secret or "").strip()
    if aid and asec and iata in _AIRPORT_TO_CITY:
        city, country = _AIRPORT_TO_CITY[iata]
        from mcp_servers.rental_car.amadeus_transfer import (
            search_airport_to_city,
            search_city_to_airport,
        )

        pdt = (pickup_datetime or "").strip()
        ddt = (dropoff_datetime or "").strip()
        if len(pdt) >= 16:
            amadeus_cards.extend(
                search_airport_to_city(
                    iata, pdt, city, country, raw_seats, aid, asec, max_offers=6
                )
            )
        if len(ddt) >= 16:
            amadeus_cards.extend(
                search_city_to_airport(
                    iata, ddt, city, country, raw_seats, aid, asec, max_offers=6
                )
            )

    amadeus_cards.sort(key=lambda x: x.get("price_total_krw") or 0)
    results.extend(serpapi_cards)
    results.extend(amadeus_cards)

    if tp_rental:
        results.append(tp_card)
    results.append(economy_card)

    pdt_s = (pickup_datetime or "").strip()
    ddt_s = (dropoff_datetime or "").strip()
    attempted_amadeus = len(pdt_s) >= 16 or len(ddt_s) >= 16
    if (
        not amadeus_cards
        and not serpapi_cards
        and aid
        and asec
        and attempted_amadeus
    ):
        if len(iata) == 3 and iata not in _AIRPORT_TO_CITY:
            hint_desc = "이 공항 코드는 앱의 시내 매핑에 없어 트랜스퍼 API를 호출하지 않았습니다."
        else:
            hint_desc = (
                "Amadeus 테스트 환경은 일부 구간만 지원합니다. "
                "셀프 드라이브는 EconomyBookings 링크에서 확인하세요."
            )
        results.insert(
            0,
            {
                "rental_id": "AMADEUS-HINT",
                "offer_kind": "info",
                "provider": "견적 안내",
                "car_type": "info",
                "seats": raw_seats,
                "vehicle_name": "트랜스퍼 자동 견적 없음",
                "description": hint_desc,
                "features": [],
                "luggage_capacity": "",
                "image_url": None,
                "pickup_location": pickup,
                "dropoff_location": dropoff,
                "price_total_krw": None,
                "price_basis": "AMADEUS_CLIENT_ID/SECRET·픽업 일시·공항(IATA)을 확인해 주세요.",
                "recommended": False,
                "booking_url": None,
            },
        )

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

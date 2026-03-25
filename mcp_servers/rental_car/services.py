"""Rental car search logic - shared by MCP server and agents."""

import logging
import math
from urllib.parse import urlencode

from mcp_servers.rental_car.economybookings_hint import (
    daily_to_total_krw_hint,
    fetch_lowest_daily_eur,
)
from mcp_servers.rental_car.economybookings_links import build_airport_landing_url
from mcp_servers.rental_car.travelpayouts_economybookings import (
    apply_economybookings_tracking_to_url,
    fetch_economybookings_tracking_params,
    is_travelpayouts_economybookings_gateway,
)

logger = logging.getLogger(__name__)

# 차급별 최대 탑승 인원 (compact=4, sedan=5, suv=7, van=8)
_CAR_SEATS = {"compact": 4, "sedan": 5, "suv": 7, "van": 8, "minivan": 8}

# 여행 가방 고려: 일행 x 1.5 좌석 → "추천" 배지. 최소 seats >= passengers 인 차량은 모두 표시
_CAPACITY_MULTIPLIER = 1.5

# Travelpayouts 렌트 제휴 URL이 항공 검색으로 잘못 설정된 경우 목록에서 제외
_TP_FLIGHT_URL_MARKERS = (
    "/flights",
    "travel/flights",
    "google.com/flights",
    "kayak.com/flights",
    "skyscanner.net/transport/flights",
    "skyscanner.com/transport/flights",
    "expedia.com/flights",
    "booking.com/flights",
    "cheapoair.com",
    "momondo.com/flight",
)


def _travelpayouts_rental_url_valid(url: str) -> bool:
    u = (url or "").strip().lower()
    if not u.startswith("http"):
        return False
    if any(m in u for m in _TP_FLIGHT_URL_MARKERS):
        return False
    if "aviasales." in u or "aviasales/" in u:
        if not any(k in u for k in ("car", "rent", "rental", "cars", "авто")):
            return False
    return True


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


def _hhmm_from_iso(dt: str | None, default: str = "10:00") -> str:
    s = (dt or "").strip()
    if len(s) >= 16 and s[10] in " Tt":
        return s[11:16]
    if len(s) == 5 and s[2] == ":":
        return s
    return default


def _fmt_rental_display_datetime(iso: str | None) -> str | None:
    s = (iso or "").strip().replace(" ", "T")
    if len(s) >= 16:
        return s[:16].replace("T", " ")
    return None


def _rental_schedule_payload(
    pickup_dt: str | None,
    dropoff_dt: str | None,
    passengers: int,
    airport_iata: str,
    start_d: str,
    end_d: str,
) -> dict:
    """모든 렌트 카드에 동일하게 붙여 UI·제휴 링크 맥락을 드러냄."""
    pax = max(1, int(passengers) if passengers else 1)
    iata = (airport_iata or "").strip().upper()[:3]
    ds = (start_d or "")[:10]
    de = (end_d or ds)[:10]
    pu = _fmt_rental_display_datetime(pickup_dt)
    du = _fmt_rental_display_datetime(dropoff_dt)
    out: dict = {
        "rental_party_passengers": pax,
        "rental_date_start": ds if len(ds) >= 10 else None,
        "rental_date_end": de if len(de) >= 10 else None,
        "rental_pickup_datetime": pu,
        "rental_dropoff_datetime": du,
        "rental_pickup_airport_iata": iata if len(iata) == 3 else None,
    }
    segs: list[str] = []
    if len(iata) == 3:
        segs.append(iata)
    if pu:
        segs.append(f"픽업 {pu}")
    elif len(ds) >= 10:
        segs.append(f"픽업일 {ds} {_hhmm_from_iso(pickup_dt)}")
    if du:
        segs.append(f"반납 {du}")
    elif len(de) >= 10:
        segs.append(f"반납일 {de} {_hhmm_from_iso(dropoff_dt)}")
    segs.append(f"일행 {pax}명")
    out["rental_schedule_line"] = " · ".join(segs)
    return out


def _filter_tiers_for_party(tiers: list[dict], pax: int) -> list[dict]:
    """좌석 정원이 [일행, ceil(일행×1.5)]에 들어가는 차급만 우선.

    해당 구간에 차급이 없으면(소형차만 있고 상한이 3인승 등) 일행 이상 탑승 가능한 **가장 작은 정원** 티어만 반환.
    일행이 최대 티어보다 많으면 최대 티어 1개(안내용).
    """
    pax = max(1, pax)
    low = pax
    high = max(low, math.ceil(pax * _CAPACITY_MULTIPLIER))
    ideal = [t for t in tiers if low <= int(t["seats"]) <= high]
    if ideal:
        return sorted(ideal, key=lambda t: int(t["seats"]))
    adequate = [t for t in tiers if int(t["seats"]) >= low]
    if adequate:
        min_seats = min(int(t["seats"]) for t in adequate)
        picked = [t for t in adequate if int(t["seats"]) == min_seats]
        return sorted(picked, key=lambda t: t["rental_id"])
    return [max(tiers, key=lambda t: int(t["seats"]))]


def _build_economybookings_url(
    pickup: str,
    dropoff: str,
    start_date: str,
    end_date: str,
    pickup_datetime: str | None = None,
    dropoff_datetime: str | None = None,
) -> str:
    """공항 SEO 랜딩 URL (mergedLocationId 조회·가격 스크레이프 폴백용)."""
    pickup_upper = (pickup or "").strip().upper()[:3]
    path = _AIRPORT_TO_ECONOMYBOOKINGS.get(pickup_upper)
    pt = _hhmm_from_iso(pickup_datetime)
    dt = _hhmm_from_iso(dropoff_datetime)
    sd = (start_date or "")[:10]
    ed = (end_date or sd)[:10]
    if path:
        region, country, city, airport = path
        return build_airport_landing_url(region, country, city, airport, sd, ed, pt, dt)
    base = "https://www.economybookings.com/en/car-rental/all"
    if len(sd) >= 10 and len(ed) >= 10:
        return f"{base}?{urlencode({'pickup_date': sd, 'dropoff_date': ed, 'pickup_time': pt, 'dropoff_time': dt, 'return_time': dt})}"
    return base


def _build_economybookings_car_type_url(
    country_slug: str,
    city_slug: str,
    eb_slug: str,
    start_date: str,
    end_date: str,
    pickup_datetime: str | None,
    dropoff_datetime: str | None,
) -> str:
    """EconomyBookings 차급(영문) + 도시 경로 + 날짜·시각."""
    base = f"https://www.economybookings.com/en/car-types/{eb_slug}/{country_slug}/{city_slug}"
    if start_date and len(start_date) >= 10 and end_date and len(end_date) >= 10:
        pt = _hhmm_from_iso(pickup_datetime)
        dt = _hhmm_from_iso(dropoff_datetime)
        q = urlencode({
            "pickup_date": start_date[:10],
            "dropoff_date": end_date[:10],
            "pickup_time": pt,
            "dropoff_time": dt,
            "return_time": dt,
        })
        return f"{base}?{q}"
    return base


def _min_serp_price_krw(serp_cards: list[dict]) -> int | None:
    vals = [int(c["price_total_krw"]) for c in serp_cards if c.get("price_total_krw")]
    return min(vals) if vals else None


def _vehicle_class_guide_cards(
    eb_user_booking_url: str,
    pickup: str,
    dropoff: str,
    passengers: int,
    start_d: str,
    end_d: str,
    days: int,
    pickup_datetime: str | None,
    dropoff_datetime: str | None,
    eb_path: tuple[str, str, str, str] | None,
    daily_eur_cache: dict[str, float | None] | None = None,
    eb_tracking_params: dict[str, str] | None = None,
) -> list[dict]:
    """일행·짐(×1.5) 범위에 맞는 차급만. 공항 매핑이 있으면 차급별 EB URL(날짜·시각 쿼리)로 버튼을 구분. 가격 힌트는 차급 소개 페이지 스크레이프."""
    pax = max(1, passengers)
    need_bags = math.ceil(pax * _CAPACITY_MULTIPLIER)
    country_slug: str | None = None
    city_slug: str | None = None
    if eb_path:
        country_slug = eb_path[1]
        city_slug = eb_path[2]

    tiers_all: list[dict] = [
        {
            "rental_id": "CLASS-COMPACT",
            "car_type": "compact",
            "eb_slug": "compact",
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
            "eb_slug": "midsize",
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
            "eb_slug": "suv",
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
            "eb_slug": "van",
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

    tiers = _filter_tiers_for_party(tiers_all, pax)
    track = eb_tracking_params or {}
    out: list[dict] = []
    for t in tiers:
        seats = int(t["seats"])
        fits_pax = seats >= pax
        rec_bags = seats >= need_bags
        desc = t["description"]
        if not fits_pax:
            desc += f" 일행 {pax}명 기준 정원이 부족할 수 있어 2대 또는 더 큰 클래스를 확인하세요."

        if country_slug and city_slug:
            car_type_url = _build_economybookings_car_type_url(
                country_slug,
                city_slug,
                str(t["eb_slug"]),
                start_d,
                end_d,
                pickup_datetime,
                dropoff_datetime,
            )
            scrape_url = car_type_url
            booking_url = apply_economybookings_tracking_to_url(car_type_url, track)
        else:
            scrape_url = eb_user_booking_url
            booking_url = eb_user_booking_url

        if daily_eur_cache is not None and scrape_url in daily_eur_cache:
            daily_eur = daily_eur_cache[scrape_url]
        else:
            daily_eur = fetch_lowest_daily_eur(scrape_url)
            if daily_eur_cache is not None:
                daily_eur_cache[scrape_url] = daily_eur
        price_krw: int | None = None
        if country_slug and city_slug:
            price_basis = (
                f"픽업 {start_d} ~ 반납 {end_d}({days}일). 예약 버튼은 이 차급 전용 EB 페이지(날짜·시각 쿼리)로 열립니다. "
                "가격 힌트는 동일 차급 소개 페이지 스니펫 기준입니다."
            )
        else:
            price_basis = (
                f"픽업 {start_d} ~ 반납 {end_d}({days}일). 버튼은 공항 랜딩(날짜·시각 쿼리)입니다. "
                "가격 숫자는 차급 소개 페이지 스니펫 기준입니다."
            )
        if daily_eur is not None:
            price_krw = daily_to_total_krw_hint(daily_eur, days)
            price_basis = (
                f"EconomyBookings 해당 차급 페이지에 표시된 From 일당(€) 중 최저 {daily_eur:.2f}€ × "
                f"{days}일 × 고정 환율로 추정한 총액 힌트입니다. 보험·옵션·실제 차종에 따라 달라집니다."
            )
        else:
            price_basis += " 가격 숫자는 페이지 로드 후 확인하거나 SerpApi 후보를 참고하세요."

        feats = list(t["features"])
        feats.insert(0, f"일행 {pax}명 · 짐·여유 좌석 기준 약 {need_bags}인승급 권장")

        out.append({
            "rental_id": t["rental_id"],
            "offer_kind": "vehicle_class_guide",
            "provider": "차급 스펙 · EconomyBookings",
            "car_type": t["car_type"],
            "seats": seats,
            "vehicle_name": t["vehicle_name"],
            "description": desc,
            "features": feats,
            "luggage_capacity": t["luggage_capacity"],
            "image_url": t["image_url"],
            "pickup_location": pickup,
            "dropoff_location": dropoff,
            "price_total_krw": price_krw,
            "price_is_estimate": bool(price_krw),
            "price_basis": price_basis,
            "recommended": rec_bags and fits_pax,
            "booking_url": booking_url,
            "source_label": "EconomyBookings · 차급 페이지(일정·시각 쿼리)",
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
    """렌트 단계: SerpApi 후보 → 차급별 EB 딥링크(차급·일정 구분) → 공항 비교 카드 → 제휴.

    Amadeus 트랜스퍼는 렌트 UX와 겹쳐 혼란을 주어 호출하지 않습니다.
    """
    raw_seats = passengers or 1
    start_d = (start_date or "")[:10]
    end_d = (end_date or start_d)[:10]

    iata = (pickup_airport_iata or "").strip().upper()[:3]
    if len(iata) != 3 and pickup:
        p = pickup.strip().upper()
        if len(p) == 3 and p.isalpha():
            iata = p
    pickup_code = iata if len(iata) == 3 else (pickup or "").strip().upper()[:3]

    eb_landing_url = _build_economybookings_url(
        pickup_code,
        dropoff,
        start_d,
        end_d,
        pickup_datetime,
        dropoff_datetime,
    )
    # cars/results?plc&py… 딥링크는 EB 쪽에서 빈 결과로 이어지는 사례가 있어, 사용자 링크는 공항 랜딩만 사용합니다.
    eb_booking_url = eb_landing_url
    eb_path = _AIRPORT_TO_ECONOMYBOOKINGS.get(pickup_code)

    tp_rental = (travelpayouts_rental_booking_url or "").strip()
    if tp_rental and not _travelpayouts_rental_url_valid(tp_rental):
        logger.warning(
            "TRAVELPAYOUTS_RENTAL_BOOKING_URL looks like a flight URL; skipping affiliate card. "
            "Use Travelpayouts dashboard → Cars (렌트카) deep link."
        )
        tp_rental = ""
    tp_track: dict[str, str] = {}
    if tp_rental and is_travelpayouts_economybookings_gateway(tp_rental):
        tp_track = fetch_economybookings_tracking_params(tp_rental)
    eb_booking_url = apply_economybookings_tracking_to_url(eb_landing_url, tp_track)
    affiliate_tracking_merged = bool(tp_track)

    tp_card = {
        "rental_id": "TP-AFFILIATE",
        "offer_kind": "affiliate",
        "provider": "Travelpayouts 제휴 렌트카",
        "car_type": "다양",
        "seats": 9,
        "vehicle_name": "Travelpayouts 제휴 진입",
        "description": (
            "EconomyBookings 제휴 숏링크입니다. 위 EconomyBookings·차급 카드 예약 링크에 "
            "동일 제휴 추적(btag·tpo_uid)이 붙어 있습니다."
            if affiliate_tracking_merged
            else (
                "Travelpayouts에서 받은 제휴 링크입니다. "
                "일정이 반영된 예약 링크는 위 EconomyBookings·차급 카드를 사용하세요."
            )
        ),
        "features": (
            ["제휴 홈·일반 검색", "일정 반영은 위 카드 권장"]
            if affiliate_tracking_merged
            else ["제휴 링크", "실시간 가격"]
        ),
        "luggage_capacity": "차종별 상이",
        "image_url": "https://images.unsplash.com/photo-1449965408869-eaa3f722e40d?w=400&h=260&fit=crop",
        "pickup_location": pickup,
        "dropoff_location": dropoff,
        "price_total_krw": None,
        "price_basis": "실시간 가격은 제휴 사이트에서 확인",
        "recommended": False,
        "booking_url": tp_rental,
    }

    econ_features = [
        "공항·날짜·시각 쿼리",
        "600+ 업체",
        "차급·좌석 필터",
    ]
    if affiliate_tracking_merged:
        econ_features.insert(0, "Travelpayouts 제휴 추적 포함 링크")

    _econ_extra = ""
    if affiliate_tracking_merged:
        _econ_extra = (
            " economybookings.tpk.ro 제휴 진입 URL에서 추출한 btag·tpo_uid를 이 링크에 병합했습니다."
        )
    elif tp_rental:
        _econ_extra = " Travelpayouts 렌트 제휴 링크가 설정되어 있습니다."

    economy_card = {
        "rental_id": "EB-COMPARE",
        "offer_kind": "self_drive_compare",
        "provider": "EconomyBookings",
        "car_type": "다양",
        "seats": 9,
        "vehicle_name": "전체 업체 비교 (필터로 차급·가격)",
        "description": (
            f"픽업 {start_d} ~ 반납 {end_d} · 공항 전용 페이지로 연결됩니다. "
            "URL에 픽업·반납 날짜와 시각이 붙어 있으면 사이트에서 입력이 일부 채워질 수 있습니다."
            + _econ_extra
        ),
        "features": econ_features,
        "luggage_capacity": "차급별 상이",
        "image_url": "https://images.unsplash.com/photo-1449965408869-eaa3f722e40d?w=400&h=260&fit=crop",
        "pickup_location": pickup,
        "dropoff_location": dropoff,
        "price_total_krw": None,
        "price_is_estimate": False,
        "price_basis": "",
        "recommended": False,
        "booking_url": eb_booking_url,
        "source_label": "EconomyBookings · 공항 전체 비교(일정·시각)"
        + (" · Travelpayouts" if affiliate_tracking_merged else ""),
    }

    results: list[dict] = []
    serpapi_cards: list[dict] = []

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

    d_days = max(1, days)
    eb_daily_cache: dict[str, float | None] = {}
    eb_daily_airport = fetch_lowest_daily_eur(eb_landing_url)
    eb_daily_cache[eb_landing_url] = eb_daily_airport
    eb_airport_krw = (
        daily_to_total_krw_hint(eb_daily_airport, d_days) if eb_daily_airport is not None else None
    )
    serp_min_krw = _min_serp_price_krw(serpapi_cards)
    hint_candidates = [x for x in (eb_airport_krw, serp_min_krw) if x is not None]
    if hint_candidates:
        economy_card["price_total_krw"] = min(hint_candidates)
        economy_card["price_is_estimate"] = True
        basis_parts: list[str] = []
        if eb_airport_krw is not None and eb_daily_airport is not None:
            basis_parts.append(
                f"EconomyBookings(결과·랜딩 페이지) From 일당 중 최저 약 {eb_daily_airport:.2f}€ × {d_days}일 "
                f"→ 표시용 환율로 총액 힌트 약 {eb_airport_krw:,}원 (보험·옵션 제외 가능)."
            )
        if serp_min_krw is not None:
            basis_parts.append(
                f"Google 검색(SerpApi) 후보 중 추정 총액 최저 약 {serp_min_krw:,}원. "
                "둘 중 낮은 값을 카드에 표시했습니다."
            )
        economy_card["price_basis"] = " ".join(basis_parts)
    else:
        economy_card["price_basis"] = (
            "가격 숫자 힌트를 만들지 못했습니다. SerpApi 키·네트워크를 확인하거나 링크에서 직접 확인하세요."
        )

    vehicle_cards = _vehicle_class_guide_cards(
        eb_booking_url,
        pickup,
        dropoff,
        raw_seats,
        start_d,
        end_d,
        d_days,
        pickup_datetime,
        dropoff_datetime,
        eb_path,
        eb_daily_cache,
        eb_tracking_params=tp_track,
    )

    results.extend(serpapi_cards)
    results.extend(vehicle_cards)
    results.append(economy_card)
    if tp_rental:
        results.append(tp_card)

    sched = _rental_schedule_payload(
        pickup_datetime,
        dropoff_datetime,
        raw_seats,
        pickup_code,
        start_d,
        end_d,
    )
    for item in results:
        item.update(sched)

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

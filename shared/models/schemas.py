"""Pydantic schemas for travel planning input and output."""

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class LocalTransportType(str, Enum):
    """현지 이동 수단."""

    RENTAL_CAR = "rental_car"
    PUBLIC_TRANSIT = "public_transit"


class AccommodationType(str, Enum):
    """숙소 형태 (별장, B&B, 부엌 있는 호텔, 산장 등 포함)."""

    HOTEL = "hotel"
    GUESTHOUSE = "guesthouse"
    HOSTEL = "hostel"
    APARTMENT = "apartment"
    RESORT = "resort"
    VILLA = "villa"
    BNB = "bnb"
    HOTEL_WITH_KITCHEN = "hotel_with_kitchen"
    MOUNTAIN_LODGE = "mountain_lodge"


class SeatClass(str, Enum):
    """항공 좌석 클래스."""

    ECONOMY = "economy"
    PREMIUM_ECONOMY = "premium_economy"
    BUSINESS = "business"
    FIRST = "first"


class TravelerComposition(BaseModel):
    """일행 구성 (성인 남·여, 아동)."""

    male: int = Field(default=1, ge=0, description="성인 남성 인원")
    female: int = Field(default=0, ge=0, description="성인 여성 인원")
    children: int = Field(default=0, ge=0, description="아동 인원")


class TravelPreference(BaseModel):
    """여행 취향."""

    interests: list[str] = Field(default_factory=list, description="관심사 (관광, 음식, 자연 등)")
    pace: str = Field(default="medium", description="여행 속도 (relaxed, medium, packed)")
    budget_level: str = Field(default="moderate", description="예산 수준 (budget, moderate, luxury)")
    extra_notes: str = Field(default="", description="추가 메모")


class TravelInput(BaseModel):
    """사용자 여행 입력.

    - origin/destination: 공항 코드 또는 도시/관광지 이름. 8시간 이상 거리 시
      origin_airport_code, destination_airport_code로 선택된 공항 사용.
    - end_date: '귀국일'이 아닌 '귀환일' (국내 여행 등 포함).
    - date_flexibility_days: +/- 허용 일수 (최저가 검색 등).
    - accommodation_priority: 선호 숙소 형태 3순위 (혼합 후보 제시).
    - start_time_preference: 별도 질문하지 않음. 도착 빠를수록 현지 선택폭 고려.
    """

    destination: str = Field(..., description="목적지 (공항 코드 또는 도시/관광지)")
    origin: str = Field(..., description="출발지 (공항 코드 또는 도시/관광지)")
    start_date: date = Field(..., description="출발일")
    end_date: date = Field(..., description="귀환일")
    trip_type: str = Field(
        default="round_trip", description="여정 타입 (round_trip, one_way, multi_city)"
    )
    date_flexibility_days: int | None = Field(
        None, description="날짜 유연성: +/- 허용 일수 (최저가 검색 등)"
    )
    origin_airport_code: str | None = Field(
        None, description="선택된 출발 공항 코드 (8시간 이내 접근 가능 공항 중 선택)"
    )
    destination_airport_code: str | None = Field(
        None, description="선택된 도착 공항 코드"
    )
    destination_airports: list[str] | None = Field(
        None, description="검색할 도착 공항 목록 (마일리지 직항 우선순, 다중 검색 시)"
    )
    start_time_preference: str | None = Field(
        None, description="출발 시간 선호 (미질문, 일정 설계 시 조기 도착 우선 고려)"
    )
    preference: TravelPreference = Field(default_factory=TravelPreference)
    mileage_balance: int = Field(default=0, description="보유 마일리지")
    mileage_program: str | None = Field(None, description="마일리지 프로그램명")
    seat_class: SeatClass = Field(default=SeatClass.ECONOMY)
    use_miles: bool = Field(default=False, description="마일리지 사용 여부")
    local_transport: LocalTransportType = Field(..., description="현지 이동 방법")
    accommodation_type: AccommodationType = Field(
        default=AccommodationType.HOTEL, description="선호 숙소 형태 (1순위)"
    )
    accommodation_priority: list[AccommodationType] = Field(
        default_factory=lambda: [AccommodationType.HOTEL],
        description="숙소 형태 선호 우선순위 (최대 3개, 혼합 후보 제시)",
    )
    travelers: TravelerComposition = Field(
        default_factory=TravelerComposition,
        description="일행 구성 (성인 남·여, 아동)",
    )
    multi_cities: list[dict] | None = Field(
        None,
        description="다구간 여정: [{origin, destination, date}, ...]",
    )


class FlightResult(BaseModel):
    """항공편 검색 결과."""

    flight_id: str
    airline: str
    flight_number: str
    departure: datetime
    arrival: datetime
    origin: str
    destination: str
    price_krw: int | None = None
    miles_required: int | None = None
    seat_class: SeatClass = SeatClass.ECONOMY


class DayActivity(BaseModel):
    """일정 내 하루 활동."""

    date: date
    title: str
    description: str
    location: str | None = None
    needs_accommodation: bool = False


class ItineraryOption(BaseModel):
    """일정안."""

    option_id: str
    title: str
    summary: str
    daily_activities: list[DayActivity] = Field(default_factory=list)
    accommodation_nights: list[tuple[date, str]] = Field(
        default_factory=list, description="(날짜, 지역) 숙박 필요 구간"
    )


class AccommodationOption(BaseModel):
    """숙소 후보."""

    hotel_id: str
    name: str
    location: str
    price_per_night_krw: int | None = None
    rating: float | None = None
    accommodation_type: AccommodationType = AccommodationType.HOTEL
    amenities: list[str] = Field(default_factory=list)


class RentalCarOption(BaseModel):
    """렌트카 후보."""

    rental_id: str
    provider: str
    car_type: str
    pickup_location: str
    dropoff_location: str
    price_total_krw: int | None = None
    seats: int | None = Field(None, description="최대 탑승 인원")
    vehicle_name: str | None = Field(None, description="예시 차량 모델명")
    description: str | None = Field(None, description="차량 설명")
    features: list[str] | None = Field(None, description="편의 기능 목록")
    luggage_capacity: str | None = Field(None, description="수하물 적재량")
    image_url: str | None = Field(None, description="차량 이미지 URL")
    booking_url: str | None = Field(None, description="검색 날짜·조건 반영 예약 사이트 URL")
    price_basis: str | None = Field(None, description="가격 산정 근거 설명")
    recommended: bool | None = Field(None, description="여행가방 고려 추천 여부")


class TransitOption(BaseModel):
    """대중교통 옵션."""

    route_id: str
    description: str
    duration_minutes: int
    pass_name: str | None = None
    pass_price_krw: int | None = None

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
    """숙소 형태."""

    HOTEL = "hotel"
    GUESTHOUSE = "guesthouse"
    HOSTEL = "hostel"
    APARTMENT = "apartment"
    RESORT = "resort"


class SeatClass(str, Enum):
    """항공 좌석 클래스."""

    ECONOMY = "economy"
    PREMIUM_ECONOMY = "premium_economy"
    BUSINESS = "business"
    FIRST = "first"


class TravelPreference(BaseModel):
    """여행 취향."""

    interests: list[str] = Field(default_factory=list, description="관심사 (관광, 음식, 자연 등)")
    pace: str = Field(default="medium", description="여행 속도 (relaxed, medium, packed)")
    budget_level: str = Field(default="moderate", description="예산 수준 (budget, moderate, luxury)")
    extra_notes: str = Field(default="", description="추가 메모")


class TravelInput(BaseModel):
    """사용자 여행 입력."""

    destination: str = Field(..., description="여행 지역")
    origin: str = Field(..., description="출발지")
    start_date: date = Field(..., description="출발일")
    end_date: date = Field(..., description="귀국일")
    start_time_preference: str | None = Field(None, description="출발 시간 선호 (morning, afternoon, evening)")
    preference: TravelPreference = Field(default_factory=TravelPreference)
    mileage_balance: int = Field(default=0, description="보유 마일리지")
    mileage_program: str | None = Field(None, description="마일리지 프로그램명")
    seat_class: SeatClass = Field(default=SeatClass.ECONOMY)
    use_miles: bool = Field(default=False, description="마일리지 사용 여부")
    local_transport: LocalTransportType = Field(..., description="현지 이동 방법")
    accommodation_type: AccommodationType = Field(
        default=AccommodationType.HOTEL, description="선호 숙소 형태"
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


class TransitOption(BaseModel):
    """대중교통 옵션."""

    route_id: str
    description: str
    duration_minutes: int
    pass_name: str | None = None
    pass_price_krw: int | None = None

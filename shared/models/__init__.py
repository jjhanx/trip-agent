"""Pydantic models for travel planning."""

from .schemas import (
    TravelInput,
    TravelPreference,
    FlightResult,
    ItineraryOption,
    AccommodationOption,
    RentalCarOption,
    TransitOption,
    LocalTransportType,
    AccommodationType,
    SeatClass,
)

__all__ = [
    "TravelInput",
    "TravelPreference",
    "FlightResult",
    "ItineraryOption",
    "AccommodationOption",
    "RentalCarOption",
    "TransitOption",
    "LocalTransportType",
    "AccommodationType",
    "SeatClass",
]

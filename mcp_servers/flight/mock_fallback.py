"""Mock flight data - API 미설정 또는 한도 초과 시 사용."""

from datetime import datetime, timedelta

DOMESTIC_PAIRS = {
    ("ICN", "CJU"), ("CJU", "ICN"),
    ("ICN", "PUS"), ("PUS", "ICN"),
    ("GMP", "CJU"), ("CJU", "GMP"),
    ("GMP", "PUS"), ("PUS", "GMP"),
}


def _is_domestic(origin: str, destination: str) -> bool:
    o, d = (origin or "").upper()[:3], (destination or "").upper()[:3]
    return (o, d) in DOMESTIC_PAIRS or (
        o in ("ICN", "GMP", "PUS", "CJU") and d in ("ICN", "GMP", "PUS", "CJU") and o != d
    )


def mock_search_flights(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    seat_class: str = "economy",
    use_miles: bool = False,
) -> list[dict]:
    """Generate mock flight results (노선별 현실적 정보)."""
    is_domestic = _is_domestic(origin, destination)
    base_price = 450000 if seat_class == "economy" else 1200000

    _mock = lambda d: {**d, "source": "mock", "is_direct": d.get("is_direct", True)}

    if is_domestic:
        return [
            _mock({"flight_id": "FL001", "airline": "Korean Air", "flight_number": "KE123",
             "departure": f"{start_date}T08:00", "arrival": f"{start_date}T09:30",
             "origin": origin, "destination": destination, "duration_hours": 1.5,
             "price_krw": base_price, "miles_required": 15000 if use_miles else None, "seat_class": seat_class}),
            _mock({"flight_id": "FL002", "airline": "Asiana", "flight_number": "OZ456",
             "departure": f"{start_date}T14:00", "arrival": f"{start_date}T15:30",
             "origin": origin, "destination": destination, "duration_hours": 1.5,
             "price_krw": base_price + 30000, "miles_required": 18000 if use_miles else None, "seat_class": seat_class}),
            _mock({"flight_id": "FL003", "airline": "Jeju Air", "flight_number": "7C789",
             "departure": f"{start_date}T11:00", "arrival": f"{start_date}T12:20",
             "origin": origin, "destination": destination, "duration_hours": 1.3,
             "price_krw": base_price - 80000, "miles_required": None, "seat_class": seat_class}),
        ]

    return [
        _mock({"flight_id": "FL001", "airline": "Korean Air", "flight_number": "KE925",
         "departure": f"{start_date}T00:30", "arrival": f"{start_date}T07:30",
         "origin": origin, "destination": destination, "duration_hours": 12,
         "price_krw": 1250000 if seat_class == "economy" else 3200000,
         "miles_required": 65000 if use_miles else None, "seat_class": seat_class}),
        _mock({"flight_id": "FL002", "airline": "Asiana", "flight_number": "OZ542",
         "departure": f"{start_date}T23:00", "arrival": f"{(datetime.strptime(start_date, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')}T11:00",
         "origin": origin, "destination": destination, "duration_hours": 12,
         "price_krw": 1180000 if seat_class == "economy" else 3000000,
         "miles_required": 62000 if use_miles else None, "seat_class": seat_class}),
        _mock({"flight_id": "FL003", "airline": "Korean Air", "flight_number": "KE927",
         "departure": f"{start_date}T13:00", "arrival": f"{start_date}T20:00",
         "origin": origin, "destination": destination, "duration_hours": 12,
         "price_krw": 1320000 if seat_class == "economy" else 3500000,
         "miles_required": 70000 if use_miles else None, "seat_class": seat_class}),
    ]

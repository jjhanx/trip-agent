"""Flight search logic - shared by MCP server and agents."""


def mock_search_flights(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    seat_class: str = "economy",
    use_miles: bool = False,
) -> list[dict]:
    """Generate mock flight results."""
    base_price = 450000 if seat_class == "economy" else 1200000
    return [
        {
            "flight_id": "FL001",
            "airline": "Korean Air",
            "flight_number": "KE123",
            "departure": f"{start_date}T08:00:00",
            "arrival": f"{start_date}T10:30:00",
            "origin": origin,
            "destination": destination,
            "price_krw": base_price,
            "miles_required": 25000 if use_miles else None,
            "seat_class": seat_class,
        },
        {
            "flight_id": "FL002",
            "airline": "Asiana",
            "flight_number": "OZ456",
            "departure": f"{start_date}T14:00:00",
            "arrival": f"{start_date}T16:30:00",
            "origin": origin,
            "destination": destination,
            "price_krw": base_price + 50000,
            "miles_required": 27000 if use_miles else None,
            "seat_class": seat_class,
        },
        {
            "flight_id": "FL003",
            "airline": "Jeju Air",
            "flight_number": "7C789",
            "departure": f"{start_date}T11:00:00",
            "arrival": f"{start_date}T13:00:00",
            "origin": origin,
            "destination": destination,
            "price_krw": base_price - 80000,
            "miles_required": 22000 if use_miles else None,
            "seat_class": seat_class,
        },
    ]

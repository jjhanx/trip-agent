"""Rental car search logic - shared by MCP server and agents."""


def mock_search_rentals(
    pickup: str,
    dropoff: str,
    car_type: str,
    days: int = 3,
) -> list[dict]:
    """Generate mock rental car results."""
    base = 80000 * days
    return [
        {
            "rental_id": "RC001",
            "provider": "Hertz",
            "car_type": car_type,
            "pickup_location": pickup,
            "dropoff_location": dropoff,
            "price_total_krw": base,
        },
        {
            "rental_id": "RC002",
            "provider": "Avis",
            "car_type": car_type,
            "pickup_location": pickup,
            "dropoff_location": dropoff,
            "price_total_krw": base + 15000,
        },
        {
            "rental_id": "RC003",
            "provider": "Local Rent",
            "car_type": car_type,
            "pickup_location": pickup,
            "dropoff_location": dropoff,
            "price_total_krw": base - 10000,
        },
    ]

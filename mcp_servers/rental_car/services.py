"""Rental car search logic - shared by MCP server and agents."""

# 차급별 최대 탑승 인원 (compact=4, sedan=5, suv=7, van=8)
_CAR_SEATS = {"compact": 4, "sedan": 5, "suv": 7, "van": 8, "minivan": 8}


def _min_car_type_for_passengers(passengers: int) -> str:
    """일행 수에 맞는 최소 차급."""
    if passengers <= 4:
        return "compact"
    if passengers <= 5:
        return "sedan"
    if passengers <= 7:
        return "suv"
    return "van"


def mock_search_rentals(
    pickup: str,
    dropoff: str,
    car_type: str,
    days: int = 3,
    passengers: int | None = None,
) -> list[dict]:
    """Generate mock rental car results. passengers가 있으면 일행이 탈 수 있는 차량만 반환."""
    base = 80000 * days
    min_seats = passengers or 1
    # 일행 수에 맞는 최소 차급으로 상향
    min_type = _min_car_type_for_passengers(min_seats)
    type_order = ["compact", "sedan", "suv", "van"]
    try:
        car_idx = type_order.index(min_type)
    except ValueError:
        car_idx = 0
    candidates = [
        {"rental_id": "RC001", "provider": "Hertz", "car_type": "compact", "seats": 4},
        {"rental_id": "RC002", "provider": "Avis", "car_type": "sedan", "seats": 5},
        {"rental_id": "RC003", "provider": "Local Rent", "car_type": "suv", "seats": 7},
        {"rental_id": "RC004", "provider": "Sixt", "car_type": "van", "seats": 8},
    ]
    results = []
    for i, c in enumerate(candidates):
        if c["seats"] >= min_seats and type_order.index(c["car_type"]) >= car_idx:
            results.append({
                "rental_id": c["rental_id"],
                "provider": c["provider"],
                "car_type": c["car_type"],
                "seats": c["seats"],
                "pickup_location": pickup,
                "dropoff_location": dropoff,
                "price_total_krw": base + (i * 15000) - (5000 if c["car_type"] == "compact" else 0),
            })
    if not results:
        # fallback: 최소 한 건 (가장 큰 차량)
        fallback = candidates[-1]
        results = [{
            "rental_id": fallback["rental_id"],
            "provider": fallback["provider"],
            "car_type": fallback["car_type"],
            "seats": fallback["seats"],
            "pickup_location": pickup,
            "dropoff_location": dropoff,
            "price_total_krw": base + 20000,
        }]
    return results

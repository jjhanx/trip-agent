"""Hotel search logic - shared by MCP server and agents."""

ACCOMMODATION_TYPES = [
    "hotel", "guesthouse", "hostel", "apartment", "resort",
    "villa", "bnb", "hotel_with_kitchen", "mountain_lodge",
]


def mock_search_hotels(
    location: str,
    accommodation_type: str = "hotel",
    accommodation_priority: list[str] | None = None,
) -> list[dict]:
    """Generate mock hotel results. accommodation_priority: 선호 3순위, 혼합 후보 제시."""
    priority = accommodation_priority or [accommodation_type]
    valid = [p for p in priority if p in ACCOMMODATION_TYPES] or ["hotel"]
    # 5개 결과를 우선순위 순으로 혼합
    types_for_results = (valid * 2)[:5]
    base_hotels = [
        {
            "hotel_id": "HT001",
            "name": "Central Plaza Hotel",
            "location": location,
            "price_per_night_krw": 120000,
            "rating": 4.5,
            "amenities": ["wifi", "breakfast", "parking"],
        },
        {
            "hotel_id": "HT002",
            "name": "Riverside Inn",
            "location": location,
            "price_per_night_krw": 95000,
            "rating": 4.2,
            "amenities": ["wifi", "breakfast"],
        },
        {
            "hotel_id": "HT003",
            "name": "Sunset Resort",
            "location": location,
            "price_per_night_krw": 180000,
            "rating": 4.8,
            "amenities": ["wifi", "breakfast", "pool", "spa"],
        },
        {
            "hotel_id": "HT004",
            "name": "City Stay Hostel",
            "location": location,
            "price_per_night_krw": 45000,
            "rating": 4.0,
            "amenities": ["wifi", "kitchen"],
        },
        {
            "hotel_id": "HT005",
            "name": "Mountain View Lodge",
            "location": location,
            "price_per_night_krw": 150000,
            "rating": 4.6,
            "amenities": ["wifi", "breakfast", "parking", "garden"],
        },
    ]
    return [
        {**h, "accommodation_type": t}
        for h, t in zip(base_hotels, types_for_results)
    ]

"""Hotel search logic - shared by MCP server and agents."""


def mock_search_hotels(location: str, accommodation_type: str = "hotel") -> list[dict]:
    """Generate mock hotel results."""
    types = ["hotel", "guesthouse", "hostel", "apartment", "resort"]
    at = accommodation_type if accommodation_type in types else "hotel"
    return [
        {
            "hotel_id": "HT001",
            "name": "Central Plaza Hotel",
            "location": location,
            "price_per_night_krw": 120000,
            "rating": 4.5,
            "accommodation_type": at,
            "amenities": ["wifi", "breakfast", "parking"],
        },
        {
            "hotel_id": "HT002",
            "name": "Riverside Inn",
            "location": location,
            "price_per_night_krw": 95000,
            "rating": 4.2,
            "accommodation_type": at,
            "amenities": ["wifi", "breakfast"],
        },
        {
            "hotel_id": "HT003",
            "name": "Sunset Resort",
            "location": location,
            "price_per_night_krw": 180000,
            "rating": 4.8,
            "accommodation_type": at,
            "amenities": ["wifi", "breakfast", "pool", "spa"],
        },
        {
            "hotel_id": "HT004",
            "name": "City Stay Hostel",
            "location": location,
            "price_per_night_krw": 45000,
            "rating": 4.0,
            "accommodation_type": at,
            "amenities": ["wifi", "kitchen"],
        },
        {
            "hotel_id": "HT005",
            "name": "Mountain View Lodge",
            "location": location,
            "price_per_night_krw": 150000,
            "rating": 4.6,
            "accommodation_type": at,
            "amenities": ["wifi", "breakfast", "parking", "garden"],
        },
    ]

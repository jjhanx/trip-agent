"""Rental Car MCP Server - 렌트카 검색 Tools."""

import json

from mcp.server.fastmcp import FastMCP

from mcp_servers.rental_car.services import mock_search_rentals

mcp = FastMCP("rental-car-search", port=8003)


@mcp.tool()
def search_rentals(
    pickup: str,
    dropoff: str,
    start_date: str,
    end_date: str,
    car_type: str = "compact",
    passengers: int | None = None,
) -> str:
    """Search for rental cars. passengers x 1.5 좌석(여행가방 고려) 이상 차량만 반환.

    Args:
        pickup: Pickup location (airport/city)
        dropoff: Dropoff location
        start_date: Rental start (YYYY-MM-DD)
        end_date: Rental end (YYYY-MM-DD)
        car_type: compact, sedan, suv, etc.
        passengers: 일행 수 (일행 x 1.5 좌석 이상 차량만 검색, 여행가방 고려)

    Returns:
        JSON array of rental options (seats, vehicle_name, image_url, booking_url 등 포함)
    """
    from datetime import datetime

    d1 = datetime.strptime(start_date, "%Y-%m-%d")
    d2 = datetime.strptime(end_date, "%Y-%m-%d")
    days = max(1, (d2 - d1).days)
    rentals = mock_search_rentals(
        pickup, dropoff, car_type, days,
        passengers=passengers,
        start_date=start_date,
        end_date=end_date,
    )
    return json.dumps(rentals, ensure_ascii=False)


@mcp.tool()
def get_drive_routes(origin: str, destination: str) -> str:
    """Get driving routes between two points.

    Args:
        origin: Start address/location
        destination: End address/location

    Returns:
        JSON with route info and estimated duration
    """
    return json.dumps(
        {
            "origin": origin,
            "destination": destination,
            "duration_minutes": 45,
            "distance_km": 35,
        },
        ensure_ascii=False,
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

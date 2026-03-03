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
) -> str:
    """Search for rental cars.

    Args:
        pickup: Pickup location (airport/city)
        dropoff: Dropoff location
        start_date: Rental start (YYYY-MM-DD)
        end_date: Rental end (YYYY-MM-DD)
        car_type: compact, sedan, suv, etc.

    Returns:
        JSON array of rental options
    """
    from datetime import datetime

    d1 = datetime.strptime(start_date, "%Y-%m-%d")
    d2 = datetime.strptime(end_date, "%Y-%m-%d")
    days = max(1, (d2 - d1).days)
    rentals = mock_search_rentals(pickup, dropoff, car_type, days)
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

"""Public Transit MCP Server - 대중교통 검색 Tools."""

import json

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("transit-search", port=8004)


@mcp.tool()
def search_routes(
    origin: str,
    destination: str,
    date_time: str,
) -> str:
    """Search for public transit routes.

    Args:
        origin: Start location/station
        destination: End location/station
        date_time: Departure date-time (YYYY-MM-DDTHH:MM or YYYY-MM-DD)

    Returns:
        JSON array of route options
    """
    routes = [
        {
            "route_id": "TR001",
            "description": "Metro Line 1 → Bus 101",
            "duration_minutes": 35,
            "pass_name": None,
            "pass_price_krw": None,
        },
        {
            "route_id": "TR002",
            "description": "Direct bus",
            "duration_minutes": 50,
            "pass_name": "City Pass 1-day",
            "pass_price_krw": 15000,
        },
        {
            "route_id": "TR003",
            "description": "Train + Metro",
            "duration_minutes": 40,
            "pass_name": "Rail Pass",
            "pass_price_krw": 25000,
        },
    ]
    return json.dumps(routes, ensure_ascii=False)


@mcp.tool()
def get_transit_passes(location: str, duration_days: int = 1) -> str:
    """Get available transit passes for a location.

    Args:
        location: City or region name
        duration_days: Pass validity (1, 3, 7 etc.)

    Returns:
        JSON array of pass options
    """
    passes_list = [
        {"name": "1-day pass", "price_krw": 12000, "duration_days": 1},
        {"name": "3-day pass", "price_krw": 28000, "duration_days": 3},
        {"name": "7-day pass", "price_krw": 55000, "duration_days": 7},
    ]
    found = [p for p in passes_list if p["duration_days"] <= duration_days] or passes_list
    return json.dumps(found, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

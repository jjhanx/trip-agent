"""Flight MCP Server - 항공편 검색 Tools."""

import json

from mcp.server.fastmcp import FastMCP

from mcp_servers.flight.services import mock_search_flights

mcp = FastMCP("flight-search", port=8001)


@mcp.tool()
def search_flights(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    seat_class: str = "economy",
    use_miles: bool = False,
) -> str:
    """Search for flights between origin and destination for the given dates.

    Args:
        origin: Departure city/code (e.g. ICN, GMP)
        destination: Arrival city/code (e.g. KIX, NRT)
        start_date: Outbound date (YYYY-MM-DD)
        end_date: Return date (YYYY-MM-DD)
        seat_class: economy, premium_economy, business, first
        use_miles: Whether to search mileage redemption options

    Returns:
        JSON array of flight options sorted by price
    """
    flights = mock_search_flights(origin, destination, start_date, end_date, seat_class, use_miles)
    if use_miles:
        flights.sort(key=lambda x: x.get("miles_required") or 999999)
    else:
        flights.sort(key=lambda x: x.get("price_krw") or 999999)
    return json.dumps(flights, ensure_ascii=False)


@mcp.tool()
def get_mileage_balance(program: str) -> str:
    """Get current mileage balance for an airline program (mock).

    Args:
        program: Mileage program name (e.g. Skypass, Asiana Club)

    Returns:
        JSON with balance and program info
    """
    return json.dumps(
        {"program": program, "balance": 50000, "tier": "silver"},
        ensure_ascii=False,
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

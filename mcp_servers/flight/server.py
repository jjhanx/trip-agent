"""Flight MCP Server - 항공편 검색 Tools (Amadeus + Kiwi + RapidAPI)."""

import json
import os

from mcp.server.fastmcp import FastMCP

from mcp_servers.flight.services import multi_source_search_flights

mcp = FastMCP("flight-search", port=8001)


def _get_config():
    return {
        "amadeus_client_id": os.environ.get("AMADEUS_CLIENT_ID", ""),
        "amadeus_client_secret": os.environ.get("AMADEUS_CLIENT_SECRET", ""),
        "amadeus_base_url": os.environ.get("AMADEUS_BASE_URL", "https://test.api.amadeus.com"),
        "kiwi_api_key": os.environ.get("KIWI_API_KEY", ""),
        "rapidapi_key": os.environ.get("RAPIDAPI_KEY", ""),
        "flightapi_key": os.environ.get("FLIGHTAPI_KEY", ""),
    }


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
    Amadeus, Kiwi, RapidAPI(Skyscanner) 사용. 무료 한도 초과 시 해당 API는 건너뛰고 경고 반환.

    Args:
        origin: Departure city/code (e.g. ICN, GMP)
        destination: Arrival city/code (e.g. KIX, NRT)
        start_date: Outbound date (YYYY-MM-DD)
        end_date: Return date (YYYY-MM-DD)
        seat_class: economy, premium_economy, business, first
        use_miles: Whether to search mileage redemption options

    Returns:
        JSON object with "flights" array and "warnings" array
    """
    cfg = _get_config()
    flights, warnings = multi_source_search_flights(
        origin, destination, start_date, end_date, seat_class, use_miles,
        amadeus_client_id=cfg["amadeus_client_id"],
        amadeus_client_secret=cfg["amadeus_client_secret"],
        amadeus_base_url=cfg["amadeus_base_url"],
        kiwi_api_key=cfg["kiwi_api_key"],
        rapidapi_key=cfg["rapidapi_key"],
        flightapi_key=cfg["flightapi_key"],
    )
    return json.dumps({"flights": flights, "warnings": warnings}, ensure_ascii=False)


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

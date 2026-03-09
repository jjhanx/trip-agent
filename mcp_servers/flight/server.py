"""Flight MCP Server - 항공편 검색 Tools (flightapi.io, Kiwi, RapidAPI)."""

import json
import os

from mcp.server.fastmcp import FastMCP

from mcp_servers.flight.services import multi_source_search_flights

mcp = FastMCP("flight-search", port=8001)


def _get_config():
    return {
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
    mileage_program: str | None = None,
) -> str:
    """Search for flights between origin and destination for the given dates.
    flightapi.io, Kiwi, RapidAPI 사용. mileage_program이 있으면 해당 마일리지 적립 항공사 편 우선 노출.

    Args:
        origin: Departure city/code (e.g. ICN, GMP)
        destination: Arrival city/code (e.g. KIX, NRT)
        start_date: Outbound date (YYYY-MM-DD)
        end_date: Return date (YYYY-MM-DD)
        seat_class: economy, premium_economy, business, first
        use_miles: Whether to search mileage redemption options
        mileage_program: 마일리지 프로그램 (Skypass, Asiana, Miles&More 등). 해당 항공사 편 우선 표시

    Returns:
        JSON object with "flights" array and "warnings" array
    """
    cfg = _get_config()
    flights, warnings = multi_source_search_flights(
        origin, destination, start_date, end_date, seat_class, use_miles,
        mileage_program=mileage_program or None,
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

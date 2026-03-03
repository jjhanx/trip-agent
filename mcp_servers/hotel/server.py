"""Hotel MCP Server - 숙소 검색 Tools."""

import json

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("hotel-search", port=8002)


from mcp_servers.hotel.services import mock_search_hotels


@mcp.tool()
def search_hotels(
    location: str,
    check_in: str,
    check_out: str,
    accommodation_type: str = "hotel",
) -> str:
    """Search for hotels/accommodations in a location.

    Args:
        location: City or area name
        check_in: Check-in date (YYYY-MM-DD)
        check_out: Check-out date (YYYY-MM-DD)
        accommodation_type: hotel, guesthouse, hostel, apartment, resort

    Returns:
        JSON array of up to 5 accommodation options
    """
    hotels = mock_search_hotels(location, accommodation_type)
    return json.dumps(hotels, ensure_ascii=False)


@mcp.tool()
def compare_hotels(hotel_ids: str) -> str:
    """Compare multiple hotels by ID.

    Args:
        hotel_ids: Comma-separated hotel IDs (e.g. HT001,HT002,HT003)

    Returns:
        JSON array of hotel details for comparison
    """
    ids = [x.strip() for x in hotel_ids.split(",")]
    all_hotels = mock_search_hotels("default", "hotel")
    found = [h for h in all_hotels if h["hotel_id"] in ids]
    return json.dumps(found, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

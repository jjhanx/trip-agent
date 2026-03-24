"""Public Transit MCP Server - 대중교통 검색 Tools."""

import json

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("transit-search", port=8004)


@mcp.tool()
def search_routes(
    origin: str,
    destination: str,
    date_time: str,
    trip_days: int = 1,
) -> str:
    """Search for public transit routes (공항·역 → 시내 등). 항공 도착 시각 date_time 반영.

    Args:
        origin: Start (e.g. airport name or code)
        destination: End (city / district)
        date_time: Departure date-time (YYYY-MM-DDTHH:MM or YYYY-MM-DD)
        trip_days: 현지 체류 일수 (참고용 문구)

    Returns:
        JSON array of route options
    """
    ctx = f"{origin} → {destination}"
    when = f" ({date_time})" if date_time else ""
    td = max(1, min(int(trip_days or 1), 30))
    routes = [
        {
            "route_id": "TR001",
            "description": f"{ctx}: 공항철도/리무진 → 시청 방향{when}",
            "duration_minutes": 35 + (td % 3),
            "pass_name": None,
            "pass_price_krw": None,
        },
        {
            "route_id": "TR002",
            "description": f"{ctx}: 직행 버스 (Express){when}",
            "duration_minutes": 50,
            "pass_name": None,
            "pass_price_krw": None,
        },
        {
            "route_id": "TR003",
            "description": f"{ctx}: 전철 환승{when}",
            "duration_minutes": 42,
            "pass_name": None,
            "pass_price_krw": None,
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
        {"name": "1일 패스", "price_krw": 12000, "duration_days": 1},
        {"name": "3일 패스", "price_krw": 28000, "duration_days": 3},
        {"name": "7일 패스", "price_krw": 55000, "duration_days": 7},
    ]
    d = max(1, min(int(duration_days or 1), 14))
    found = [p for p in passes_list if p["duration_days"] <= d] or passes_list
    return json.dumps(found, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

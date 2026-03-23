"""Flight MCP Server — SerpApi 우선, Amadeus(429)·Travelpayouts(캐시 참고)·Mock 순."""

import json
import os

from mcp.server.fastmcp import FastMCP

from mcp_servers.flight.services import (
    multi_source_search_flights,
    multi_source_search_flights_multi_dest,
)

mcp = FastMCP("flight-search", port=8001)


def _get_config():
    return {
        "travelpayouts_api_token": os.environ.get("TRAVELPAYOUTS_API_TOKEN", ""),
        "travelpayouts_marker": os.environ.get("TRAVELPAYOUTS_MARKER", ""),
        "serpapi_api_key": os.environ.get("SERPAPI_API_KEY", ""),
        "amadeus_client_id": os.environ.get("AMADEUS_CLIENT_ID", ""),
        "amadeus_client_secret": os.environ.get("AMADEUS_CLIENT_SECRET", ""),
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
    destination_airports: list[str] | None = None,
    date_flexibility_days: int | None = None,
    one_way: bool = False,
) -> str:
    """Search for flights between origin and destination for the given dates.
    SerpApi(Google Flights) 우선. 결과에 대한항공(KE)·아시아나(OZ)가 없으면 SerpApi include_airlines로 보강 병합.
    SerpApi·Amadeus에 표시할 결과가 없을 때 Travelpayouts 캐시(토큰 설정 시) 참고.
    mileage_program이 있으면 해당 마일리지 적립 항공사 편 우선 정렬·배지.
    date_flexibility_days > 0 시 ±일 범위 내 여러 날짜 병렬 검색.
    one_way=True 시 편도만 검색 (왕복의 가는 편/오는 편 별도 검색용).

    Args:
        origin: Departure city/code (e.g. ICN, GMP)
        destination: Arrival city/code (e.g. KIX, NRT)
        start_date: Outbound date (YYYY-MM-DD). one_way 시 검색할 출발일
        end_date: Return date (YYYY-MM-DD). one_way 시 무시
        seat_class: economy, premium_economy, business, first
        use_miles: Whether to search mileage redemption options
        mileage_program: 마일리지 프로그램 (Skypass, Asiana, Miles&More 등). 해당 항공사 편 우선 표시
        destination_airports: [MXP, MUC, VCE, ...] 마일리지 직항 우선순. 있으면 다중 공항 검색 후 병합 (최대 4개)
        date_flexibility_days: 날짜 유연성 (±일). 0/None이면 해당 날짜만 검색
        one_way: 편도 검색 (왕복 시 가는 편/오는 편 각각 검색 시 True)

    Returns:
        JSON object with "flights", "warnings", "flight_search_api" (이번 검색에 쓰인 API 설명)
    """
    cfg = _get_config()
    flex = date_flexibility_days if date_flexibility_days is not None and date_flexibility_days > 0 else None
    if destination_airports and len(destination_airports) > 0:
        flights, warnings, flight_search_api = multi_source_search_flights_multi_dest(
            origin,
            destination_airports[:4],
            start_date,
            end_date,
            seat_class,
            use_miles,
            mileage_program=mileage_program or None,
            travelpayouts_api_token=cfg["travelpayouts_api_token"],
            travelpayouts_marker=cfg["travelpayouts_marker"],
            serpapi_api_key=cfg["serpapi_api_key"],
            amadeus_client_id=cfg["amadeus_client_id"],
            amadeus_client_secret=cfg["amadeus_client_secret"],
            date_flexibility_days=flex,
        )
    else:
        flights, warnings, flight_search_api = multi_source_search_flights(
            origin, destination, start_date, end_date, seat_class, use_miles,
            mileage_program=mileage_program or None,
            travelpayouts_api_token=cfg["travelpayouts_api_token"],
            travelpayouts_marker=cfg["travelpayouts_marker"],
            serpapi_api_key=cfg["serpapi_api_key"],
            amadeus_client_id=cfg["amadeus_client_id"],
            amadeus_client_secret=cfg["amadeus_client_secret"],
            date_flexibility_days=flex,
            one_way=one_way,
        )
    return json.dumps(
        {"flights": flights, "warnings": warnings, "flight_search_api": flight_search_api},
        ensure_ascii=False,
    )


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

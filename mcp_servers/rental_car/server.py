"""Rental Car MCP Server - 렌트카 검색 Tools."""

import json
import os

from mcp.server.fastmcp import FastMCP

from mcp_servers.rental_car.services import search_rentals_combined

mcp = FastMCP("rental-car-search", port=8003)


@mcp.tool()
def search_rentals(
    pickup: str,
    dropoff: str,
    start_date: str,
    end_date: str,
    car_type: str = "compact",
    passengers: int | None = None,
    pickup_datetime: str | None = None,
    dropoff_datetime: str | None = None,
    pickup_airport_iata: str | None = None,
) -> str:
    """렌트카 단계: Amadeus 트랜스퍼 견적(가능 시) + 셀프 드라이브 비교 링크.

    Args:
        pickup: 픽업 위치 (공항 IATA 또는 도시)
        dropoff: 반납 위치
        start_date: 렌트 시작일 YYYY-MM-DD
        end_date: 반납일 YYYY-MM-DD
        car_type: 참고용 차급
        passengers: 일행 수
        pickup_datetime: 픽업 일시 (ISO, Amadeus 트랜스퍼 공항→시내)
        dropoff_datetime: 반납·출발 일시 (ISO, 시내→공항 트랜스퍼)
        pickup_airport_iata: 목적지 공항 3자 코드 (트랜스퍼 구간 기준)

    Returns:
        JSON 배열 (offer_kind, price_total_krw, booking_url 등)
    """
    from datetime import datetime

    d1 = datetime.strptime(start_date, "%Y-%m-%d")
    d2 = datetime.strptime(end_date, "%Y-%m-%d")
    days = max(1, (d2 - d1).days)
    rentals = search_rentals_combined(
        pickup,
        dropoff,
        car_type,
        days,
        passengers=passengers,
        start_date=start_date,
        end_date=end_date,
        travelpayouts_rental_booking_url=os.environ.get("TRAVELPAYOUTS_RENTAL_BOOKING_URL", "").strip() or None,
        pickup_datetime=pickup_datetime,
        dropoff_datetime=dropoff_datetime,
        pickup_airport_iata=pickup_airport_iata,
        amadeus_client_id=os.environ.get("AMADEUS_CLIENT_ID", "").strip() or None,
        amadeus_client_secret=os.environ.get("AMADEUS_CLIENT_SECRET", "").strip() or None,
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

"""Flight search logic - multi-API (Amadeus, Kiwi, RapidAPI) + mock fallback."""

import asyncio
from concurrent.futures import ThreadPoolExecutor

from mcp_servers.flight.api_clients import (
    search_amadeus,
    search_kiwi,
    search_rapidapi_skyscanner,
)


async def _search_all_apis(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    seat_class: str,
    use_miles: bool,
    config: dict,
) -> tuple[list[dict], list[str]]:
    """병렬로 Amadeus, Kiwi, RapidAPI 호출. 한도 초과 시 해당 API는 건너뜀."""
    warnings: list[str] = []
    all_flights: list[dict] = []
    tasks = []

    if config.get("amadeus_client_id") and config.get("amadeus_client_secret"):
        base = config.get("amadeus_base_url") or None
        tasks.append(
            search_amadeus(
                origin, destination, start_date, end_date,
                config["amadeus_client_id"], config["amadeus_client_secret"],
                base_url=base,
            )
        )
    if config.get("kiwi_api_key"):
        tasks.append(
            search_kiwi(origin, destination, start_date, end_date, config["kiwi_api_key"])
        )
    if config.get("rapidapi_key"):
        tasks.append(
            search_rapidapi_skyscanner(
                origin, destination, start_date, end_date, config["rapidapi_key"]
            )
        )

    if not tasks:
        return [], ["API 키가 설정되지 않았습니다. .env 참고."]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, r in enumerate(results):
        if isinstance(r, Exception):
            warnings.append(f"API 오류: {r}")
            continue
        flights, w = r
        warnings.extend(w)
        all_flights.extend(flights)

    # 중복 제거 (airline+flight_number+departure 기준)
    seen = set()
    unique = []
    for f in all_flights:
        key = (f.get("airline"), f.get("flight_number"), f.get("departure"))
        if key not in seen:
            seen.add(key)
            unique.append(f)

    # 가격순 정렬
    if use_miles:
        unique.sort(key=lambda x: x.get("miles_required") or 999999)
    else:
        unique.sort(key=lambda x: x.get("price_krw") or 999999)

    return unique[:15], warnings


def multi_source_search_flights(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    seat_class: str = "economy",
    use_miles: bool = False,
    amadeus_client_id: str = "",
    amadeus_client_secret: str = "",
    amadeus_base_url: str = "",
    kiwi_api_key: str = "",
    rapidapi_key: str = "",
) -> tuple[list[dict], list[str]]:
    """
    Amadeus + Kiwi + RapidAPI 연동 검색.
    무료 한도 초과 전에 중단, 경고 반환.
    Returns (flights, warnings)
    """
    config = {
        "amadeus_client_id": amadeus_client_id,
        "amadeus_client_secret": amadeus_client_secret,
        "amadeus_base_url": amadeus_base_url or "",
        "kiwi_api_key": kiwi_api_key,
        "rapidapi_key": rapidapi_key,
    }

    async def _run():
        return await _search_all_apis(
            origin, destination, start_date, end_date, seat_class, use_miles, config
        )

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None:
        flights, warnings = asyncio.run(_run())
    else:
        # uvicorn 등 이미 실행 중인 이벤트 루프 내에서는 별도 스레드에서 실행
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, _run())
            flights, warnings = future.result()

    if not flights:
        from mcp_servers.flight.mock_fallback import mock_search_flights
        flights = mock_search_flights(
            origin, destination, start_date, end_date, seat_class, use_miles
        )
        warnings.append("실제 API 결과 없음. Mock 데이터로 대체합니다.")

    return flights, warnings


def mock_search_flights(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    seat_class: str = "economy",
    use_miles: bool = False,
) -> list[dict]:
    """Mock fallback (기존 로직)."""
    from mcp_servers.flight.mock_fallback import mock_search_flights as m
    return m(origin, destination, start_date, end_date, seat_class, use_miles)

"""Flight search logic - multi-API (flightapi.io, Kiwi, RapidAPI) + mock fallback."""

import asyncio
from concurrent.futures import ThreadPoolExecutor

from mcp_servers.flight.api_clients import (
    search_flightapi,
    search_kiwi,
    search_rapidapi_skyscanner,
)


def _get_preferred_airlines(mileage_program: str | None) -> frozenset[str]:
    """마일리지 프로그램 → 마일리지 적립 항공사명/코드 집합."""
    if not mileage_program or not str(mileage_program).strip():
        return frozenset()
    key = str(mileage_program).lower().replace(" ", "").replace("_", "")
    if "skypass" in key or "대한항공" in key:
        return frozenset({"korean air", "ke", "koreanair"})
    if "asiana" in key or "아시아나" in key:
        return frozenset({"asiana", "oz", "asiana airlines"})
    if "milesandmore" in key or "miles_and_more" in key or "루프트한자" in key:
        return frozenset({"lufthansa", "lh", "swiss", "lx", "austrian", "os"})
    return frozenset()


def _is_preferred_airline(flight: dict, preferred: frozenset[str]) -> bool:
    """해당 편이 선호 항공사(마일리지 적립 항공사)인지."""
    if not preferred:
        return False
    airline = (flight.get("airline") or "").lower().replace(" ", "").replace("-", "")
    fn = (flight.get("flight_number") or "").upper()[:2]
    return airline in preferred or fn in {x.upper() for x in preferred if len(x) <= 3}


async def _search_all_apis(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    seat_class: str,
    use_miles: bool,
    mileage_program: str | None,
    config: dict,
) -> tuple[list[dict], list[str], bool]:
    """병렬로 Kiwi, RapidAPI, flightapi.io 호출. 한도 초과 시 해당 API는 건너뜀.
    Returns (flights, warnings, api_responded_ok).
    api_responded_ok: 최소 1개 API가 예외 없이 정상 응답했는지 (0건이어도 OK)."""
    warnings: list[str] = []
    all_flights: list[dict] = []
    tasks = []

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
    if config.get("flightapi_key"):
        tasks.append(
            search_flightapi(
                origin, destination, start_date, end_date,
                config["flightapi_key"], seat_class,
            )
        )

    if not tasks:
        return [], ["API 키가 설정되지 않았습니다. .env 참고."], False

    results = await asyncio.gather(*tasks, return_exceptions=True)
    api_responded_ok = any(not isinstance(r, Exception) for r in results)

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

    # 마일리지 선호 항공사 우선: 선호 항공사 전편 먼저, 그다음 나머지. 각 그룹 내 가격순
    preferred_airlines = _get_preferred_airlines(mileage_program)
    if preferred_airlines:
        preferred = [f for f in unique if _is_preferred_airline(f, preferred_airlines)]
        others = [f for f in unique if not _is_preferred_airline(f, preferred_airlines)]
        for f in preferred:
            f["mileage_eligible"] = True  # UI에서 마일리지 적립 배지 표시용
        for f in others:
            f["mileage_eligible"] = False
        price_key = (lambda x: x.get("miles_required") or 999999) if use_miles else (lambda x: x.get("price_krw") or 999999)
        preferred.sort(key=price_key)
        others.sort(key=price_key)
        unique = preferred + others  # 선호 항공사 전편 + 나머지, 제한 없이 모두 반환
    else:
        if use_miles:
            unique.sort(key=lambda x: x.get("miles_required") or 999999)
        else:
            unique.sort(key=lambda x: x.get("price_krw") or 999999)

    return unique, warnings, api_responded_ok


def multi_source_search_flights(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    seat_class: str = "economy",
    use_miles: bool = False,
    mileage_program: str | None = None,
    kiwi_api_key: str = "",
    rapidapi_key: str = "",
    flightapi_key: str = "",
) -> tuple[list[dict], list[str]]:
    """
    flightapi.io + Kiwi + RapidAPI 연동 검색.
    무료 한도 초과 전에 중단, 경고 반환.
    mileage_program이 있으면 해당 마일리지 적립 항공사 편을 우선 노출.
    Returns (flights, warnings)
    """
    config = {
        "kiwi_api_key": kiwi_api_key,
        "rapidapi_key": rapidapi_key,
        "flightapi_key": flightapi_key,
    }

    async def _run():
        return await _search_all_apis(
            origin, destination, start_date, end_date, seat_class, use_miles,
            mileage_program, config,
        )

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None:
        flights, warnings, api_responded_ok = asyncio.run(_run())
    else:
        # uvicorn 등 이미 실행 중인 이벤트 루프 내에서는 별도 스레드에서 실행
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, _run())
            flights, warnings, api_responded_ok = future.result()

    if not flights:
        from mcp_servers.flight.mock_fallback import mock_search_flights

        flights = mock_search_flights(
            origin, destination, start_date, end_date, seat_class, use_miles
        )
        # Mock에도 마일리지 선호 항공사 우선 정렬 적용
        preferred_airlines = _get_preferred_airlines(mileage_program)
        if preferred_airlines:
            preferred = [f for f in flights if _is_preferred_airline(f, preferred_airlines)]
            others = [f for f in flights if not _is_preferred_airline(f, preferred_airlines)]
            for f in preferred:
                f["mileage_eligible"] = True
            for f in others:
                f["mileage_eligible"] = False
            price_key = (lambda x: x.get("miles_required") or 999999) if use_miles else (lambda x: x.get("price_krw") or 999999)
            preferred.sort(key=price_key)
            others.sort(key=price_key)
            flights = preferred + others
        # API 정상 연결됐으나 0건 → 예약 기간 밖 가능성. 그 외(인증/검색 실패 등)는 일반 메시지
        api_error_keywords = ("인증", "API 키가", "토큰", "검색 실패", "401", "403", "404", "500", "API 오류")
        has_api_error = any(
            any(kw in w for kw in api_error_keywords)
            for w in warnings
        )
        if api_responded_ok and not has_api_error:
            warnings.append(
                "아직 예약 가능한 기간이 아닙니다. "
                "(항공편 예약은 보통 출발일 기준 약 11개월 전부터 열립니다.) "
                "예시(Mock) 데이터로 보여드립니다."
            )
        else:
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

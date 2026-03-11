"""Flight search logic - SerpApi (Google Flights) API + Playwright Fallback."""

import asyncio
import json
import os
from typing import Any
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

from mcp_servers.flight.api_clients import search_serpapi_flights, search_playwright_flights


def _get_preferred_airlines(mileage_program: str | None) -> frozenset[str]:
    """마일리지 프로그램 → 마일리지 적립 항공사명/코드 집합."""
    if not mileage_program or not str(mileage_program).strip():
        return frozenset()
    key = str(mileage_program).lower().replace(" ", "").replace("_", "")
    if "skypass" in key or "대한항공" in key:
        return frozenset({"korean air", "ke", "koreanair", "koreanairlines", "korean air lines"})
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
    return airline in preferred or fn in {x.upper() for x in preferred if len(x) <= 3} or any(
        p in airline for p in preferred if len(p) > 3
    )  # "koreanair" in "koreanairlines"


async def _search_orchestrator(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str | None = None,
    trip_type: str = "round_trip",
    multi_cities: list[dict] | None = None,
    seat_class: str = "economy",
    use_miles: bool = False,
    mileage_program: str | None = None,
    config: dict | None = None,
    date_flexibility_days: int = 0,
) -> tuple[list[dict], list[str]]:
    """
    모든 API 및 폴백 검색을 오케스트레이션하고 마일리지 우선 정렬 수행.
    date_flexibility_days 파라미터를 사용해 지정일 전후의 모든 날짜 조합에 대해 검색을 수행합니다.
    """
    if config is None:
        config = {}
    api_key = config.get("serpapi_api_key", os.environ.get("SERPAPI_API_KEY", ""))

    all_flights: list[dict] = []
    all_warnings: list[str] = []
    api_responded_ok = False

    # 날짜 유연성 처리 (다구간이 아닌 왕복, 편도의 경우에만 적용)
    # 지나친 트래픽을 막기 위해 flexibility 최대를 2로 제한
    flex = min(date_flexibility_days, 2)
    
    date_pairs = []
    if trip_type == "multi_city":
        # 다구간은 복잡하므로 유연성 적용 최소화 (우선 1회 요청만 함)
        date_pairs.append({"start_date": start_date, "end_date": end_date})
    else:
        try:
            s_dt = datetime.strptime(start_date, "%Y-%m-%d")
            e_dt = datetime.strptime(end_date, "%Y-%m-%d") if end_date else None
            
            for d in range(-flex, flex + 1):
                mod_start = (s_dt + timedelta(days=d)).strftime("%Y-%m-%d")
                if e_dt:
                    for rd in range(-flex, flex + 1):
                        mod_end = (e_dt + timedelta(days=rd)).strftime("%Y-%m-%d")
                        # 출발일이 도착일보다 늦으면 스킵
                        if mod_start <= mod_end:
                            date_pairs.append({"start_date": mod_start, "end_date": mod_end})
                else:
                    date_pairs.append({"start_date": mod_start, "end_date": None})
        except ValueError:
            date_pairs.append({"start_date": start_date, "end_date": end_date})
            
    if not date_pairs:
        date_pairs = [{"start_date": start_date, "end_date": end_date}]

    if api_key:
        # 여러 날짜 비동기 병렬 요청 (gather)
        tasks = []
        for pair in date_pairs:
            tasks.append(search_serpapi_flights(
                origin, destination, pair["start_date"], pair["end_date"], api_key, seat_class, 
                trip_type=trip_type, multi_cities=multi_cities
            ))
            
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in results:
            if isinstance(res, tuple) and len(res) == 2:
                flights, w = res
                all_flights.extend(flights)
                all_warnings.extend(w)
                if flights:
                    api_responded_ok = True
            elif isinstance(res, Exception):
                all_warnings.append(f"SerpApi 동시 검색 중 오류: {str(res)}")
    else:
        all_warnings.append("SERPAPI_API_KEY가 설정되지 않았습니다.")
        
    needs_fallback = any("Playwright 크롤링으로 전환" in x for x in all_warnings) or (not all_flights and api_key)

    # 2단계: Playwright Fallback (폴백은 메인 지정 날짜 하루만 시도)
    if needs_fallback and not all_flights:
        try:
            play_flights, play_w = await search_playwright_flights(
                origin, destination, start_date, end_date, seat_class
            )
            all_warnings.extend(play_w)
            if play_flights:
                all_flights = play_flights
                api_responded_ok = True # 크롤링 성공을 API 성공으로 취급
        except Exception as e:
            all_warnings.append(f"Playwright Fallback 최종 실패: {e}")

    flights = all_flights

    # 중복 제거 (airline+flight_number+departure 기준)
    seen: set = set()
    unique: list = []
    for f in all_flights:
        key = (f.get("airline"), f.get("flight_number"), f.get("departure"))
        if key not in seen:
            seen.add(key)
            unique.append(f)

    # 마일리지 선호 항공사 우선 정렬
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
        unique = preferred + others
    else:
        if use_miles:
            unique.sort(key=lambda x: x.get("miles_required") or 999999)
        else:
            unique.sort(key=lambda x: x.get("price_krw") or 999999)

    return unique, all_warnings, api_responded_ok


def multi_source_search_flights(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str | None = None,
    trip_type: str = "round_trip",
    multi_cities: list[dict] | None = None,
    seat_class: str = "economy",
    use_miles: bool = False,
    mileage_program: str | None = None,
    serpapi_api_key: str = "",
) -> tuple[list[dict], list[str]]:
    """
    SerpApi 검색 및 Playwright Fallback.
    Returns (flights, warnings)
    """
    config = {"serpapi_api_key": serpapi_api_key}

    async def _run():
        return await _search_orchestrator(
            origin, destination, start_date, end_date, 
            trip_type, multi_cities,
            seat_class, use_miles,
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
            origin, destination, start_date, end_date or "", seat_class, use_miles
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
            warnings.append("실제 데이터 가져오기에 모두 실패했습니다. Mock 데이터로 대체합니다.")
            
    return flights, warnings


def multi_source_search_flights_multi_dest(
    origin: str,
    destination_airports: list[str],
    start_date: str,
    end_date: str | None = None,
    trip_type: str = "round_trip",
    seat_class: str = "economy",
    use_miles: bool = False,
    mileage_program: str | None = None,
    serpapi_api_key: str = "",
) -> tuple[list[dict], list[str]]:
    """
    다중 도착 공항 검색. 마일리지 직항 우선순으로 각 공항 검색 후 병합.
    """
    airport_labels = {"MXP": "밀라노", "MUC": "뮌헨", "VCE": "베니스", "VRN": "베로나", "INN": "인스부르크", "TSF": "베니스", "BZO": "볼차노"}
    all_flights: list[dict] = []
    all_warnings: list[str] = []
    preferred_airlines = _get_preferred_airlines(mileage_program)
    price_key = (lambda x: x.get("miles_required") or 999999) if use_miles else (lambda x: x.get("price_krw") or 999999)

    for i, dest in enumerate(destination_airports):
        flights, warnings = multi_source_search_flights(
            origin, dest, start_date, end_date, 
            trip_type=trip_type, multi_cities=None,
            seat_class=seat_class, use_miles=use_miles,
            mileage_program=mileage_program,
            serpapi_api_key=serpapi_api_key,
        )
        label = airport_labels.get(dest, dest)
        for f in flights:
            f["destination_airport"] = dest
            f["destination_label"] = label
            f["airport_priority"] = i  # 직항 우선순 (0=MXP 등)
        all_flights.extend(flights)
        all_warnings.extend(warnings)

    # 중복 제거 (같은 편이 여러 공항에 나올 수 있음 - 목적지 공항 기준으로 구분)
    seen: set[tuple] = set()
    unique = []
    for f in all_flights:
        key = (f.get("airline"), f.get("flight_number"), f.get("departure"), f.get("destination"))
        if key not in seen:
            seen.add(key)
            unique.append(f)

    # 정렬: 1) 직항 우선 공항(MXP 등) + 선호 항공사 2) 공항 우선순위 3) 가격
    def sort_key(f: dict) -> tuple:
        is_pref = _is_preferred_airline(f, preferred_airlines) if preferred_airlines else False
        ap = f.get("airport_priority", 99)
        pk = price_key(f)
        return (0 if is_pref else 1, ap, pk)

    unique.sort(key=sort_key)
    return unique, list(dict.fromkeys(all_warnings))  # 중복 경고 제거


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

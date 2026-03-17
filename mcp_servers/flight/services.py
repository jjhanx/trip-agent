"""Flight search logic - SerpApi (Google Flights) + mock fallback."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from mcp_servers.flight.api_clients import search_serpapi


def _date_pairs_with_flexibility(
    start_date: str,
    end_date: str,
    date_flexibility_days: int,
) -> list[tuple[str, str]]:
    """날짜 유연성 적용 시 검색할 (출발일, 귀환일) 쌍. 최대 5쌍으로 API 호출 절약."""
    if not date_flexibility_days or date_flexibility_days <= 0:
        return [(start_date, end_date)]

    try:
        sd = datetime.strptime(start_date, "%Y-%m-%d").date()
        ed = datetime.strptime(end_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return [(start_date, end_date)]

    flex = min(int(date_flexibility_days), 7)  # 최대 ±7일

    pairs: list[tuple[str, str]] = []
    # 대표 날짜: -flex, -1, 0, +1, +flex (최대 5쌍)
    offsets = []
    if flex >= 3:
        offsets = [-flex, -1, 0, 1, flex]
    elif flex >= 2:
        offsets = [-flex, -1, 0, 1, flex]
    elif flex >= 1:
        offsets = [-1, 0, 1]

    seen: set[tuple[str, str]] = set()
    for off in offsets:
        ns = (sd + timedelta(days=off)).strftime("%Y-%m-%d")
        ne = (ed + timedelta(days=off)).strftime("%Y-%m-%d")
        if (ns, ne) not in seen:
            seen.add((ns, ne))
            pairs.append((ns, ne))

    return pairs if pairs else [(start_date, end_date)]


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


def _recommend_sort_key(
    flight: dict,
    preferred_airlines: frozenset[str],
    use_miles: bool,
) -> tuple[int, float, float]:
    """
    추천순 정렬 키: 1) 선호 직항 2) 선호 경유(비행시간↑) 3) 나머지 직항 4) 나머지 경유(비행시간↑)
    같은 카테고리 내: 비행시간 짧은 순 → 최저가 순
    Returns (category, duration_hours, price).
    """
    if flight.get("round_trip"):
        ob = flight.get("outbound") or {}
        price = (flight.get("miles_required") or flight.get("price_krw") or 999999999)
        dur = (ob.get("duration_hours") or 999.0) + (flight.get("return") or {}).get("duration_hours", 0)
        is_pref = bool(preferred_airlines) and (
            _is_preferred_airline(ob, preferred_airlines)
            or _is_preferred_airline(flight.get("return") or {}, preferred_airlines)
        )
        is_direct = ob.get("is_direct", True) and (flight.get("return") or {}).get("is_direct", True)
    else:
        is_pref = bool(preferred_airlines) and _is_preferred_airline(flight, preferred_airlines)
        is_direct = flight.get("is_direct", True)
        dur = flight.get("duration_hours") or 999.0
        price = (flight.get("miles_required") or flight.get("price_krw") or 999999999)

    if is_pref and is_direct:
        cat = 0
    elif is_pref and not is_direct:
        cat = 1
    elif not is_pref and is_direct:
        cat = 2
    else:
        cat = 3
    return (cat, dur, price)


async def _search_serpapi_only(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    seat_class: str,
    use_miles: bool,
    mileage_program: str | None,
    config: dict,
    one_way: bool = False,
) -> tuple[list[dict], list[str], bool]:
    """SerpApi Google Flights 호출 (대한항공·아시아나 포함).
    one_way=True 시 편도 검색.
    Returns (flights, warnings, api_responded_ok)."""
    api_key = config.get("serpapi_api_key", "")
    if not api_key:
        return [], ["SerpApi API 키가 설정되지 않았습니다. .env에 SERPAPI_API_KEY 추가."], False

    try:
        flights, warnings = await search_serpapi(
            origin, destination, start_date, end_date, api_key, seat_class, one_way=one_way
        )
        api_responded_ok = True
    except Exception as e:
        return [], [f"SerpApi 오류: {e}"], False

    all_flights = flights

    # 중복 제거 (왕복은 flight_id, 편도는 airline+flight_number+departure)
    seen: set = set()
    unique: list = []
    for f in all_flights:
        if f.get("round_trip"):
            key = ("rt", f.get("flight_id"), (f.get("outbound") or {}).get("departure"), (f.get("return") or {}).get("departure"))
        else:
            key = (f.get("airline"), f.get("flight_number"), f.get("departure"))
        if key not in seen:
            seen.add(key)
            unique.append(f)

    # mileage_eligible 표시 및 추천순 정렬 (검색 결과 있을 때 Mock 보충 안 함)
    preferred_airlines = _get_preferred_airlines(mileage_program)
    for f in unique:
        ob = f.get("outbound") if f.get("round_trip") else f
        ret = f.get("return") if f.get("round_trip") else None
        f["mileage_eligible"] = bool(preferred_airlines) and (
            _is_preferred_airline(ob, preferred_airlines)
            or (ret and _is_preferred_airline(ret, preferred_airlines))
        )
    sort_fn = lambda x: _recommend_sort_key(x, preferred_airlines, use_miles)
    unique.sort(key=sort_fn)

    return unique, warnings, api_responded_ok


def multi_source_search_flights(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    seat_class: str = "economy",
    use_miles: bool = False,
    mileage_program: str | None = None,
    serpapi_api_key: str = "",
    date_flexibility_days: int | None = None,
    one_way: bool = False,
) -> tuple[list[dict], list[str]]:
    """
    SerpApi Google Flights 검색 (대한항공·아시아나 포함).
    date_flexibility_days > 0 시 해당 ±일 범위 내 여러 날짜로 병렬 검색 후 통합.
    mileage_program이 있으면 해당 마일리지 적립 항공사 편을 우선 노출.
    Returns (flights, warnings)
    """
    config = {"serpapi_api_key": serpapi_api_key}
    date_pairs = _date_pairs_with_flexibility(
        start_date, end_date, date_flexibility_days or 0
    )

    async def _run():
        if len(date_pairs) == 1:
            return await _search_serpapi_only(
                origin, destination, date_pairs[0][0], date_pairs[0][1],
                seat_class, use_miles, mileage_program, config, one_way=one_way,
            )
        # 날짜 유연성: 여러 날짜 쌍 병렬 검색
        tasks = [
            _search_serpapi_only(
                origin, destination, ds, de, seat_class, use_miles,
                mileage_program, config, one_way=one_way,
            )
            for ds, de in date_pairs
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        all_flights: list[dict] = []
        all_warnings: list[str] = []
        api_responded_ok = False
        for r in results:
            if isinstance(r, Exception):
                all_warnings.append(f"날짜 유연 검색 오류: {r}")
                continue
            fl, wa, ok = r
            all_flights.extend(fl)
            all_warnings.extend(wa)
            if ok:
                api_responded_ok = True
        # 중복 제거 및 정렬
        seen: set = set()
        unique: list = []
        for f in all_flights:
            if f.get("round_trip"):
                key = ("rt", f.get("flight_id"), (f.get("outbound") or {}).get("departure"), (f.get("return") or {}).get("departure"))
            else:
                key = (f.get("airline"), f.get("flight_number"), f.get("departure"))
            if key not in seen:
                seen.add(key)
                unique.append(f)
        preferred = _get_preferred_airlines(mileage_program)
        for f in unique:
            ob = f.get("outbound") if f.get("round_trip") else f
            ret = f.get("return") if f.get("round_trip") else None
            f["mileage_eligible"] = bool(preferred) and (
                _is_preferred_airline(ob, preferred)
                or (ret and _is_preferred_airline(ret, preferred))
            )
        unique.sort(key=lambda x: _recommend_sort_key(x, preferred, use_miles))
        return unique, list(dict.fromkeys(all_warnings)), api_responded_ok

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None:
        flights, warnings, api_responded_ok = asyncio.run(_run())
    else:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, _run())
            flights, warnings, api_responded_ok = future.result()

    if not flights:
        from mcp_servers.flight.mock_fallback import mock_search_flights

        flights = mock_search_flights(
            origin, destination, start_date, end_date, seat_class, use_miles, one_way=one_way
        )
        # Mock에도 추천순 정렬 적용 (선호 직항 → 선호 경유 → 나머지 직항 → 나머지 경유, 비행시간↑ 가격↑)
        preferred_airlines = _get_preferred_airlines(mileage_program)
        for f in flights:
            f["mileage_eligible"] = bool(preferred_airlines) and _is_preferred_airline(f, preferred_airlines)
        flights.sort(key=lambda x: _recommend_sort_key(x, preferred_airlines, use_miles))
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


def multi_source_search_flights_multi_dest(
    origin: str,
    destination_airports: list[str],
    start_date: str,
    end_date: str,
    seat_class: str = "economy",
    use_miles: bool = False,
    mileage_program: str | None = None,
    serpapi_api_key: str = "",
    date_flexibility_days: int | None = None,
    one_way: bool = False,
) -> tuple[list[dict], list[str]]:
    """
    다중 도착 공항 검색. 마일리지 직항 우선순으로 각 공항 검색 후 병합.
    정렬: 1) 마일리지 직항 공항·선호 항공사 2) 가격순
    """
    airport_labels = {"MXP": "밀라노", "MUC": "뮌헨", "VCE": "베니스", "VRN": "베로나", "INN": "인스부르크", "TSF": "베니스", "BZO": "볼차노"}
    all_flights: list[dict] = []
    all_warnings: list[str] = []
    preferred_airlines = _get_preferred_airlines(mileage_program)

    for i, dest in enumerate(destination_airports):
        flights, warnings = multi_source_search_flights(
            origin, dest, start_date, end_date, seat_class, use_miles,
            mileage_program=mileage_program,
            serpapi_api_key=serpapi_api_key,
            date_flexibility_days=date_flexibility_days,
            one_way=one_way,
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
        if f.get("round_trip"):
            ob = f.get("outbound") or {}
            key = ("rt", f.get("flight_id"), ob.get("departure"), (f.get("return") or {}).get("departure"), f.get("destination_airport"))
        else:
            key = (f.get("airline"), f.get("flight_number"), f.get("departure"), f.get("destination"))
        if key not in seen:
            seen.add(key)
            unique.append(f)

    # 정렬: 추천순 4단계 + 공항 우선순위(MXP 등) + 비행시간↑ 가격↑
    def sort_key_multi(f: dict) -> tuple:
        base = _recommend_sort_key(f, preferred_airlines, use_miles)
        ap = f.get("airport_priority", 99)
        return (base[0], ap, base[1], base[2])

    unique.sort(key=sort_key_multi)
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

"""Flight search logic - SerpApi (Google Flights) + mock fallback."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from mcp_servers.flight.api_clients import search_serpapi


def _outbound_return_dates_with_flex(
    start_date: str,
    end_date: str,
    date_flexibility_days: int,
) -> tuple[list[str], list[str], str, str]:
    """날짜 유연성 적용 시 검색할 출발일·귀환일 목록.
    Returns (outbound_dates, return_dates, outbound_range_str, return_range_str) for no-results message.
    """
    if not date_flexibility_days or date_flexibility_days <= 0:
        return ([start_date], [end_date], start_date, end_date)

    try:
        sd = datetime.strptime(start_date, "%Y-%m-%d").date()
        ed = datetime.strptime(end_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return ([start_date], [end_date], start_date, end_date)

    flex = min(int(date_flexibility_days), 7)  # 최대 ±7일
    offsets = sorted(set([-flex, -1, 0, 1, flex]) if flex >= 2 else [-1, 0, 1])
    outbound_dates = [(sd + timedelta(days=o)).strftime("%Y-%m-%d") for o in offsets]
    return_dates = [(ed + timedelta(days=o)).strftime("%Y-%m-%d") for o in offsets]
    ob_min = (sd - timedelta(days=flex)).strftime("%Y-%m-%d")
    ob_max = (sd + timedelta(days=flex)).strftime("%Y-%m-%d")
    ret_min = (ed - timedelta(days=flex)).strftime("%Y-%m-%d")
    ret_max = (ed + timedelta(days=flex)).strftime("%Y-%m-%d")
    return outbound_dates, return_dates, f"{ob_min}부터 {ob_max}", f"{ret_min}부터 {ret_max}"


def _date_pairs_with_flexibility(
    start_date: str,
    end_date: str,
    date_flexibility_days: int,
) -> list[tuple[str, str]]:
    """날짜 유연성 적용 시 검색할 (출발일, 귀환일) 쌍. (편도조합 방식 아닐 때 폴백용)"""
    if not date_flexibility_days or date_flexibility_days <= 0:
        return [(start_date, end_date)]
    try:
        sd = datetime.strptime(start_date, "%Y-%m-%d").date()
        ed = datetime.strptime(end_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return [(start_date, end_date)]
    flex = min(int(date_flexibility_days), 7)
    offsets = ([-flex, -1, 0, 1, flex] if flex >= 2 else [-1, 0, 1])
    pairs = [
        ((sd + timedelta(days=o)).strftime("%Y-%m-%d"), (ed + timedelta(days=e)).strftime("%Y-%m-%d"))
        for o in offsets for e in offsets
        if (sd + timedelta(days=o)) <= (ed + timedelta(days=e))
    ]
    return pairs[:15] if pairs else [(start_date, end_date)]


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


async def _search_round_trip_flex_2phase(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    seat_class: str,
    use_miles: bool,
    mileage_program: str | None,
    config: dict,
    date_flexibility_days: int,
) -> tuple[list[dict], list[str], bool, str, str]:
    """
    2단계 왕복 검색:
    1) 편도 검색으로 가능한 (출발일, 귀환일) 조합 추출
    2) 추출된 조합별 왕복 검색(deep_search=true)으로 정확한 가격 획득
    Returns (flights, warnings, api_ok, ob_range_msg, ret_range_msg).
    """
    od_dates, rd_dates, ob_range, ret_range = _outbound_return_dates_with_flex(
        start_date, end_date, date_flexibility_days
    )
    api_key = config.get("serpapi_api_key", "")
    if not api_key:
        return [], ["SerpApi API 키가 설정되지 않았습니다. .env에 SERPAPI_API_KEY 추가."], False, ob_range, ret_range

    # 1단계: 편도 검색으로 존재 여부 파악 → 가능한 날짜 조합 추출
    tasks_out = [
        _search_serpapi_only(
            origin, destination, d, d, seat_class, use_miles,
            mileage_program, config, one_way=True,
        )
        for d in od_dates
    ]
    tasks_ret = [
        _search_serpapi_only(
            destination, origin, r, r, seat_class, use_miles,
            mileage_program, config, one_way=True,
        )
        for r in rd_dates
    ]
    out_results = await asyncio.gather(*tasks_out, return_exceptions=True)
    ret_results = await asyncio.gather(*tasks_ret, return_exceptions=True)

    all_warnings: list[str] = []
    ob_by_date: dict[str, list[dict]] = {}
    ret_by_date: dict[str, list[dict]] = {}
    api_responded = False
    for i, r in enumerate(out_results):
        if isinstance(r, Exception):
            all_warnings.append(f"출발일 검색 오류: {r}")
            ob_by_date[od_dates[i]] = []
            continue
        fl, wa, ok = r
        if ok:
            api_responded = True
        all_warnings.extend(wa)
        ob_by_date[od_dates[i]] = fl
    for i, r in enumerate(ret_results):
        if isinstance(r, Exception):
            all_warnings.append(f"귀환일 검색 오류: {r}")
            ret_by_date[rd_dates[i]] = []
            continue
        fl, wa, ok = r
        if ok:
            api_responded = True
        all_warnings.extend(wa)
        ret_by_date[rd_dates[i]] = fl

    # 가능한 (출발일, 귀환일) 조합: 출발·귀환 모두 편도 결과 있음 & 귀환 > 출발
    viable_pairs: list[tuple[str, str]] = [
        (ob_d, ret_d) for ob_d in od_dates for ret_d in rd_dates
        if ret_d > ob_d and ob_by_date.get(ob_d) and ret_by_date.get(ret_d)
    ]
    # 편도 0건이어도 왕복은 있을 수 있음(SerpApi 동작 차이) → fallback으로 날짜쌍 사용
    if not viable_pairs:
        fallback_pairs = _date_pairs_with_flexibility(start_date, end_date, date_flexibility_days)
        viable_pairs = fallback_pairs[:12]

    # 2단계: 각 날짜 조합으로 왕복 검색(deep_search=true) → 정확한 왕복가
    preferred = _get_preferred_airlines(mileage_program)
    pairs_to_try = viable_pairs[:12]  # API 한도 고려
    round_trip_results = await asyncio.gather(
        *[
            _search_serpapi_round_trip_deep(
                origin, destination, ob_d, ret_d, seat_class, use_miles,
                mileage_program, config,
            )
            for ob_d, ret_d in pairs_to_try
        ],
        return_exceptions=True,
    )

    all_flights: list[dict] = []
    seen: set = set()
    for r in round_trip_results:
        if isinstance(r, Exception):
            all_warnings.append(f"왕복 가격 검색 오류: {r}")
            continue
        fl, wa = r
        all_warnings.extend(wa)
        for f in fl:
            key = ("rt", f.get("flight_id"), (f.get("outbound") or {}).get("departure"), (f.get("return") or {}).get("departure"))
            if key not in seen:
                seen.add(key)
                all_flights.append(f)

    # deep_search 0건 시 일반 왕복 검색으로 재시도 (타임아웃/동작 차이 회피)
    if not all_flights and pairs_to_try:
        retry_results = await asyncio.gather(
            *[
                _search_serpapi_round_trip(  # deep_search 없음
                    origin, destination, ob_d, ret_d, seat_class, config,
                )
                for ob_d, ret_d in pairs_to_try[:5]
            ],
            return_exceptions=True,
        )
        for r in retry_results:
            if isinstance(r, Exception):
                all_warnings.append(f"왕복 재검색 오류: {r}")
                continue
            fl, wa = r
            all_warnings.extend(wa)
            for f in fl:
                key = ("rt", f.get("flight_id"), (f.get("outbound") or {}).get("departure"), (f.get("return") or {}).get("departure"))
                if key not in seen:
                    seen.add(key)
                    all_flights.append(f)
        if all_flights:
            all_warnings.append("일반 검색으로 결과를 찾았습니다. (deep_search 0건)")

    for f in all_flights:
        ob = f.get("outbound") or {}
        ret = f.get("return") or {}
        f["mileage_eligible"] = bool(preferred) and (
            _is_preferred_airline(ob, preferred) or _is_preferred_airline(ret, preferred)
        )
    all_flights.sort(key=lambda x: (x.get("price_krw") or 999999999))
    return all_flights[:100], list(dict.fromkeys(all_warnings)), api_responded, ob_range, ret_range


async def _search_serpapi_round_trip(
    origin: str,
    destination: str,
    ob_date: str,
    ret_date: str,
    seat_class: str,
    config: dict,
) -> tuple[list[dict], list[str]]:
    """왕복 검색 (deep_search 없음, 빠른 응답)."""
    api_key = config.get("serpapi_api_key", "")
    if not api_key:
        return [], []
    try:
        return await search_serpapi(
            origin, destination, ob_date, ret_date, api_key, seat_class,
            one_way=False, deep_search=False,
        )
    except Exception:
        return [], []


async def _search_serpapi_round_trip_deep(
    origin: str,
    destination: str,
    ob_date: str,
    ret_date: str,
    seat_class: str,
    use_miles: bool,
    mileage_program: str | None,
    config: dict,
) -> tuple[list[dict], list[str]]:
    """왕복 검색 + deep_search=true (Google Flights 동일 결과·가격)."""
    api_key = config.get("serpapi_api_key", "")
    if not api_key:
        return [], ["SerpApi API 키가 설정되지 않았습니다."]
    try:
        flights, warnings = await search_serpapi(
            origin, destination, ob_date, ret_date, api_key, seat_class,
            one_way=False, deep_search=True,
        )
        return flights, warnings
    except Exception as e:
        return [], [f"SerpApi 왕복 검색 오류: {e}"]


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
    왕복 + date_flexibility_days>=2: 출발일±N·귀환일±N 각각 편도 검색 후 조합, 가격 싼 순.
    그 외: 기존 (날짜쌍 왕복) 또는 편도 검색.
    Returns (flights, warnings)
    """
    config = {"serpapi_api_key": serpapi_api_key}
    flex = date_flexibility_days or 0

    async def _run():
        # 왕복 + 날짜 유연성: 2단계 (편도로 조합 추출 → 왕복 deep_search로 정확한 가격)
        if not one_way and flex >= 1:
            flights, warnings, api_ok, ob_range, ret_range = await _search_round_trip_flex_2phase(
                origin, destination, start_date, end_date,
                seat_class, use_miles, mileage_program, config, flex,
            )
            return flights, warnings, api_ok, ob_range, ret_range
        # 단일 날짜 또는 편도
        date_pairs = _date_pairs_with_flexibility(start_date, end_date, flex)
        if len(date_pairs) == 1:
            fl, wa, ok = await _search_serpapi_only(
                origin, destination, date_pairs[0][0], date_pairs[0][1],
                seat_class, use_miles, mileage_program, config, one_way=one_way,
            )
            return fl, wa, ok, "", ""
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
        return unique, list(dict.fromkeys(all_warnings)), api_responded_ok, "", ""

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None:
        flights, warnings, api_responded_ok, ob_range, ret_range = asyncio.run(_run())
    else:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, _run())
            flights, warnings, api_responded_ok, ob_range, ret_range = future.result()

    if not flights:
        # 0건 시: 날짜범위 메시지로 안내 (편도조합 방식 사용 시)
        if ob_range and ret_range and flex >= 1 and not one_way:
            warnings.append(
                f"출발일 {ob_range}까지와 귀환일 {ret_range} 사이에 해당되는 왕복 항공편이 없습니다."
            )
            return [], warnings
        # 그 외: Mock 폴백
        from mcp_servers.flight.mock_fallback import mock_search_flights

        flights = mock_search_flights(
            origin, destination, start_date, end_date, seat_class, use_miles, one_way=one_way
        )
        preferred_airlines = _get_preferred_airlines(mileage_program)
        for f in flights:
            f["mileage_eligible"] = bool(preferred_airlines) and _is_preferred_airline(f, preferred_airlines)
        flights.sort(key=lambda x: _recommend_sort_key(x, preferred_airlines, use_miles))
        api_error_keywords = ("인증", "API 키가", "토큰", "검색 실패", "401", "403", "404", "500", "API 오류")
        has_quota_msg = any("한도" in w or "429" in w for w in warnings)
        has_api_error = any(any(kw in w for kw in api_error_keywords) for w in warnings)
        if has_quota_msg:
            pass
        elif api_responded_ok and not has_api_error:
            warnings.append(
                "검색 결과가 없습니다. (가능한 원인: 노선/날짜 조합, SerpApi 일시적 오류 등) "
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

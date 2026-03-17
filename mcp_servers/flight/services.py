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
    """날짜 유연성 적용 시 검색할 (출발일, 귀환일) 쌍.
    출발·귀환을 동시에 shift + 출발만/귀환만 각각 shift하여 더 많은 조합 시도 (최대 9쌍).
    """
    if not date_flexibility_days or date_flexibility_days <= 0:
        return [(start_date, end_date)]

    try:
        sd = datetime.strptime(start_date, "%Y-%m-%d").date()
        ed = datetime.strptime(end_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return [(start_date, end_date)]

    flex = min(int(date_flexibility_days), 7)  # 최대 ±7일

    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(ns: str, ne: str) -> None:
        if (ns, ne) not in seen and ns <= ne:  # 귀환일 ≥ 출발일
            seen.add((ns, ne))
            pairs.append((ns, ne))

    # 1) 출발·귀환 동시 shift (기존)
    for off in ([-flex, -1, 0, 1, flex] if flex >= 2 else [-1, 0, 1]):
        ns = (sd + timedelta(days=off)).strftime("%Y-%m-%d")
        ne = (ed + timedelta(days=off)).strftime("%Y-%m-%d")
        add(ns, ne)

    # 2) 출발일만 ±1 shift (귀환일 고정)
    if flex >= 1:
        for doff in [-1, 1]:
            ns = (sd + timedelta(days=doff)).strftime("%Y-%m-%d")
            ne = end_date
            add(ns, ne)

    # 3) 귀환일만 ±1 shift (출발일 고정)
    if flex >= 1:
        for eoff in [-1, 1]:
            ns = start_date
            ne = (ed + timedelta(days=eoff)).strftime("%Y-%m-%d")
            add(ns, ne)

    # 4) flex>=2 시 출발/귀환 각각 ±2 (총 9쌍 이내로 제한)
    if flex >= 2 and len(pairs) < 9:
        for doff in [-2, 2]:
            ns = (sd + timedelta(days=doff)).strftime("%Y-%m-%d")
            add(ns, end_date)
            if len(pairs) >= 9:
                break
        for eoff in [-2, 2]:
            if len(pairs) >= 9:
                break
            ne = (ed + timedelta(days=eoff)).strftime("%Y-%m-%d")
            add(start_date, ne)

    return pairs[:9] if pairs else [(start_date, end_date)]  # SerpApi 한도 고려 최대 9쌍


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

    # 0건 시 flex가 0/None이었으면 flex=2로 재시도 (전달 누락 또는 단일 날짜 한정 회피)
    used_flex = date_flexibility_days or 0
    if not flights and used_flex < 2:
        date_pairs_retry = _date_pairs_with_flexibility(start_date, end_date, 2)
        if len(date_pairs_retry) > 1:
            config = {"serpapi_api_key": serpapi_api_key}
            try:
                async def _retry_run():
                    tasks = [
                        _search_serpapi_only(
                            origin, destination, ds, de, seat_class, use_miles,
                            mileage_program, config, one_way=one_way,
                        )
                        for ds, de in date_pairs_retry
                    ]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    all_f: list[dict] = []
                    all_w: list[str] = []
                    for r in results:
                        if isinstance(r, Exception):
                            all_w.append(f"날짜 유연 재검색 오류: {r}")
                            continue
                        fl, wa, _ = r
                        all_f.extend(fl)
                        all_w.extend(wa)
                    seen_retry: set = set()
                    unique_retry: list = []
                    for f in all_f:
                        if f.get("round_trip"):
                            key = ("rt", f.get("flight_id"), (f.get("outbound") or {}).get("departure"), (f.get("return") or {}).get("departure"))
                        else:
                            key = (f.get("airline"), f.get("flight_number"), f.get("departure"))
                        if key not in seen_retry:
                            seen_retry.add(key)
                            unique_retry.append(f)
                    preferred_retry = _get_preferred_airlines(mileage_program)
                    for f in unique_retry:
                        ob = f.get("outbound") if f.get("round_trip") else f
                        ret = f.get("return") if f.get("round_trip") else None
                        f["mileage_eligible"] = bool(preferred_retry) and (
                            _is_preferred_airline(ob, preferred_retry)
                            or (ret and _is_preferred_airline(ret, preferred_retry))
                        )
                    unique_retry.sort(key=lambda x: _recommend_sort_key(x, preferred_retry, use_miles))
                    return unique_retry, list(dict.fromkeys(all_w))
                try:
                    asyncio.get_running_loop()
                    in_async = True
                except RuntimeError:
                    in_async = False
                if in_async:
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        flights, extra_w = pool.submit(lambda: asyncio.run(_retry_run())).result()
                else:
                    flights, extra_w = asyncio.run(_retry_run())
                warnings.extend(extra_w)
                if flights:
                    warnings.append("날짜 유연성(±2일)으로 재검색하여 결과를 찾았습니다.")
            except Exception:
                pass  # 재시도 실패 시 기존 빈 결과로 Mock 진행

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
        # 추가 안내: 429(한도초과)는 api_clients에서 상세 메시지 반환. 그 외에만 일반 메시지 추가
        api_error_keywords = ("인증", "API 키가", "토큰", "검색 실패", "401", "403", "404", "500", "API 오류")
        has_quota_msg = any("한도" in w or "429" in w for w in warnings)
        has_api_error = any(
            any(kw in w for kw in api_error_keywords)
            for w in warnings
        )
        if has_quota_msg:
            pass  # api_clients에서 한도 초과 상세 안내 이미 포함
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

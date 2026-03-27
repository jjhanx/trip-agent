"""Flight search logic — SerpApi → Amadeus(429 등) → Travelpayouts(캐시 참고) → Mock."""

import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from mcp_servers.flight.api_clients import search_serpapi
from mcp_servers.flight.travelpayouts_clients import search_travelpayouts_flights

# 실제로 결과를 만든 항공 검색 API (JSON·UI에 노출)
FLIGHT_SEARCH_API_TRAVELPAYOUTS = (
    "Travelpayouts Data API — GET https://api.travelpayouts.com/v1/prices/cheap "
    "(직항 보강: /v1/prices/direct)"
)
FLIGHT_SEARCH_API_SERPAPI = "SerpApi — GET https://serpapi.com/search.json (Google Flights)"
FLIGHT_SEARCH_API_AMADEUS = "Amadeus — Flight Offers Search API (test/production)"
FLIGHT_SEARCH_API_MOCK = "내부 Mock (예시 항공편 데이터)"

# 마일리지(스카이패스·아시아나 클럽 등) 계획용 — 결과에 반드시 반영할 대한항공·아시아나(IATA)
MILEAGE_PLANNING_CARRIER_CODES = ("KE", "OZ")


def _carrier_code_from_flight_dict(f: dict | None) -> str | None:
    """편명에서 IATA 항공사 코드(2자리) 추출."""
    if not f or not isinstance(f, dict):
        return None
    fn = (f.get("flight_number") or "").strip().upper().replace(" ", "")
    m = re.match(r"^([A-Z]{2,3})\d", fn)
    if not m:
        return None
    return m.group(1)[:2]


def _flight_key(f: dict) -> tuple:
    """중복 제거용 flight 키."""
    if f.get("round_trip"):
        ob, ret = f.get("outbound") or {}, f.get("return") or {}
        return ("rt", ob.get("departure"), ob.get("arrival"), ret.get("departure"), ret.get("arrival"))
    return ("ow", f.get("departure"), f.get("arrival"), f.get("flight_number"))


async def _enrich_direct_first_and_cheapest(
    flights: list[dict],
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    config: dict,
    one_way: bool,
    seat_class: str,
    use_miles: bool,
    mileage_program: str | None,
    preferred_airlines: frozenset,
    source: str,
) -> tuple[list[dict], list[str]]:
    """
    직항 우선 검색 + 최저가 5건 병합.
    source: "serpapi" | "amadeus" | "travelpayouts"
    Returns (merged_flights, extra_warnings)
    """
    extra_warnings: list[str] = []
    if not flights:
        return [], []

    # 1) 직항 전용 검색
    direct_flights: list[dict] = []
    if source == "travelpayouts" and (config.get("travelpayouts_api_token") or "").strip():
        try:
            direct_flights, dw = await search_travelpayouts_flights(
                origin,
                destination,
                start_date,
                end_date,
                config["travelpayouts_api_token"].strip(),
                one_way=one_way,
                seat_class=seat_class,
                marker=(config.get("travelpayouts_marker") or "").strip(),
                direct_only=True,
                quiet=True,
            )
            if direct_flights:
                extra_warnings.append("직항 우선 검색 결과를 상단에 표시했습니다.")
            elif dw:
                extra_warnings.extend(dw[:1])
        except Exception as e:
            extra_warnings.append(f"직항 검색 보조 실패: {e}")
    elif source == "serpapi" and config.get("serpapi_api_key"):
        try:
            direct_flights, dw = await search_serpapi(
                origin, destination, start_date, end_date,
                config["serpapi_api_key"], seat_class, one_way=one_way,
                deep_search=False, non_stop=True,
            )
            if direct_flights:
                extra_warnings.append("직항 우선 검색 결과를 상단에 표시했습니다.")
            elif dw:
                extra_warnings.extend(dw[:1])
        except Exception as e:
            extra_warnings.append(f"직항 검색 보조 실패: {e}")
    elif source == "amadeus" and config.get("amadeus_client_id") and config.get("amadeus_client_secret"):
        from mcp_servers.flight.amadeus_clients import search_amadeus, AMADEUS_RATE_LIMIT_DELAY

        try:
            await asyncio.sleep(AMADEUS_RATE_LIMIT_DELAY)
            direct_flights, dw = await search_amadeus(
                origin, destination, start_date, end_date,
                config["amadeus_client_id"], config["amadeus_client_secret"],
                one_way=one_way, seat_class=seat_class, max_offers=15,
                non_stop=True,
            )
            if direct_flights:
                extra_warnings.append("직항 우선 검색 결과를 상단에 표시했습니다.")
            elif dw:
                extra_warnings.extend(dw[:1])
        except Exception as e:
            extra_warnings.append(f"직항 검색 보조 실패: {e}")

    # 2) 메인 결과에서 최저가 5건
    by_price = sorted(
        flights,
        key=lambda x: (x.get("miles_required") or x.get("price_krw") or 999999999),
    )
    cheapest_5 = by_price[:5]

    # 3) 직항 mileage_eligible + 정렬
    for f in direct_flights:
        f["mileage_eligible"] = _mileage_eligible_for_flight(f, preferred_airlines)
    direct_flights.sort(key=lambda x: _recommend_sort_key(x, preferred_airlines, use_miles))

    direct_set = {_flight_key(f) for f in direct_flights}
    cheapest_not_in_direct = [c for c in cheapest_5 if _flight_key(c) not in direct_set]
    for c in cheapest_not_in_direct:
        c["cheapest_reference"] = True  # 최저가 참고용

    if direct_flights:
        merged = direct_flights + cheapest_not_in_direct
        if cheapest_not_in_direct:
            extra_warnings.append("최저가 5건을 참고용으로 하단에 추가했습니다.")
    else:
        # 직항 전용 검색 0건 시: 메인 결과 유지(직항 포함 가능). 최저가 5건만 표시하지 않음.
        merged = flights
        if extra_warnings:
            extra_warnings.append("직항 전용 검색 결과 없음. 메인 검색 결과를 표시합니다.")
    return merged, extra_warnings


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


def _flight_includes_carrier(flight: dict, carrier_code: str) -> bool:
    """편/왕복 카드에 해당 IATA(KE, OZ 등) 운항·편명이 포함되는지."""
    cc = carrier_code.upper()[:2]
    if len(cc) != 2:
        return False

    def leg_matches(leg: dict) -> bool:
        if not leg:
            return False
        fn = str(leg.get("flight_number") or "").upper().replace(" ", "")
        if len(fn) >= 2 and fn.startswith(cc):
            return True
        air = str(leg.get("airline") or "").lower()
        if cc == "KE" and ("korean" in air or air in ("ke", "koreanair")):
            return True
        if cc == "OZ" and ("asiana" in air or air in ("oz", "asianaair")):
            return True
        for seg in leg.get("segments") or []:
            sfn = str(seg.get("flight_number") or "").upper().replace(" ", "")
            if len(sfn) >= 2 and sfn.startswith(cc):
                return True
            sa = str(seg.get("airline") or "").lower()
            if cc == "KE" and "korean" in sa:
                return True
            if cc == "OZ" and "asiana" in sa:
                return True
        return False

    if flight.get("round_trip"):
        ob = flight.get("outbound") or {}
        ret = flight.get("return") or {}
        return leg_matches(ob) or leg_matches(ret)
    return leg_matches(flight)


def _is_ke_or_oz_flight(flight: dict) -> bool:
    return _flight_includes_carrier(flight, "KE") or _flight_includes_carrier(flight, "OZ")


def _mileage_eligible_for_flight(flight: dict, preferred_airlines: frozenset[str]) -> bool:
    """UI 배지: 대한항공·아시아나는 프로그램 미선택이어도 마일리지 후보로 표시. 그 외는 선택 프로그램 일치 시."""
    if _is_ke_or_oz_flight(flight):
        return True
    if not preferred_airlines:
        return False
    if flight.get("round_trip"):
        ob = flight.get("outbound") or {}
        ret = flight.get("return") or {}
        return _is_preferred_airline(ob, preferred_airlines) or (
            bool(ret) and _is_preferred_airline(ret, preferred_airlines)
        )
    return _is_preferred_airline(flight, preferred_airlines)


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


async def _merge_ke_oz_serpapi_supplements(
    flights: list[dict],
    warnings: list[str],
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    api_key: str,
    seat_class: str,
    one_way: bool,
    *,
    deep_search: bool = False,
) -> tuple[list[dict], list[str]]:
    """
    일반 Google Flights 결과 상위에 KE/OZ가 없을 수 있어 SerpApi `include_airlines`로 보강 검색 후 병합.
    (마일리지 계획용 — 노선에 해당 항공사가 없으면 0건 유지)
    """
    if not (api_key or "").strip():
        return flights, warnings
    codes_needed: list[str] = []
    for cc in MILEAGE_PLANNING_CARRIER_CODES:
        if not any(_flight_includes_carrier(f, cc) for f in flights):
            codes_needed.append(cc)
    if not codes_needed:
        return flights, warnings

    seen: set = set()
    for f in flights:
        if f.get("round_trip"):
            key = (
                "rt",
                f.get("flight_id"),
                (f.get("outbound") or {}).get("departure"),
                (f.get("return") or {}).get("departure"),
            )
        else:
            key = (f.get("airline"), f.get("flight_number"), f.get("departure"))
        seen.add(key)
    codes = codes_needed

    async def _fetch(code: str) -> tuple[list[dict], list[str]]:
        try:
            return await search_serpapi(
                origin,
                destination,
                start_date,
                end_date,
                api_key,
                seat_class,
                one_way=one_way,
                deep_search=deep_search,
                non_stop=False,
                include_airlines=code,
            )
        except Exception as e:
            return [], [f"대한항공·아시아나 보강 검색({code}) 오류: {e}"]

    gathered = await asyncio.gather(*[_fetch(c) for c in codes], return_exceptions=True)
    added = 0
    for i, code in enumerate(codes):
        r = gathered[i]
        if isinstance(r, Exception):
            warnings.append(f"{code} 보강 검색 오류: {r}")
            continue
        extra_flights, w = r
        warnings.extend(w)
        for f in extra_flights:
            if f.get("round_trip"):
                key = (
                    "rt",
                    f.get("flight_id"),
                    (f.get("outbound") or {}).get("departure"),
                    (f.get("return") or {}).get("departure"),
                )
            else:
                key = (f.get("airline"), f.get("flight_number"), f.get("departure"))
            if key in seen:
                continue
            seen.add(key)
            flights.append(f)
            added += 1

    if added:
        warnings.append(
            f"마일리지 계획용 SerpApi 항공사 필터(include_airlines={','.join(codes)})로 "
            f"대한항공·아시아나 편 {added}건을 추가했습니다."
        )
    return flights, warnings


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
            mileage_program, config, one_way=True, skip_ke_oz_supplement=True,
        )
        for d in od_dates
    ]
    tasks_ret = [
        _search_serpapi_only(
            destination, origin, r, r, seat_class, use_miles,
            mileage_program, config, one_way=True, skip_ke_oz_supplement=True,
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

    # 1단계 진단: 편도 검색 결과 요약
    ob_counts = {d: len(ob_by_date.get(d, [])) for d in od_dates}
    ret_counts = {d: len(ret_by_date.get(d, [])) for d in rd_dates}
    ob_with_flights = [d for d in od_dates if ob_counts[d] > 0]
    ret_with_flights = [d for d in rd_dates if ret_counts[d] > 0]
    diag_phase1 = (
        f"[진단] 1단계 편도: 출발 {ob_counts} → {len(ob_with_flights)}일 유효, "
        f"귀환 {ret_counts} → {len(ret_with_flights)}일 유효"
    )
    all_warnings.append(diag_phase1)

    # 1단계 편도 전부 0건 + SerpAPI 한도 초과 → 2·3단계 생략, Amadeus fallback으로 즉시 전달
    has_quota_msg = any("한도" in w or "429" in w for w in all_warnings)
    if has_quota_msg and len(ob_with_flights) == 0 and len(ret_with_flights) == 0:
        all_warnings.append("[진단] 1단계 편도 전부 0건(SerpAPI 한도 초과) → 2·3단계 생략, Amadeus fallback으로 전달")
        return [], all_warnings, False, ob_range, ret_range

    # 가능한 (출발일, 귀환일) 조합: 출발·귀환 모두 편도 결과 있음 & 귀환 > 출발
    viable_pairs: list[tuple[str, str]] = [
        (ob_d, ret_d) for ob_d in od_dates for ret_d in rd_dates
        if ret_d > ob_d and ob_by_date.get(ob_d) and ret_by_date.get(ret_d)
    ]
    used_fallback = False
    if not viable_pairs:
        fallback_pairs = _date_pairs_with_flexibility(start_date, end_date, date_flexibility_days)
        viable_pairs = fallback_pairs[:12]
        used_fallback = True
        all_warnings.append(f"[진단] 편도 조합 0쌍 → 날짜쌍 fallback {len(viable_pairs)}쌍 사용")

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
    rt_deep_errors = 0
    for r in round_trip_results:
        if isinstance(r, Exception):
            all_warnings.append(f"왕복 가격 검색 오류: {r}")
            rt_deep_errors += 1
            continue
        fl, wa = r
        all_warnings.extend(wa)
        for f in fl:
            key = ("rt", f.get("flight_id"), (f.get("outbound") or {}).get("departure"), (f.get("return") or {}).get("departure"))
            if key not in seen:
                seen.add(key)
                all_flights.append(f)

    all_warnings.append(
        f"[진단] 2단계 왕복(deep_search): {len(pairs_to_try)}쌍 검색 → {len(all_flights)}건"
        + (f", 오류 {rt_deep_errors}건" if rt_deep_errors else "")
    )

    # deep_search 0건 시 일반 왕복 검색으로 재시도 (타임아웃/동작 차이 회피)
    if not all_flights and pairs_to_try:
        retry_pairs = pairs_to_try[:5]
        retry_results = await asyncio.gather(
            *[
                _search_serpapi_round_trip(  # deep_search 없음
                    origin, destination, ob_d, ret_d, seat_class, config,
                )
                for ob_d, ret_d in retry_pairs
            ],
            return_exceptions=True,
        )
        retry_flights = 0
        retry_errors = 0
        for r in retry_results:
            if isinstance(r, Exception):
                all_warnings.append(f"왕복 재검색 오류: {r}")
                retry_errors += 1
                continue
            fl, wa = r
            all_warnings.extend(wa)
            for f in fl:
                key = ("rt", f.get("flight_id"), (f.get("outbound") or {}).get("departure"), (f.get("return") or {}).get("departure"))
                if key not in seen:
                    seen.add(key)
                    all_flights.append(f)
                    retry_flights += 1
        all_warnings.append(
            f"[진단] 3단계 왕복(일반): {len(retry_pairs)}쌍 재시도 → {retry_flights}건"
            + (f", 오류 {retry_errors}건" if retry_errors else "")
        )
        if all_flights:
            all_warnings.append("일반 검색으로 결과를 찾았습니다. (deep_search 0건)")

    all_flights, all_warnings = await _merge_ke_oz_serpapi_supplements(
        all_flights,
        all_warnings,
        origin,
        destination,
        start_date,
        end_date,
        api_key,
        seat_class,
        one_way=False,
        deep_search=True,
    )
    for f in all_flights:
        f["mileage_eligible"] = _mileage_eligible_for_flight(f, preferred)
    all_flights.sort(key=lambda x: _recommend_sort_key(x, preferred, use_miles))
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
    skip_ke_oz_supplement: bool = False,
    preferred_return_airline_code: str | None = None,
) -> tuple[list[dict], list[str], bool]:
    """SerpApi Google Flights 호출. 마일리지 계획용 KE/OZ가 없으면 include_airlines 보강 병합.
    skip_ke_oz_supplement=True: 날짜 다건 병렬 검색 등에서 호출 후 상위에서 한 번만 보강.
    one_way=True 시 편도 검색.
    preferred_return_airline_code: 귀국편에서 해당 항공사 우선(SerpApi include_airlines 후 0건이면 전체 재검색).
    Returns (flights, warnings, api_responded_ok)."""
    api_key = config.get("serpapi_api_key", "")
    if not api_key:
        return [], ["SerpApi API 키가 설정되지 않았습니다. .env에 SERPAPI_API_KEY 추가."], False

    raw_pref = (preferred_return_airline_code or "").strip().upper()
    pref = raw_pref[:2] if len(raw_pref) >= 2 else ""
    if pref and not pref.isalpha():
        pref = ""
    extra_pref_w: list[str] = []

    try:
        flights, warnings = await search_serpapi(
            origin, destination, start_date, end_date, api_key, seat_class, one_way=one_way,
            include_airlines=pref if (one_way and pref) else None,
        )
        if one_way and pref and not flights:
            flights, warnings = await search_serpapi(
                origin, destination, start_date, end_date, api_key, seat_class, one_way=one_way
            )
            extra_pref_w.append(
                f"출국편 동일 항공사({pref}) 귀국편이 없어 전체 항공사로 다시 검색했습니다."
            )
        elif one_way and pref and flights:
            extra_pref_w.append(f"출국편과 동일 항공사({pref}) 귀국편을 우선 표시합니다.")
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

    if not skip_ke_oz_supplement:
        unique, warnings = await _merge_ke_oz_serpapi_supplements(
            unique,
            warnings,
            origin,
            destination,
            start_date,
            end_date,
            api_key,
            seat_class,
            one_way,
            deep_search=False,
        )

    preferred_airlines = _get_preferred_airlines(mileage_program)
    for f in unique:
        f["mileage_eligible"] = _mileage_eligible_for_flight(f, preferred_airlines)
    sort_fn = lambda x: _recommend_sort_key(x, preferred_airlines, use_miles)
    if one_way and pref:
        unique.sort(
            key=lambda x: (
                0 if (_carrier_code_from_flight_dict(x) or "").upper() == pref else 1,
                _recommend_sort_key(x, preferred_airlines, use_miles),
            )
        )
    else:
        unique.sort(key=sort_fn)
    if extra_pref_w:
        warnings = list(warnings) + extra_pref_w

    return unique, warnings, api_responded_ok


async def _travelpayouts_cache_fallback(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    config: dict,
    *,
    one_way: bool,
    seat_class: str,
    use_miles: bool,
    mileage_program: str | None,
) -> tuple[list[dict], list[str]]:
    """
    SerpApi·Amadeus에 결과가 없을 때만: Travelpayouts 캐시 최저가·제휴 링크 참고.
    """
    token = (config.get("travelpayouts_api_token") or "").strip()
    if not token:
        return [], []
    tp_flights, tp_w = await search_travelpayouts_flights(
        origin,
        destination,
        start_date,
        end_date,
        token,
        one_way=one_way,
        seat_class=seat_class,
        marker=(config.get("travelpayouts_marker") or "").strip(),
    )
    preferred_airlines = _get_preferred_airlines(mileage_program)
    if not tp_flights:
        return [], list(tp_w)

    seen_tp: set = set()
    unique_tp: list = []
    for f in tp_flights:
        if f.get("round_trip"):
            key = (
                "rt",
                f.get("flight_id"),
                (f.get("outbound") or {}).get("departure"),
                (f.get("return") or {}).get("departure"),
            )
        else:
            key = (f.get("airline"), f.get("flight_number"), f.get("departure"))
        if key not in seen_tp:
            seen_tp.add(key)
            unique_tp.append(f)

    for f in unique_tp:
        f["mileage_eligible"] = _mileage_eligible_for_flight(f, preferred_airlines)
    unique_tp.sort(key=lambda x: _recommend_sort_key(x, preferred_airlines, use_miles))
    unique_tp, ew = await _enrich_direct_first_and_cheapest(
        unique_tp,
        origin,
        destination,
        start_date,
        end_date,
        config,
        one_way,
        seat_class,
        use_miles,
        mileage_program,
        preferred_airlines,
        "travelpayouts",
    )
    prefix = (
        "[Travelpayouts] SerpApi·Amadeus에 표시할 결과가 없어 "
        "캐시 기준 최저가(참고)만 표시합니다."
    )
    merged_w = [prefix] + list(dict.fromkeys([*tp_w, *ew]))
    return unique_tp, merged_w


def multi_source_search_flights(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    seat_class: str = "economy",
    use_miles: bool = False,
    mileage_program: str | None = None,
    travelpayouts_api_token: str = "",
    travelpayouts_marker: str = "",
    serpapi_api_key: str = "",
    amadeus_client_id: str = "",
    amadeus_client_secret: str = "",
    date_flexibility_days: int | None = None,
    one_way: bool = False,
    preferred_return_airline_code: str | None = None,
) -> tuple[list[dict], list[str], str]:
    """
    SerpApi Google Flights 우선 → Amadeus(429 등) → Travelpayouts 캐시(참고) → Mock.
    대한항공(KE)·아시아나(OZ)는 마일리지 계획상 항상 노출되도록 SerpApi 보강·Amadeus 병합을 수행.
    왕복 + date_flexibility_days>=2: 출발일±N·귀환일±N 각각 편도 검색 후 조합, 가격 싼 순.
    그 외: 기존 (날짜쌍 왕복) 또는 편도 검색.
    Returns (flights, warnings, flight_search_api) — 세 번째 값은 실제로 표시 데이터를 만든 API 설명 문자열.
    """
    config = {
        "travelpayouts_api_token": travelpayouts_api_token,
        "travelpayouts_marker": travelpayouts_marker,
        "serpapi_api_key": serpapi_api_key,
        "amadeus_client_id": amadeus_client_id,
        "amadeus_client_secret": amadeus_client_secret,
    }
    flex = date_flexibility_days or 0

    async def _run():
        preferred = _get_preferred_airlines(mileage_program)

        # 왕복 + 날짜 유연성: 2단계 (편도로 조합 추출 → 왕복 deep_search로 정확한 가격)
        if not one_way and flex >= 1:
            flights, warnings, api_ok, ob_range, ret_range = await _search_round_trip_flex_2phase(
                origin, destination, start_date, end_date,
                seat_class, use_miles, mileage_program, config, flex,
            )
            if flights and api_ok:
                flights, ew = await _enrich_direct_first_and_cheapest(
                    flights, origin, destination, start_date, end_date,
                    config, one_way, seat_class, use_miles, mileage_program,
                    preferred, "serpapi",
                )
                warnings.extend(ew)
            api_lbl = FLIGHT_SEARCH_API_SERPAPI if flights else ""
            return flights, warnings, api_ok, ob_range, ret_range, api_lbl
        # 단일 날짜 또는 편도
        date_pairs = _date_pairs_with_flexibility(start_date, end_date, flex)
        if len(date_pairs) == 1:
            fl, wa, ok = await _search_serpapi_only(
                origin, destination, date_pairs[0][0], date_pairs[0][1],
                seat_class, use_miles, mileage_program, config, one_way=one_way,
                preferred_return_airline_code=preferred_return_airline_code,
            )
            if fl and ok:
                fl, ew = await _enrich_direct_first_and_cheapest(
                    fl, origin, destination, start_date, end_date,
                    config, one_way, seat_class, use_miles, mileage_program,
                    preferred, "serpapi",
                )
                wa.extend(ew)
            return fl, wa, ok, "", "", (FLIGHT_SEARCH_API_SERPAPI if fl else "")
        tasks = [
            _search_serpapi_only(
                origin, destination, ds, de, seat_class, use_miles,
                mileage_program, config, one_way=one_way, skip_ke_oz_supplement=True,
                preferred_return_airline_code=preferred_return_airline_code,
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
        if unique and (config.get("serpapi_api_key") or "").strip():
            unique, all_warnings = await _merge_ke_oz_serpapi_supplements(
                unique,
                all_warnings,
                origin,
                destination,
                start_date,
                end_date,
                config["serpapi_api_key"].strip(),
                seat_class,
                one_way,
                deep_search=False,
            )
        for f in unique:
            f["mileage_eligible"] = _mileage_eligible_for_flight(f, preferred)
        unique.sort(key=lambda x: _recommend_sort_key(x, preferred, use_miles))
        if unique and api_responded_ok:
            unique, ew = await _enrich_direct_first_and_cheapest(
                unique, origin, destination, start_date, end_date,
                config, one_way, seat_class, use_miles, mileage_program,
                preferred, "serpapi",
            )
            all_warnings.extend(ew)
        api_lbl_m = FLIGHT_SEARCH_API_SERPAPI if unique else ""
        return unique, list(dict.fromkeys(all_warnings)), api_responded_ok, "", "", api_lbl_m

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None:
        flights, warnings, api_responded_ok, ob_range, ret_range, search_api_label = asyncio.run(_run())
    else:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, _run())
            flights, warnings, api_responded_ok, ob_range, ret_range, search_api_label = future.result()

    if flights and not search_api_label:
        search_api_label = FLIGHT_SEARCH_API_SERPAPI

    if not flights:
        # SerpAPI 한도 초과 시 Amadeus fallback 시도 (날짜 유연성 early return보다 먼저)
        has_quota_msg = any("한도" in w or "429" in w for w in warnings)
        if has_quota_msg and not (amadeus_client_id and amadeus_client_secret):
            warnings.append(
                "Amadeus API(AMADEUS_CLIENT_ID, AMADEUS_CLIENT_SECRET)를 .env에 설정하면 한도 초과 시 실시간 검색이 가능합니다. FLIGHT_API_SETUP.md §1.1 참조."
            )
        if has_quota_msg and amadeus_client_id and amadeus_client_secret:
            from mcp_servers.flight.amadeus_clients import search_amadeus_with_preferred

            def _run_amadeus():
                async def _do():
                    date_pairs = (
                        _date_pairs_with_flexibility(start_date, end_date, flex)
                        if flex >= 1 and not one_way
                        else [(start_date, end_date)]
                    )
                    amadeus_flights, amadeus_warnings = await search_amadeus_with_preferred(
                        origin,
                        destination,
                        start_date,
                        end_date,
                        amadeus_client_id,
                        amadeus_client_secret,
                        mileage_program=mileage_program,
                        date_pairs=date_pairs,
                        one_way=one_way,
                        seat_class=seat_class,
                    )
                    if amadeus_flights:
                        preferred_airlines = _get_preferred_airlines(mileage_program)
                        amadeus_flights, ew = await _enrich_direct_first_and_cheapest(
                            amadeus_flights, origin, destination, start_date, end_date,
                            config, one_way, seat_class, use_miles, mileage_program,
                            preferred_airlines, "amadeus",
                        )
                        amadeus_warnings.extend(ew)
                    return amadeus_flights, amadeus_warnings

                return asyncio.run(_do())

            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    amadeus_flights, amadeus_warnings = pool.submit(_run_amadeus).result()
                if amadeus_flights:
                    flights = amadeus_flights
                    warnings.extend(amadeus_warnings)
                    preferred_airlines = _get_preferred_airlines(mileage_program)
                    for f in flights:
                        f["mileage_eligible"] = _mileage_eligible_for_flight(f, preferred_airlines)
                    flights.sort(key=lambda x: _recommend_sort_key(x, preferred_airlines, use_miles))
                    return flights, warnings, FLIGHT_SEARCH_API_AMADEUS
                warnings.extend(amadeus_warnings)
            except Exception as e:
                warnings.append(f"Amadeus fallback 실패: {e}")
        # SerpApi·Amadeus 모두 결과 없음 → Travelpayouts 캐시 최저가(참고)
        if not flights and (travelpayouts_api_token or "").strip():

            def _run_tp_fallback():
                async def _do():
                    return await _travelpayouts_cache_fallback(
                        origin,
                        destination,
                        start_date,
                        end_date,
                        config,
                        one_way=one_way,
                        seat_class=seat_class,
                        use_miles=use_miles,
                        mileage_program=mileage_program,
                    )

                return asyncio.run(_do())

            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    tp_flights, tp_warnings = pool.submit(_run_tp_fallback).result()
                if tp_flights:
                    flights = tp_flights
                    warnings = list(dict.fromkeys([*warnings, *tp_warnings]))
                    return flights, warnings, FLIGHT_SEARCH_API_TRAVELPAYOUTS
                warnings.extend(tp_warnings)
            except Exception as e:
                warnings.append(f"Travelpayouts 보조 검색 실패: {e}")
        # 0건 시: 날짜범위 메시지로 안내 (편도조합 방식 사용 시, Amadeus도 실패한 경우)
        if not flights and ob_range and ret_range and flex >= 1 and not one_way:
            warnings.append(
                f"출발일 {ob_range}까지와 귀환일 {ret_range} 사이에 해당되는 왕복 항공편이 없습니다."
            )
            return [], warnings, ""
        # 그 외: Mock 폴백
        from mcp_servers.flight.mock_fallback import mock_search_flights

        flights = mock_search_flights(
            origin, destination, start_date, end_date, seat_class, use_miles, one_way=one_way
        )
        preferred_airlines = _get_preferred_airlines(mileage_program)
        for f in flights:
            f["mileage_eligible"] = _mileage_eligible_for_flight(f, preferred_airlines)
        flights.sort(key=lambda x: _recommend_sort_key(x, preferred_airlines, use_miles))
        api_error_keywords = ("인증", "API 키가", "토큰", "검색 실패", "401", "403", "404", "500", "API 오류")
        has_quota_msg = any("한도" in w or "429" in w for w in warnings)
        has_api_error = any(any(kw in w for kw in api_error_keywords) for w in warnings)
        if has_quota_msg:
            pass
        elif api_responded_ok and not has_api_error:
            warnings.append(
                "검색 결과가 없습니다. (가능한 원인: 노선/날짜 조합, SerpApi·Travelpayouts·Amadeus 일시적 오류 등) "
                "예시(Mock) 데이터로 보여드립니다."
            )
        else:
            warnings.append("실제 API 결과 없음. Mock 데이터로 대체합니다.")
        return flights, warnings, FLIGHT_SEARCH_API_MOCK
    return flights, warnings, search_api_label


def multi_source_search_flights_multi_dest(
    origin: str,
    destination_airports: list[str],
    start_date: str,
    end_date: str,
    seat_class: str = "economy",
    use_miles: bool = False,
    mileage_program: str | None = None,
    travelpayouts_api_token: str = "",
    travelpayouts_marker: str = "",
    serpapi_api_key: str = "",
    amadeus_client_id: str = "",
    amadeus_client_secret: str = "",
    date_flexibility_days: int | None = None,
    one_way: bool = False,
) -> tuple[list[dict], list[str], str]:
    """
    다중 도착 공항 검색. 마일리지 직항 우선순으로 각 공항 검색 후 병합.
    정렬: 1) 마일리지 직항 공항·선호 항공사 2) 가격순
    Returns (flights, warnings, flight_search_api) — 공항별 소스가 다르면 한 줄로 병합 표기.
    """
    airport_labels = {"MXP": "밀라노", "MUC": "뮌헨", "VCE": "베니스", "VRN": "베로나", "INN": "인스부르크", "TSF": "베니스", "BZO": "볼차노"}
    all_flights: list[dict] = []
    all_warnings: list[str] = []
    preferred_airlines = _get_preferred_airlines(mileage_program)
    api_labels_seen: list[str] = []

    for i, dest in enumerate(destination_airports):
        flights, warnings, api_lbl = multi_source_search_flights(
            origin, dest, start_date, end_date, seat_class, use_miles,
            mileage_program=mileage_program,
            travelpayouts_api_token=travelpayouts_api_token,
            travelpayouts_marker=travelpayouts_marker,
            serpapi_api_key=serpapi_api_key,
            amadeus_client_id=amadeus_client_id,
            amadeus_client_secret=amadeus_client_secret,
            date_flexibility_days=date_flexibility_days,
            one_way=one_way,
        )
        if api_lbl and api_lbl not in api_labels_seen:
            api_labels_seen.append(api_lbl)
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
    if not api_labels_seen:
        combined_api = ""
    elif len(api_labels_seen) == 1:
        combined_api = api_labels_seen[0]
    else:
        combined_api = "공항별 검색 소스: " + " · ".join(api_labels_seen)
    return unique, list(dict.fromkeys(all_warnings)), combined_api  # 중복 경고 제거


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

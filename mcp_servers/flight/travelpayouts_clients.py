"""Travelpayouts Flight Data API — 캐시 기반 최저가 (cheap / direct).

https://api.travelpayouts.com/documentation
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

BASE_URL = "https://api.travelpayouts.com"

# Travelpayouts Data API는 문서상 origin/destination에 **도시 IATA**를 기대합니다.
# 공항 코드만 넣으면 success=True 인데 data={} 인 경우가 많습니다.
_AIRPORT_IATA_TO_CITY_IATA: dict[str, str] = {
    "ICN": "SEL",
    "GMP": "SEL",
    "MXP": "MIL",
    "LIN": "MIL",
    "BGY": "MIL",
    "NRT": "TYO",
    "HND": "TYO",
    "KIX": "OSA",
    "ITM": "OSA",
    "CDG": "PAR",
    "ORY": "PAR",
    "BVA": "PAR",
    "LHR": "LON",
    "LGW": "LON",
    "STN": "LON",
    "LTN": "LON",
    "LCY": "LON",
    "SXF": "BER",
    "TXL": "BER",
    "BER": "BER",
    "FCO": "ROM",
    "CIA": "ROM",
    "JFK": "NYC",
    "EWR": "NYC",
    "LGA": "NYC",
}


def _tp_city_code_for_api(airport_or_city: str) -> str:
    c = (airport_or_city or "").strip().upper()[:3]
    return _AIRPORT_IATA_TO_CITY_IATA.get(c, c)


# 응답 통화가 KRW가 아닐 때 대략 환산 (표시용)
_ROUGH_KRW_PER_UNIT = {"usd": 1400, "eur": 1500, "rub": 18, "gbp": 1800}


def _iso_from_tp_at(s: str | None) -> str:
    """Travelpayouts ISO 시간 → 프론트용 YYYY-MM-DDTHH:MM:SS (로컬 표시 근사)."""
    if not s:
        return ""
    t = str(s).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(t)
        return dt.strftime("%Y-%m-%dT%H:%M:00")
    except ValueError:
        if len(s) >= 19:
            return s[:19].replace(" ", "T")
        return s


def _row_has_travelpayouts_fare(d: dict) -> bool:
    """티켓/요금 행인지 (중첩 메타데이터·스칼라만 있는 dict 제외)."""
    if not isinstance(d, dict):
        return False
    amount = d.get("price")
    if amount is None:
        amount = d.get("value")
    if amount is None:
        return False
    if d.get("departure_at") or d.get("depart_date"):
        return True
    if d.get("airline") or d.get("flight_number") is not None:
        return True
    if d.get("origin") and d.get("destination"):
        return True
    return False


def _collect_fare_rows(raw: Any) -> list[dict[str, Any]]:
    """
    Travelpayouts `data` 필드의 모든 관례적 형태에서 요금 행만 수집.

    - 문서 예: { \"HKT\": { \"0\": { ticket }, \"1\": ... } }
    - 단일 건: { \"HKT\": { ticket } }  (인덱스 없음 — 기존 파서는 여기서 0건이 됨)
    - 배열: { \"data\": [ { value, depart_date, ... }, ... ] }
    - 혼합 중첩: 재귀적으로 dict 값·list 원소만 순회
    """
    out: list[dict[str, Any]] = []
    seen: set[int] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if _row_has_travelpayouts_fare(node):
                i = id(node)
                if i not in seen:
                    seen.add(i)
                    out.append(node)
                return
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for x in node:
                walk(x)

    walk(raw)
    return out


def _describe_raw_data(raw: Any) -> str:
    """진단용: data 필드 모양만 요약 (토큰·대용량 본문 노출 없음)."""
    if raw is None:
        return "data=null (필드 없음)"
    if isinstance(raw, dict):
        if not raw:
            return "data={} 빈 객체"
        keys = list(raw.keys())[:6]
        more = " …" if len(raw) > 6 else ""
        return f"data=객체, 키 {len(raw)}개 (예: {keys}{more})"
    if isinstance(raw, list):
        return f"data=배열, 길이 {len(raw)}"
    return f"data=예상 외 타입({type(raw).__name__})"


def _ticket_amount(row: dict[str, Any]) -> float | None:
    p = row.get("price")
    if p is not None:
        try:
            return float(p)
        except (TypeError, ValueError):
            pass
    v = row.get("value")
    if v is not None:
        try:
            return float(v)
        except (TypeError, ValueError):
            pass
    return None


def _departure_iso_from_row(row: dict[str, Any]) -> str:
    if row.get("departure_at"):
        return _iso_from_tp_at(row.get("departure_at"))
    dd = row.get("depart_date")
    if dd:
        ds = str(dd).strip()[:10]
        if len(ds) == 10:
            return f"{ds}T12:00:00"
    return ""


def _return_iso_from_row(row: dict[str, Any]) -> str:
    if row.get("return_at"):
        return _iso_from_tp_at(row.get("return_at"))
    rd = row.get("return_date")
    if rd is not None and str(rd).strip() and str(rd).strip().lower() not in ("null", "none"):
        ds = str(rd).strip()[:10]
        if len(ds) == 10:
            return f"{ds}T12:00:00"
    return ""


def _price_to_krw(amount: float | int | None, currency: str) -> int | None:
    if amount is None:
        return None
    try:
        v = float(amount)
    except (TypeError, ValueError):
        return None
    c = (currency or "rub").lower()
    if c == "krw":
        return int(round(v))
    mult = _ROUGH_KRW_PER_UNIT.get(c, 1400 if c == "usd" else 1500)
    return int(round(v * mult))


def build_aviasales_search_url(
    origin: str,
    destination: str,
    depart_date: str,
    return_date: str | None,
    marker: str,
    *,
    one_way: bool,
    currency: str = "KRW",
) -> str:
    """Aviasales 검색 딥링크 (marker=제휴 마커)."""
    o = (origin or "").upper()[:3]
    d = (destination or "").upper()[:3]
    dep = (depart_date or "")[:10]
    ret = (return_date or "")[:10] if return_date else ""
    if one_way or not ret:
        path = f"{o}/{d}/{dep}"
    else:
        path = f"{o}/{d}/{dep}/{ret}"
    q = {
        "marker": marker,
        "currency": currency,
        "adults": 1,
        "children": 0,
        "infants": 0,
        "is_one_way": "true" if one_way else "false",
    }
    return f"https://www.aviasales.com/search/{path}?{urlencode(q)}"


def _leg_from_tp(
    airline: str,
    flight_number: str | int,
    dep_iso: str,
    arr_iso: str,
    origin: str,
    destination: str,
    duration_hours: float | None,
    is_direct: bool,
    seat_class: str,
) -> dict[str, Any]:
    fn = str(flight_number).strip() if flight_number is not None else ""
    return {
        "airline": airline or "Unknown",
        "flight_number": fn,
        "departure": dep_iso,
        "arrival": arr_iso,
        "origin": origin,
        "destination": destination,
        "duration_hours": duration_hours,
        "is_direct": is_direct,
        "seat_class": seat_class,
        "source": "api",
    }


def _estimate_arrival(dep_iso: str, duration_hours: float | None) -> str:
    if not dep_iso or not duration_hours or duration_hours <= 0:
        return dep_iso
    try:
        raw = dep_iso.replace("T", " ")[:19]
        dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        return (dt + timedelta(hours=duration_hours)).strftime("%Y-%m-%dT%H:%M:00")
    except ValueError:
        return dep_iso


async def search_travelpayouts_flights(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    token: str,
    *,
    one_way: bool = False,
    seat_class: str = "economy",
    marker: str = "",
    direct_only: bool = False,
    currency: str = "krw",
    quiet: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    cheap 또는 direct 엔드포인트 호출 → SerpApi와 유사한 flight / round_trip dict 목록.
    """
    warnings: list[str] = []
    o_user = (origin or "").strip().upper()[:3]
    d_user = (destination or "").strip().upper()[:3]
    if len(o_user) != 3 or len(d_user) != 3:
        return [], ["Travelpayouts: 출발/도착은 IATA 코드 3자리여야 합니다."]

    if not (token or "").strip():
        return [], []

    depart = (start_date or "")[:10]
    ret_part = (end_date or "")[:10] if not one_way else None
    token_s = token.strip()
    headers = {"X-Access-Token": token_s}

    path = "/v1/prices/direct" if direct_only else "/v1/prices/cheap"

    o_city = _tp_city_code_for_api(o_user)
    d_city = _tp_city_code_for_api(d_user)
    code_trials: list[tuple[str, str, str]] = [(o_user, d_user, "입력 코드(공항·도시 그대로)")]
    if (o_city, d_city) != (o_user, d_user):
        code_trials.append(
            (o_city, d_city, f"도시 IATA로 재시도(문서 권장: {o_user}->{o_city}, {d_user}->{d_city})"),
        )

    items: list[dict[str, Any]] = []
    body: dict[str, Any] = {}
    raw_data: Any = None
    resp_currency = str(currency or "krw").lower()
    last_params: dict[str, str] = {}
    used_trial_label = code_trials[0][2]
    o_api, d_api = o_user, d_user

    for o_try, d_try, trial_label in code_trials:
        last_params = {
            "origin": o_try,
            "destination": d_try,
            "currency": currency.lower(),
            "depart_date": depart if len(depart) == 10 else (start_date or "")[:7],
            "token": token_s,
        }
        if ret_part and len(ret_part) == 10:
            last_params["return_date"] = ret_part
        elif not one_way and end_date:
            last_params["return_date"] = (end_date or "")[:7]

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(f"{BASE_URL}{path}", headers=headers, params=last_params)
        except httpx.RequestError as e:
            return [], [
                "[Travelpayouts 진단] 네트워크 단계 실패 — api.travelpayouts.com 에 연결되지 못했습니다 "
                f"(DNS·방화벽·프록시·타임아웃 등). 상세: {e}"
            ]

        if resp.status_code == 429:
            return [], [
                "[Travelpayouts 진단] 서버에는 도달했으나 HTTP 429(요청 한도 초과). "
                "잠시 후 재시도하거나 호출 빈도를 줄이세요."
            ]
        if resp.status_code == 401:
            return [], [
                "[Travelpayouts 진단] HTTP 401 Unauthorized — API 토큰이 거부되었습니다. "
                "TRAVELPAYOUTS_API_TOKEN 을 Travelpayouts 프로그램 도구 페이지에서 다시 확인하세요."
            ]
        if resp.status_code == 403:
            return [], [
                "[Travelpayouts 진단] HTTP 403 Forbidden — 접근이 거부되었습니다. "
                "토큰 권한·IP 제한·계정 상태를 확인하세요."
            ]
        if resp.status_code != 200:
            snip = (resp.text or "").strip().replace("\n", " ")[:200]
            tail = f" 응답 본문 일부: {snip!r}" if snip else " 응답 본문이 비어 있습니다."
            return [], [
                f"[Travelpayouts 진단] 서버에는 TCP 연결됐으나 HTTP {resp.status_code} 오류.{tail}"
            ]

        try:
            body = resp.json()
        except Exception as e:
            return [], [
                "[Travelpayouts 진단] HTTP 200 이지만 JSON으로 파싱할 수 없습니다. "
                f"프록시/HTML 오류 페이지일 수 있습니다. ({e})"
            ]

        err_top = body.get("error")
        if err_top:
            return [], [f"[Travelpayouts 진단] API 오류 필드: {err_top}"]

        if body.get("success") is False:
            msg = body.get("message") or body.get("description") or "success=false"
            return [], [
                f"[Travelpayouts 진단] 응답 수신했으나 success=false — {msg}"
            ]

        resp_currency = str(body.get("currency") or currency or "krw").lower()
        raw_data = body.get("data")
        items = _collect_fare_rows(raw_data) if raw_data is not None else []
        o_api, d_api = o_try, d_try
        used_trial_label = trial_label
        if items:
            if trial_label != code_trials[0][2]:
                warnings.append(
                    f"[Travelpayouts] {trial_label} — 캐시에서 요금 행을 찾았습니다. "
                    "(Data API는 도시 코드 조합에 데이터가 더 자주 있습니다.)"
                )
            break

    month_followed = False
    month_had_rows = False
    if not items and len(depart) == 10:
        month_followed = True
        params_month = {**last_params, "depart_date": depart[:7]}
        if "return_date" in last_params and len(last_params["return_date"]) == 10:
            params_month["return_date"] = last_params["return_date"][:7]
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp2 = await client.get(f"{BASE_URL}{path}", headers=headers, params=params_month)
            if resp2.status_code == 200:
                body2 = resp2.json()
                if body2.get("error"):
                    warnings.append(
                        f"[Travelpayouts] 월(yyyy-mm) 재요청 응답 error={body2.get('error')!r}"
                    )
                elif body2.get("success") is not False:
                    items = _collect_fare_rows(body2.get("data"))
                    resp_currency = str(body2.get("currency") or resp_currency).lower()
                    month_had_rows = bool(items)
                    if items:
                        warnings.append(
                            "Travelpayouts: 일별(yyyy-mm-dd) 캐시가 비어 월(yyyy-mm) 단위로 같은 엔드포인트를 "
                            "한 번 더 조회했습니다."
                        )
            else:
                warnings.append(f"[Travelpayouts] 월 단위 재요청 HTTP {resp2.status_code}")
        except Exception as e:
            warnings.append(f"[Travelpayouts] 월 단위 재요청 예외: {e}")

    week_path = "/v2/prices/week-matrix"
    if not items and len(depart) == 10:
        wm_params: dict[str, str] = {
            "currency": currency.lower(),
            "origin": o_api,
            "destination": d_api,
            "depart_date": depart,
            "show_to_affiliates": "false",
            "token": token_s,
        }
        if ret_part and len(ret_part) == 10:
            wm_params["return_date"] = ret_part
        elif not one_way and end_date:
            wm_params["return_date"] = (end_date or "")[:10]
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp_w = await client.get(f"{BASE_URL}{week_path}", headers=headers, params=wm_params)
            if resp_w.status_code == 200:
                wb = resp_w.json()
                if wb.get("success") is not False and not wb.get("error"):
                    w_items = _collect_fare_rows(wb.get("data"))
                    if w_items:
                        items = w_items
                        body = wb
                        raw_data = wb.get("data")
                        resp_currency = str(wb.get("currency") or resp_currency).lower()
                        path = week_path
                        warnings.append(
                            f"[Travelpayouts] /v1/prices/cheap 에는 캐시가 없어 "
                            f"{week_path} (주변 날짜 매트릭스, show_to_affiliates=false) 로 보조 조회했습니다."
                        )
        except Exception as e:
            warnings.append(f"[Travelpayouts] week-matrix 보조 조회 예외: {e}")

    if not items:
        req_ret = last_params.get("return_date", "")
        safe_params = {k: v for k, v in last_params.items() if k != "token"}
        month_note = ""
        if month_followed:
            month_note = (
                " 같은 조건으로 출발·귀환을 yyyy-mm(월)로도 요청했으나 "
                + ("요금 행을 얻었습니다." if month_had_rows else "여전히 비어 있었습니다.")
            )
        diag = [
            "[Travelpayouts 진단] API 연결·HTTP 200·JSON 정상입니다. (토큰·네트워크 문제는 아님)",
            f"마지막 시도: {used_trial_label}. GET {BASE_URL}{path} 파라미터(토큰 제외)={safe_params!r}.",
            f"응답: success={body.get('success')!s}, currency={resp_currency!r}, {_describe_raw_data(raw_data)}.",
            "요금 행 0건 → Travelpayouts 캐시 DB에 해당 노선·날짜(먼 미래 연도 등) 조합이 없을 때 "
            "흔히 data={} 로 옵니다. 잘못된 호출이 아니라 데이터 소스 한계일 수 있습니다.",
            "공항 코드(ICN, MXP 등)만으로 빈 응답이 나오면 도시 코드(SEL, MIL 등)로 자동 재시도합니다; "
            "그래도 비면 SerpApi 등 실시간 검색으로 이어집니다.",
        ]
        if month_followed and not month_had_rows:
            diag.insert(
                3,
                "[Travelpayouts] cheap 엔드포인트는 특정 일에 캐시가 없으면 월 단위로 한 번 더 묻는 것이 API 관례입니다."
                + month_note,
            )
        diag.append("아래 SerpApi(또는 Amadeus) 검색은 Travelpayouts와 별도로 진행됩니다.")
        return [], warnings + diag

    mk = (marker or "").strip()
    flights: list[dict[str, Any]] = []

    def _sort_key(row: dict[str, Any]) -> float:
        a = _ticket_amount(row)
        return a if a is not None else 1e18

    for idx, it in enumerate(sorted(items, key=_sort_key)[:40]):
        price_raw = _ticket_amount(it)
        airline = str(it.get("airline") or "").strip() or "요금참고"
        fn = it.get("flight_number", "")
        dep_at = _departure_iso_from_row(it)
        if not dep_at and len(depart) == 10:
            dep_at = f"{depart}T12:00:00"
        ret_at = _return_iso_from_row(it)
        transfers = it.get("number_of_changes", it.get("transfers"))
        if transfers is None:
            is_direct = direct_only
        else:
            try:
                is_direct = int(transfers) == 0
            except (TypeError, ValueError):
                is_direct = direct_only

        dur_min = it.get("duration")
        try:
            dur_h_total = float(dur_min) / 60.0 if dur_min is not None else None
        except (TypeError, ValueError):
            dur_h_total = None

        price_krw = _price_to_krw(price_raw, resp_currency) if price_raw is not None else None
        booking_url = (
            build_aviasales_search_url(o_user, d_user, depart, ret_part, mk, one_way=one_way)
            if mk
            else ""
        )

        if one_way or not ret_at:
            ob_dur = dur_h_total
            ob_arr = _estimate_arrival(dep_at, ob_dur)
            leg = _leg_from_tp(
                airline, fn, dep_at, ob_arr, o_user, d_user, ob_dur, is_direct, seat_class
            )
            flights.append(
                {
                    **leg,
                    "flight_id": f"tp_{idx}_{airline}_{fn}_{dep_at}",
                    "price_krw": price_krw,
                    "miles_required": None,
                    "seat_class": seat_class,
                    "source": "api",
                    "booking_url": booking_url,
                    "data_source": "travelpayouts",
                }
            )
        else:
            ob_dur = (dur_h_total / 2.0) if dur_h_total else 3.0
            ret_dur = (dur_h_total / 2.0) if dur_h_total else 3.0
            ob_arr = _estimate_arrival(dep_at, ob_dur)
            ret_arr = _estimate_arrival(ret_at, ret_dur)
            ob_leg = _leg_from_tp(
                airline, fn, dep_at, ob_arr, o_user, d_user, ob_dur, is_direct, seat_class
            )
            ret_leg = _leg_from_tp(
                airline, fn, ret_at, ret_arr, d_user, o_user, ret_dur, is_direct, seat_class
            )
            flights.append(
                {
                    "round_trip": True,
                    "flight_id": f"tp_rt_{idx}_{airline}_{fn}_{dep_at}",
                    "price_krw": price_krw,
                    "miles_required": None,
                    "seat_class": seat_class,
                    "source": "api",
                    "outbound": ob_leg,
                    "return": ret_leg,
                    "booking_url": booking_url,
                    "data_source": "travelpayouts",
                }
            )

    if flights and not quiet:
        warnings.insert(
            0,
            f"[Travelpayouts 진단] 연결·HTTP 200 정상. `{path}` 응답에서 요금 행 {len(flights)}건을 검색 결과에 반영했습니다.",
        )
        warnings.append(
            "항공료는 Travelpayouts(캐시) 기준 참고가이며, 실시간·최종 가격은 예약 링크(Aviasales)에서 확인하세요."
        )
    return flights, warnings

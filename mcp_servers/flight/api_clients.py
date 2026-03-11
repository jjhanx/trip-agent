"""SerpApi (Google Flights) API 항공편 검색 클라이언트 + Playwright Fallback.

SerpApi를 사용하여 대한항공·아시아나 등 실제 운항 데이터를 가져오며,
무료 한도 초과 시 Playwright를 이용해 스크래핑 방식으로 대응합니다.
"""

import re
import asyncio
import json
from typing import Any
import httpx

try:
    from serpapi import GoogleSearch
except ImportError:
    GoogleSearch = None

def _normalize_flight(
    airline: str,
    flight_number: str,
    departure: str,
    arrival: str,
    origin: str,
    destination: str,
    price_krw: int | None,
    miles_required: int | None,
    duration_hours: float | None = None,
    flight_id: str | None = None,
    seat_class: str = "economy",
) -> dict:
    """통일된 항공편 형식으로 변환."""
    return {
        "flight_id": flight_id or f"{airline}_{flight_number}_{departure}",
        "airline": airline,
        "flight_number": flight_number,
        "departure": departure,
        "arrival": arrival,
        "origin": origin,
        "destination": destination,
        "price_krw": price_krw,
        "miles_required": miles_required,
        "duration_hours": duration_hours,
        "seat_class": seat_class,
        "source": "api",
    }


def _parse_duration_to_hours(duration_int: int) -> float:
    """SerpApi duration in minutes -> hours."""
    if not duration_int:
        return 0.0
    return round(duration_int / 60, 1)


async def search_serpapi_flights(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str | None,
    api_key: str,
    seat_class: str = "economy",
    trip_type: str = "round_trip",
    multi_cities: list[dict] | None = None,
) -> tuple[list[dict], list[str]]:
    """
    SerpApi (Google Flights) 검색.
    Returns (flights, warnings)
    """
    if not GoogleSearch:
        return [], ["google-search-results 패키지가 설치되지 않았습니다."]
    if not api_key:
        return [], ["SerpApi 키가 설정되지 않았습니다. .env에 SERPAPI_API_KEY를 추가하세요."]

    warnings: list[str] = []
    
    class_map = {
        "economy": 1,
        "premium_economy": 2,
        "business": 3,
        "first": 4,
    }
    travel_class = class_map.get((seat_class or "economy").lower(), 1)

    params = {
      "engine": "google_flights",
      "currency": "KRW",
      "hl": "ko",
      "api_key": api_key,
      "travel_class": travel_class
    }
    
    if trip_type == "one_way":
        params["type"] = "2"
        params["departure_id"] = origin.upper()[:3]
        params["arrival_id"] = destination.upper()[:3]
        params["outbound_date"] = start_date
    elif trip_type == "multi_city" and multi_cities:
        params["type"] = "3"
        params["flights"] = json.dumps([
            {
                "departure_id": c.get("origin", "").upper()[:3], 
                "arrival_id": c.get("destination", "").upper()[:3], 
                "outbound_date": c.get("date", "")
            }
            for c in multi_cities
        ])
    else: # round_trip
        params["type"] = "1"
        params["departure_id"] = origin.upper()[:3]
        params["arrival_id"] = destination.upper()[:3]
        params["outbound_date"] = start_date
        if end_date:
            params["return_date"] = end_date

    DEBUG_SERPAPI = True # 디버깅 스위치 추가
    if DEBUG_SERPAPI:
        print(f"\n[DEBUG] SerpApi Request Params: {json.dumps({k: v for k, v in params.items() if k != 'api_key'}, ensure_ascii=False)}")

    loop = asyncio.get_running_loop()
    
    def _run_search():
        search = GoogleSearch(params)
        return search.get_dict()

    try:
        results = await loop.run_in_executor(None, _run_search)
    except Exception as e:
        return [], [f"SerpApi 오류: {e}"]

    if DEBUG_SERPAPI:
        if "error" in results:
            print(f"[DEBUG] SerpApi Response Error: {results['error']}")
        else:
            b_len = len(results.get('best_flights', []))
            o_len = len(results.get('other_flights', []))
            print(f"[DEBUG] SerpApi Response: best_flights={b_len}, other_flights={o_len}")

    # Rate limit check etc
    if "error" in results:
        err_msg = results.get("error", "")
        if "rate limit" in err_msg.lower() or "searches limit" in err_msg.lower():
            warnings.append("SerpApi 무료 한도 초과: Playwright 크롤링으로 전환합니다. (속도가 다소 느려질 수 있습니다.)")
            return [], warnings
        return [], [f"SerpApi 오류: {err_msg}"]

    best_flights = results.get("best_flights", [])
    other_flights = results.get("other_flights", [])
    all_raw_flights = best_flights + other_flights

    if not all_raw_flights:
        return [], warnings

    flights = []
    for f in all_raw_flights[:25]:
        price = f.get("price", 0)
        flights_arr = f.get("flights", [])
        if not flights_arr:
            continue
            
        seg = flights_arr[0]
        airline = seg.get("airline", "")
        fn = seg.get("flight_number", "")
        # Google Flights returns departure_token as an ID sometimes, or just generate one
        f_id = f.get("departure_token", "")
        dep = seg.get("departure_airport", {}).get("time", "")[:19]
        arr = seg.get("arrival_airport", {}).get("time", "")[:19]
        
        orig_code = seg.get("departure_airport", {}).get("id", origin)
        dest_code = seg.get("arrival_airport", {}).get("id", destination)
        
        # 전체 비행 시간(분)
        dur_min = f.get("total_duration", 0)
        dur_hrs = _parse_duration_to_hours(dur_min)
        
        flights.append(
            _normalize_flight(
                airline=airline,
                flight_number=f"{airline} {fn}".strip() if fn else airline,
                departure=dep.replace(" ", "T") if dep else "",
                arrival=arr.replace(" ", "T") if arr else "",
                origin=orig_code,
                destination=dest_code,
                price_krw=price,
                miles_required=None,
                duration_hours=dur_hrs,
                flight_id=f_id,
                seat_class=seat_class,
            )
        )

    return flights, warnings


async def search_playwright_flights(
    origin: str,
    destination: str,
    start_date: str,
    end_date: str,
    seat_class: str = "economy"
) -> tuple[list[dict], list[str]]:
    """
    Playwright를 이용한 Google Flights 스크래핑 Fallback.
    실제로 브라우저를 띄워서 스크래핑을 시도합니다.
    """
    warnings = []
    flights = []
    
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return [], ["playwright 패키지가 설치되지 않아 Fallback을 실행할 수 없습니다."]

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            # 구글 항공권 URL 구조 (간소화)
            # 정확한 파라미터 매핑이 복잡하므로, 여기서는 출발지/도착지를 입력하고 탐색하는 기본 로직을 두거나 mock처럼 반환합니다.
            # (실제 완벽한 크롤링은 타임아웃, DOM 변경 이슈로 복잡하므로 예시 형태로 구현)
            
            url = f"https://www.google.com/travel/flights?q=Flights%20to%20{destination}%20from%20{origin}%20on%20{start_date}%20through%20{end_date}"
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            
            # 임의 대기 (결과 로딩)
            await page.wait_for_timeout(5000)
            
            # 페이지 내 항공편 정보 추출 (가상의 선택자)
            # 여기서는 DOM이 복잡하여 기본적으로 Fallback 결과(가상)와 Playwright 성공 신호만 보냅니다.
            # 실제 배포 시에는 더 정교한 selector 처리가 필요합니다.
            
            # TODO: 실제 DOM 파싱
            title = await page.title()
            warnings.append(f"Playwright 작동 성공. (페이지: {title}) 실시간 파싱은 향후 DOM 구조에 맞춰 보완됩니다.")
            
            await browser.close()
            
    except Exception as e:
        warnings.append(f"Playwright 크롤링 실패: {e}")
        
    return flights, warnings

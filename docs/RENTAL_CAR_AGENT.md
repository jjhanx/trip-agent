# 렌트카 선택 Agent 구현 가이드

## 1. 현재 아키텍처

```
[사용자] → 항공편 선택 후 "다음" 클릭
    ↓
[Session Agent] (main.py / agents/session/executor.py)
    - 조건: flight_complete && !selected_local_transport
    - travel.local_transport == "rental_car" → Rental Car Agent 호출
    - travel.local_transport == "public_transit" → Transit Agent 호출
    ↓
[Rental Car Agent] (agents/rental_car/server.py, executor.py)
    - A2AClient로 HTTP 호출
    - MCP `search_rentals` 또는 `search_rentals_combined` 폴백
    ↓
[Session Agent] → { step: "rental", local_transport: [...] } 반환
    ↓
[프론트엔드] (frontend/app.js)
    - data.step === 'rental' → step-rental 표시
    - renderRentalOptions(state.localTransport)
```

### 1.1 데이터 소스 (요약)

- **Amadeus Transfer Offers** (`AMADEUS_CLIENT_ID`/`SECRET`, 항공과 동일): 공항(IATA)→시내·시내→공항 **1회 이동** 견적. 차종 설명·좌석·견적 금액(원화는 고정 환율 환산). **장기 셀프 드라이브 렌트 총액과는 다른 상품**임을 카드 문구로 구분.
- **EconomyBookings**: 픽업·반납 **날짜**가 URL에 반영된 **셀프 드라이브 비교** 링크. 실시간 총액은 해당 사이트에서 확인.
- **Travelpayouts 제휴 URL** (선택, `TRAVELPAYOUTS_RENTAL_BOOKING_URL`): 공개 Data API 없음. 제휴 카드만 추가.

구현: `mcp_servers/rental_car/services.search_rentals_combined`, `amadeus_transfer.py`. 배포·변수는 [DEPLOYMENT.md](../DEPLOYMENT.md), [TRAVELPAYOUTS_API_GUIDE.md](TRAVELPAYOUTS_API_GUIDE.md) 참고.

## 2. 렌트카 단계가 나타나는 조건

| 조건 | 설명 |
|------|------|
| `flight_complete` | 왕복: 출국+귀국 선택 완료 / 편도: 출국 선택 완료 |
| `!selected_local_transport` | 아직 렌트카·대중교통 옵션을 선택하지 않음 |
| `travel.local_transport == "rental_car"` | 여행 정보 폼에서 "렌트카" 선택 |
| `rental_search` (JSON 객체) | 프론트에서 픽업·반납 일시 수정 후 재검색 시. `flight_complete`이면 **렌트 단계만** 다시 응답 |

**Session 조건 판단 순서** (위에서 아래):
1. booking: 항공+일정+숙소 모두 선택됨 → 예약 안내
2. `rental_search` + `rental_car` + 항공 완료 → `{ step: "rental", local_transport }` 만 반환 (일시 수정 후 재검색)
3. accommodation_and_transport: 항공+일정 선택됨, 숙소 미선택 → 숙소+렌트카 같이 표시
4. itinerary: 항공+렌트카 선택됨, 일정 미선택 → 일정 Agent
5. **rental**: 항공 선택 완료, 렌트카/대중교통 미선택 → **렌트카 단계**
6. flight: 그 외 → 항공편 검색

## 3. 렌트카가 안 보일 때 점검사항

### 3.1 서비스 기동 확인
```bash
docker compose ps -a
# session, rental_car 둘 다 Up 상태인지 확인

docker compose logs rental_car   # Rental Car Agent 로그
docker compose logs session      # Session Agent 로그
```

### 3.2 프론트엔드 응답 확인
브라우저 개발자도구(F12) → Network 탭에서 항공 "다음" 클릭 시 요청/응답 확인:
- 요청 body: `selected_flight`, `local_transport: "rental_car"` 포함 여부
- 응답: `{ step: "rental", local_transport: [...] }` 인지

### 3.3 travelInput.local_transport 값
여행 정보 단계에서 **현지 이동**이 "렌트카"로 선택되어 있어야 합니다.
- `frontend/index.html`: `<select name="local_transport">` → `value="rental_car"`

### 3.4 응답 형식
Session이 `local_transport`를 배열로 주지 않으면 리스트가 비어 보입니다:
```javascript
// frontend/app.js 1267행
state.localTransport = Array.isArray(data?.local_transport) ? data.local_transport : [];
```
- `data.local_transport`가 배열 `[{...}, {...}]` 형태여야 함

## 4. Rental Car Agent 구현 상세

### 4.1 RentalCarExecutor (agents/rental_car/executor.py)
- 입력: `pickup`, `dropoff`, `start_date`, `end_date`, `car_type`, `passengers`, 선택 `pickup_datetime`, `dropoff_datetime`, `pickup_airport_iata`
- MCP `search_rentals` 호출 (실패 시 `search_rentals_combined` + Settings의 Amadeus·Travelpayouts URL)
- 출력: JSON 배열 문자열 (`offer_kind`, `price_total_krw`, `booking_url` 등)

### 4.2 MCP Server (mcp_servers/rental_car/server.py)
- `search_rentals`: 위 필드 + 선택 일시·공항 코드. 환경변수 `AMADEUS_*`, `TRAVELPAYOUTS_RENTAL_BOOKING_URL` 사용
- `search_rentals_combined` (services.py): Amadeus 트랜스퍼 + EconomyBookings + 선택 제휴 카드

### 4.3 가격 및 예약 사이트
- **트랜스퍼**: Amadeus `quotation` 기준(원화는 서버 고정 환율 환산, 표시용).
- **셀프 드라이브 총액**: 공개 API 미연동. EconomyBookings 링크에서 픽업·반납일 반영 후 확인.

**실시간 셀프 드라이브 API (향후 후보)**:
- Booking.com Cars 등 파트너 API

### 4.4 Session → Rental Car payload (agents/session/executor.py)
- `_build_local_transport_payload`: `pickup_datetime` = **도착 +1시간**, `dropoff_datetime` = **출발(귀국 등) -2시간**, `pickup_airport_iata`. `date_time`은 대중교통용으로 **실제 도착** 시각 유지
- `_merge_rental_search`: 프론트 `rental_search` `{ pickup_datetime, dropoff_datetime, pickup_iata }` 로 덮어쓰기
- `_rental_car_fallback_json`: Agent 실패 시 동일 로직으로 JSON 생성

```python
lt_payload = {
    "pickup": "MXP 또는 도시명",
    "dropoff": "...",
    "start_date": "YYYY-MM-DD",
    "end_date": "YYYY-MM-DD",
    "pickup_datetime": "YYYY-MM-DDTHH:MM:SS",
    "dropoff_datetime": "...",
    "pickup_airport_iata": "MXP",
    "passengers": 2,
    ...
}
```

## 5. 별도 "렌트카 선택 Agent"가 필요한 경우

현재는 **Session Agent가 오케스트레이터**로, Rental Car Agent를 호출한 뒤 그 결과를 `{ step: "rental", local_transport: [...] }` 형태로 반환합니다.  
따라서 "렌트카 선택"만 담당하는 Agent는 따로 두지 않고, Session이 Rental Car Agent를 호출해 결과를 모아서 전달하는 구조입니다.

다만 다음처럼 **선택 단계를 분리**하고 싶다면:

1. **옵션 조회 전용 Agent** (현재 Rental Car Agent): 검색/목록 반환
2. **선택 확정 Agent** (신규): 사용자가 고른 렌트카를 확정하고 다음 단계로 넘김

이 경우:
- 프론트엔드에서 `selected_local_transport`를 payload에 넣어 Session에 전달
- Session은 `selected_local_transport`가 있으면 일정(Itinerary) Agent로 진행

현재 구조에서는 이 흐름이 이미 구현되어 있습니다.

## 6. 문제 해결 체크리스트

- [ ] Docker: `rental_car` 서비스 Up
- [ ] 여행 정보: "현지 이동" = 렌트카 선택
- [ ] 항공편: 왕복이면 출국+귀국 모두 선택
- [ ] 네트워크: /a2a/ 호출 응답에 `step: "rental"` 포함
- [ ] `local_transport`가 배열이고 최소 1개 항목 존재

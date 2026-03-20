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
    - MCP search_rentals 또는 mock_search_rentals 사용
    ↓
[Session Agent] → { step: "rental", local_transport: [...] } 반환
    ↓
[프론트엔드] (frontend/app.js)
    - data.step === 'rental' → step-rental 표시
    - renderRentalOptions(state.localTransport)
```

### 1.1 Travelpayouts 제휴 링크 (선택)

렌트카는 Travelpayouts **공개 Data API가 없습니다.** `.env`에 `TRAVELPAYOUTS_RENTAL_BOOKING_URL`을 넣으면(대시보드 Link Generator 등에서 생성) `mcp_servers/rental_car/services.mock_search_rentals`가 **목록 최상단**에 제휴 카드를 붙입니다. 이어서 EconomyBookings 비교 카드·참고 차종이 옵니다. 배포·변수 설명은 [DEPLOYMENT.md](../DEPLOYMENT.md) §3.2, [docs/TRAVELPAYOUTS_API_GUIDE.md](TRAVELPAYOUTS_API_GUIDE.md) §6 참고.

## 2. 렌트카 단계가 나타나는 조건

| 조건 | 설명 |
|------|------|
| `flight_complete` | 왕복: 출국+귀국 선택 완료 / 편도: 출국 선택 완료 |
| `!selected_local_transport` | 아직 렌트카·대중교통 옵션을 선택하지 않음 |
| `travel.local_transport == "rental_car"` | 여행 정보 폼에서 "렌트카" 선택 |

**Session 조건 판단 순서** (위에서 아래):
1. booking: 항공+일정+숙소 모두 선택됨 → 예약 안내
2. accommodation_and_transport: 항공+일정 선택됨, 숙소 미선택 → 숙소+렌트카 같이 표시
3. itinerary: 항공+렌트카 선택됨, 일정 미선택 → 일정 Agent
4. **rental**: 항공 선택 완료, 렌트카/대중교통 미선택 → **렌트카 단계**
5. flight: 그 외 → 항공편 검색

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
- 입력: `pickup`, `dropoff`, `start_date`, `end_date`, `car_type`, `passengers`
- MCP `search_rentals` 호출 (실패 시 mock_search_rentals 사용)
- 출력: JSON 배열 문자열 `[{rental_id, provider, car_type, seats, ...}, ...]`

### 4.2 MCP Server (mcp_servers/rental_car/server.py)
- `search_rentals` 도구: pickup, dropoff, start_date, end_date, car_type, passengers
- `mock_search_rentals` (mcp_servers/rental_car/services.py): 차급별 참고 카드 + EconomyBookings 검색 포함

### 4.3 가격 및 예약 사이트
- **가격**: 근거 없는 추정 가격은 표시하지 않음. 실시간 가격은 예약 사이트에서 확인.
- **EconomyBookings.com**: 사용자 선호 사이트. 검색 결과 상단에 "600+ 업체 비교" 카드로 포함. 모든 예약 링크가 EconomyBookings로 연결됨 (픽업지·날짜 파라미터 반영).

**실시간 가격 API (향후 연동 후보)**:
- Amadeus Cars API: `AMADEUS_CLIENT_ID`/`SECRET`로 항공과 동일 계정 사용 가능
- Booking.com Demand API: Affiliate 파트너십 필요

### 4.4 Session → Rental Car payload (agents/session/executor.py 259행)
```python
lt_payload = {
    "pickup": travel.destination,
    "dropoff": travel.destination,
    "start_date": ...,   # 항공편 현지 도착일
    "end_date": ...,     # 항공편 현지 출발일
    "passengers": ...,   # 일행 수
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

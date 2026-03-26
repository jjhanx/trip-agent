# Travelpayouts API 연동 가이드

Travelpayouts에서 제공하는 항공·숙소·렌트카 등 여행 관련 API를 프로젝트에 연동하는 방법입니다.

---

## 1. 공통 설정

### 1.1 API 토큰 발급

1. [Travelpayouts](https://travelpayouts.com/) 가입
2. [API 토큰 페이지](https://www.travelpayouts.com/programs/100/tools/api)에서 토큰 확인
3. `.env`에 추가:
   ```
   TRAVELPAYOUTS_API_TOKEN=your_api_token_here
   TRAVELPAYOUTS_MARKER=your_affiliate_marker   # 제휴 링크용 (예: 509418)
   ```

### 1.2 인증 방법

모든 API 요청 시 아래 중 하나로 토큰 전달:

- **헤더**: `X-Access-Token: YOUR_TOKEN`
- **쿼리 파라미터**: `?token=YOUR_TOKEN`

### 1.3 Python 클라이언트 기본 예시

```python
import httpx

TOKEN = os.environ.get("TRAVELPAYOUTS_API_TOKEN", "")
HEADERS = {"X-Access-Token": TOKEN}

async def travelpayouts_get(url: str, params: dict | None = None):
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, headers=HEADERS, params=params or {})
        return resp.json() if resp.status_code == 200 else None
```

---

## 2. 항공편 API (Flight Data API)

**기본 URL**: `https://api.travelpayouts.com`

### 2.1 최저가 항공권 (경유 포함)

```
GET /v1/prices/cheap
```

| 파라미터 | 필수 | 설명 |
|----------|------|------|
| origin | O | 출발지 IATA (문서·캐시는 **도시 코드** 조합에 데이터가 더 자주 있음; 공항만 넣으면 `success: true`인데 `data: {}` 인 경우가 많음) |
| destination | O | 도착지 IATA |
| depart_date | - | 출발일 (yyyy-mm 또는 yyyy-mm-dd) |
| return_date | - | 귀환일 (편도 시 생략) |
| currency | RUB | 통화 (usd, eur, krw 등) |
| token | - | 토큰 (헤더 대신 사용 시) |

**예시**:
```python
url = "https://api.travelpayouts.com/v1/prices/cheap"
params = {"origin": "ICN", "destination": "KIX", "depart_date": "2025-06", "return_date": "2025-06", "currency": "usd"}
```

### 2.2 직항만

```
GET /v1/prices/direct
```

파라미터는 `/cheap`과 동일.

### 2.3 월별 캘린더 가격

```
GET /v1/prices/calendar
```

| 파라미터 | 설명 |
|----------|------|
| origin, destination | 출발/도착 공항 |
| depart_date | 출발 월 (yyyy-mm) |
| return_date | 귀환 월 (선택) |
| calendar_type | departure_date 또는 return_date |
| currency | 통화 |

### 2.4 기타 항공 API

| 엔드포인트 | 용도 |
|------------|------|
| `/v1/prices/monthly` | 월별 최저가 그룹 |
| `/v1/city-directions` | 특정 도시에서 인기 목적지 |
| `/v1/airline-directions` | 항공사별 인기 노선 |
| `/v2/prices/latest` | 최신 가격 (페이지네이션) |
| `/v2/prices/month-matrix` | 월별 가격 매트릭스 |
| `/v2/prices/week-matrix` | 주별 가격 매트릭스 (`show_to_affiliates=false` 등으로 캐시 범위가 달라질 수 있음) |

**이 저장소(Trip Agent)**: `/v1/prices/cheap`이 비어 있으면 도시 코드 재시도 → 필요 시 출발·귀환을 `yyyy-mm`으로 같은 엔드포인트 재요청 → 그다음 `/v2/prices/week-matrix` 보조 조회를 합니다. 제휴 검색 URL(Aviasales)은 사용자가 입력한 공항 코드를 유지합니다.

---

## 3. 실시간 항공편 검색 API

**접근**: [지원 요청](https://support.travelpayouts.com/hc/en-us/requests/new) 필요  
(프로젝트 설명, 검색 결과 화면 프로토타입 등 제출)

- **URL**: `POST https://api.travelpayouts.com/v1/flight_search`
- **제한**: IP당 시간당 200회
- **응답**: 실시간 가격 및 예약 링크

---

## 4. 숙소 API (Hotels Data API)

**기본 URL**: `http://engine.hotellook.com`  
동일한 Travelpayouts 토큰 사용.

### 4.1 호텔/지역 검색

```
GET http://engine.hotellook.com/api/v2/lookup.json
```

| 파라미터 | 설명 |
|----------|------|
| query | 도시명, 호텔명, 또는 위경도 (lat,lon) |
| lang | 언어 (en, ru, ko 등) |
| lookFor | both / city / hotel |
| limit | 결과 수 |
| token | API 토큰 |

**예시**:
```python
url = "http://engine.hotellook.com/api/v2/lookup.json"
params = {"query": "Seoul", "lang": "en", "lookFor": "both", "limit": 10, "token": TOKEN}
```

### 4.2 숙소 가격 조회

```
GET http://engine.hotellook.com/api/v2/cache.json
```

| 파라미터 | 설명 |
|----------|------|
| location | 지역명 (예: Saint-Petersburg) |
| hotelId | 호텔 ID (lookup 결과에서 획득) |
| checkIn, checkOut | 체크인/체크아웃 (yyyy-mm-dd) |
| currency | rub, usd, eur 등 |
| limit | 결과 수 |
| token | API 토큰 |

### 4.3 호텔 목록 (아카이브)

```
GET http://yasen.hotellook.com/tp/v1/hotels?language=en
```

토큰 없이 호출 가능. 주 1회 업데이트.

---

## 5. 정적 데이터 API (토큰 선택)

**기본 URL**: `https://api.travelpayouts.com/data`

| 엔드포인트 | 용도 |
|------------|------|
| `/data/en/countries.json` | 국가 목록 |
| `/data/en/cities.json` | 도시 목록 |
| `/data/en/airports.json` | 공항 목록 |
| `/data/en/airlines.json` | 항공사 목록 |
| `/data/planes.json` | 항공기 목록 |
| `/data/routes.json` | 노선 목록 |

**예시**:
```python
# 공항 데이터 (프로젝트 airports.js 보강용)
url = "https://api.travelpayouts.com/data/en/airports.json"
```

---

## 6. 렌트카·투어·기타 서비스

Travelpayouts는 **렌트카, 투어, 보험** 등은 Data API가 아니라 **제휴 프로그램(링크)** 형태로 제공합니다.

### 6.1 제휴 링크 사용

1. [Travelpayouts 대시보드](https://app.travelpayouts.com/) 로그인
2. **Tools** → **Link Generator** 또는 각 프로그램별 **Links** 메뉴
3. Aviasales(항공), Hotellook(숙소), 렌트카·투어 등 프로그램 선택 후 링크 생성
4. 생성된 URL에 `marker=YOUR_MARKER` 포함 → 클릭 시 제휴 수익 발생

### 6.2 항공편 예약 링크 (Aviasales)

검색 조건으로 직접 URL 생성 가능:

```
https://www.aviasales.com/search/{ORIGIN}/{DESTINATION}/{DEPART}/{RETURN}?marker={YOUR_MARKER}&currency=KRW&adults=1&children=0&infants=0&is_one_way=false
```

예: `https://www.aviasales.com/search/ICN/KIX/2025-06-15/2025-06-22?marker=509418&currency=usd`

### 6.3 렌트카·투어 등

공개 Data API는 없습니다. 대시보드에서 **프로그램별 링크 도구**를 사용해 검색/예약용 URL을 받아 프로젝트에 삽입합니다.

**EconomyBookings** 제휴 진입 URL이 `economybookings.tpk.ro/…` 형태이면, 서버가 **HEAD/GET(리다이렉트 1회)** 로 `www.economybookings.com?btag=…&tpo_uid=…` 에서 쿼리를 읽어, 앱이 만드는 **공항·일정 랜딩 URL**(`…/car-rental/…/공항?pickup_date…`)에 같은 파라미터를 **병합**합니다. 그래서 사용자가 «EconomyBookings 열기»·차급 카드 버튼을 눌러도 제휴 추적이 유지됩니다. 목록 **맨 아래**의 제휴 카드는 대시보드에서 받은 **숏링크 그대로** 둡니다.

---

## 7. 프로젝트 연동 (구현됨)

```
trip-agent/
├── mcp_servers/
│   ├── flight/
│   │   ├── travelpayouts_clients.py   # cheap / direct API + Aviasales URL
│   │   ├── api_clients.py             # SerpApi (1순위)
│   │   └── services.py                # SerpApi → Amadeus(429) → Travelpayouts 참고 → Mock
│   └── rental_car/
│       ├── travelpayouts_economybookings.py  # tpk.ro → btag/tpo_uid를 EB 일정 URL에 병합
│       └── services.py                # TRAVELPAYOUTS_RENTAL_BOOKING_URL 시 하단 제휴 카드 + EB 링크 병합
├── config.py                          # TRAVELPAYOUTS_* + SERPAPI_*
└── .env.example
```

### 7.1 환경 변수 (.env.example)

```env
TRAVELPAYOUTS_API_TOKEN=
TRAVELPAYOUTS_MARKER=
# 렌트카 제휴 URL (대시보드 Link Generator)
TRAVELPAYOUTS_RENTAL_BOOKING_URL=
```

### 7.2 동작 요약

1. **항공**: SerpApi·Amadeus에 결과가 없을 때 `TRAVELPAYOUTS_API_TOKEN`이 있으면 `/v1/prices/cheap`(직항 보강 `/v1/prices/direct`)로 캐시 참고. `TRAVELPAYOUTS_MARKER`로 카드에 Aviasales `booking_url` 생성.
2. **렌트카**: Data API 없음. `TRAVELPAYOUTS_RENTAL_BOOKING_URL`에 대시보드에서 받은 링크를 넣으면 검색 결과 **하단**에 제휴 카드가 붙습니다. 링크가 `economybookings.tpk.ro` 게이트웨이이면 EconomyBookings **비교·차급 카드**의 예약 URL에도 동일 추적 쿼리를 병합합니다.
3. **숙소(Hotellook)**: 본 문서 §4 참고 — 코드 연동은 별도 확장 시 진행.

---

## 8. 주의사항

| 항목 | 내용 |
|------|------|
| **응답 형태** | `data`는 `{ 목적지: { "0": 티켓, … } }` 외에 `{ 목적지: 티켓 }`(인덱스 없음), `data: [ … ]`(배열), `price` 대신 `value`, `departure_at` 대신 `depart_date` 등 변형이 있습니다. 클라이언트(`travelpayouts_clients._collect_fare_rows`)에서 모두 수집합니다. |
| **진단 메시지** | Travelpayouts 단계가 실행되면 `[Travelpayouts 진단]` 접두로 연결 성공(HTTP 200)·401/403·429·JSON 실패·캐시 0건 등을 구분합니다. (SerpApi·Amadeus가 먼저 시도됩니다.) |
| **Rate limit** | IP당 시간당 약 200 요청 (Data API) |
| **가격 통화** | 기본 RUB. `currency` 파라미터로 usd, eur 등 지정. KRW 지원 여부 확인 필요 |
| **캐시 데이터** | Flight Data API는 캐시 기반. 실시간 검색은 별도 지원 요청 필요 |
| **실시간 검색** | `flight_search` 사용 시 localhost IP 사용 불가, 전환율 요구사항 있음 |

---

## 9. 참고 링크

- [Travelpayouts API 문서](https://api.travelpayouts.com/documentation)
- [API 토큰 발급](https://www.travelpayouts.com/programs/100/tools/api)
- [실시간 검색 API 접근 요청](https://support.travelpayouts.com/hc/en-us/requests/new)
- [Help Center](https://support.travelpayouts.com/hc/en-us)

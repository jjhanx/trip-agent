# Trip Agent

여행 지역·기간·취향을 입력하면 **최저가 또는 마일리지** 항공편, **명소·동선·맛집을 단계적으로 짜는 여행 일정**, **숙소 5개**를 제시하고, 전체 일정 확정 후 **예약 안내**까지 해주는 멀티 에이전트 기반 여행 플래너입니다.

---

## 1. 질의응답 배경 (설계 근거)

### 1.1 요구사항 요약

- **입력**: 여행 지역, 기간, 시작 무렵, 여행 취향, 보유 마일리지, 선호 좌석 클래스, 현지 이동 방법, 선호 숙소 형태
- **출력 순서**:
  1. 최저가 또는 마일리지 활용 항공편 (가격순 정렬)
  2. 선택 항공 + 취향 기반 여행 일정(명소 후보 → 경로·추천 동네·맛집 → 식사 우선순위 → 확정 요약)
  3. 숙박 필요 구간별 숙소 5개 비교·선택
  4. 일정 확정 시 예약 안내

### 1.2 여행 정보 입력 설계 원칙

> 다음 5가지 원칙은 구상과 효용에 핵심이므로 구현에 반드시 반영됩니다.

**1. 출발지·목적지: 공항 코드 또는 도시/관광지**

- 출발지·목적지는 **공항 코드**(ICN, KIX 등)일 수도, **도시·관광지 이름**(오사카, 돌로미티 등)일 수 있음
- **국제선**(출발·목적 국가가 다름): 목적지 기준 **차량 8시간 이내** 공항 후보 중 **목적지와 같은 나라** 공항을 먼저 두고, 나머지는 **차량 거리** 순. 출발지 쪽도 동일한 지상 규칙으로 후보를 제시(`frontend/airports.js`).
- **국내선**(출발·목적 국가가 같음): **차량 3시간 이상** 거리의 공항을 우선(후보가 없으면 조건 완화). 이후 목록은 비행·마일리지 정보로 보조 정렬.
- **왕복 귀국편 검색**: 출국편에서 고른 항공사와 **동일 IATA 코드** 귀국편을 SerpApi에서 우선 필터·정렬(`preferred_return_airline_code`).

**2. 출발일·귀환일 및 날짜 유연성**

- “귀국일”이 아니라 **“귀환일”**로 표기 (국내 여행 등 포함)
- 계획 시점에는 정확한 날짜보다 **대략적 시기·기간**만 정할 수 있음
- **옵션**: 앞뒤 허용 구간을 두어 최저가 항공권 검색 등 지원
- 날짜 선택 시 **달력 UI** 제공

**3. 출발 시간 선호**

- 별도로 묻지 않음 (최종 후보 중 사용자가 선택)
- 다만, **도착지에 빨리 도착할수록 현지 선택 폭이 넓어지므로** 이 점을 반영해 일정 후보 제시

**4. 숙소 형태**

- 별장, B&B, 부엌 있는 호텔, 산장 등 **다양한 형태** 선택 가능
- 현지에 특정 형태가 없을 수 있으므로 **혼합 후보** 제시
- **선호 우선순위 3가지**를 정할 수 있는 UI 제공

**5. 단계별 흐름과 “다음” 버튼**

- 맨 위에 **여행 일정 설계 단계**를 보여주고 **현재 단계**를 표시
- “항공편 검색” 버튼이 항상 필요한 것은 아님
- 하단에 **“다음”** 버튼으로 다음 단계로 진행

### 1.3 Agent 구성 결정

각 기능을 **전담 Agent**로 분리하고, **A2A (Agent-to-Agent)** 프로토콜로 에이전트 간 협업을, **MCP (Model Context Protocol)**로 외부 API(항공·숙소 등)를 연동하도록 설계했습니다.

| 용도 | 프로토콜 | 이유 |
|------|----------|------|
| 외부 API/데이터 접근 | **MCP** | 항공·숙소 API를 Tools·Resources로 표준화 |
| Agent 간 협업·조율 | **A2A** | Agent 간 능력 공유, 작업 위임, 상태 관리 |
| UI 연동 | 둘 다 | MCP는 도구 제공, A2A는 백엔드 통신 |

### 1.4 현지 이동 방법별 Agent 분리

**렌트카**와 **대중교통**은 데이터 소스, 검색 방식, 고려 요소가 달라 **별도 Agent**로 분리했습니다.

| 구분 | 렌트카 | 대중교통 |
|------|--------|----------|
| 데이터 소스 | Rentalcars, Kayak 등 | Google Transit, Rome2Rio, 현지 교통권 API |
| 검색 방식 | 차종·일수·픽업·반납 | 노선·시간표·환승·교통권 |
| 고려 요소 | 주유, 주차, 반납장 | 환승, 패스, 현지 앱 |

사용자가 **현지 이동 방법**을 선택하면 Session Agent가:
- `rental_car` → **Rental Car Agent** 호출
- `public_transit` → **Public Transit Agent** 호출

---

## 2. 아키텍처 개요

```
┌──────────────────────────────────────────────────────────────────┐
│                    Web UI (PC/모바일 반응형)                       │
└────────────────────────────────┬─────────────────────────────────┘
                                 │
┌────────────────────────────────▼─────────────────────────────────┐
│              Session & Input Agent (오케스트레이터)                 │
│  · 입력 검증·정규화  · 하위 Agent 라우팅  · 결과 취합               │
└────────────────────────────────┬─────────────────────────────────┘
                                 │ A2A Protocol
         ┌───────────────────────┼───────────────────────┐
         ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌──────────────────┐
│ Flight Search   │    │ Itinerary       │    │ Accommodation     │
│ Agent           │    │ Planner Agent   │    │ Agent             │
└────────┬────────┘    └────────┬────────┘    └────────┬─────────┘
         │                      │                       │
         │  ┌──────────────────┴───────────┐           │
         │  ▼                               ▼           │
         │  ┌─────────────────┐  ┌──────────────────┐  │
         │  │ Rental Car      │  │ Public Transit    │  │
         │  │ Agent           │  │ Agent             │  │
         │  └─────────────────┘  └──────────────────┘  │
         │                      │                       │
         └──────────────────────┼──────────────────────┘
                                ▼
                    ┌──────────────────────┐
                    │  Booking Orchestrator│
                    │  Agent               │
                    └──────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│  MCP Servers: Flight | Hotel | Rental Car | Public Transit        │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. 구성 요소

| Agent | 역할 |
|-------|------|
| **Session & Input Agent** | 사용자 입력 검증, Flight → Itinerary → Accommodation → Rental/Transit → Booking 순차 호출 |
| **Flight Search Agent** | 항공편 검색, 가격순 또는 마일리지순 정렬 |
| **Itinerary Planner Agent** | 명소 후보(일수×3)·동선·숙소 동네·명소별 맛집·최종 일정 (다단계, LLM·mock). `GOOGLE_PLACES_API_KEY`가 있으면 맛집 단계에서 **Nearby+Place Details**로 실제 상호·평점·주소·웹·구글맵 URL을 채움(`shared/restaurant_places.py`). |
| **Accommodation Agent** | 숙박 구간별 숙소 5개 후보 제시 |
| **Rental Car Agent** | 현지 이동=렌트카 시 픽업/반납·가격·경로 제공 |
| **Public Transit Agent** | 현지 이동=대중교통 시 노선·패스·경로 제공 |
| **Booking Orchestrator Agent** | 일정 확정 후 예약 절차 안내 |

---

## 4. 구현 내용

### 4.1 프로젝트 구조

```
trip-agent/
├── agents/                    # A2A Agents
│   ├── session/               # Session & Input Agent (오케스트레이터)
│   ├── flight/                # Flight Search Agent
│   ├── itinerary/             # Itinerary Planner Agent
│   ├── accommodation/         # Accommodation Agent
│   ├── rental_car/            # Rental Car Agent
│   ├── public_transit/        # Public Transit Agent
│   └── booking/               # Booking Orchestrator Agent
├── mcp_servers/               # MCP Servers (Mock)
│   ├── flight/                # search_flights, get_mileage_balance
│   ├── hotel/                 # search_hotels, compare_hotels
│   ├── rental_car/            # search_rentals, get_drive_routes
│   └── transit/               # search_routes, get_transit_passes
├── api/                       # REST API (계획 서버 저장)
│   └── plans.py               # 사용자별 계획 CRUD (SQLite), 나중에 가입/로그인 연동 가능
├── data/                      # SQLite DB (plans.db, .gitignore)
├── shared/
│   ├── models/                # TravelInput, FlightResult, ItineraryOption 등
│   ├── attraction_scenic.py # 전망·케이블카류 명소 판별(전역, Places 검색·정렬·스키 필터와 공유)
│   └── utils/                 # MCPClient, A2AClient
├── frontend/                  # 반응형 Web UI
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── main.py                    # Session Agent + Frontend 통합 서버
├── config.py                  # 환경 변수 설정
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

### 4.2 기술 스택

| 영역 | 기술 |
|------|------|
| Backend | Python 3.10+, a2a-sdk, mcp |
| A2A | a2a-sdk[http-server], FastAPI/Starlette |
| MCP | mcp (modelcontextprotocol) FastMCP |
| Frontend | HTML, CSS, JavaScript (반응형) |
| LLM | OpenAI API, OpenRouter (Gemini 3.1 Pro 등, Itinerary Agent) |

### 4.3 주요 모델 (shared/models)

- **TravelInput**: destination, origin, start_date, end_date(귀환일), date_flexibility_days, origin_airport_code, destination_airport_code, local_transport, accommodation_type, accommodation_priority(최대 3순위), seat_class, use_miles, preference 등
- **LocalTransportType**: `rental_car`, `public_transit`
- **AccommodationType**: hotel, guesthouse, hostel, apartment, resort, villa, bnb, hotel_with_kitchen, mountain_lodge
- **SeatClass**: economy, premium_economy, business, first
- **FlightResult**, **ItineraryOption**, **AccommodationOption**, **RentalCarOption**, **TransitOption**

### 4.4 Fallback 동작

Session Agent는 하위 Agent(Flight, Itinerary 등)가 없을 때 **mock 서비스**로 직접 응답하여, 단일 프로세스만으로도 전체 플로우를 확인할 수 있습니다.

---

## 5. 실행 방법

### 5.1 단일 프로세스 (권장: 빠른 확인용)

```bash
pip install -r requirements.txt
python main.py
```

- http://localhost:9000 접속
- 다른 Agent 없이도 Session Agent가 mock 데이터로 응답

### 5.2 전체 에이전트 (Docker Compose)

```bash
docker compose up --build
```

- Session + Flight + Itinerary + Accommodation + Rental Car + Transit + Booking 7개 서비스 기동
- http://localhost:9000 에서 웹 UI 접속

### 5.3 개별 실행 (개발용)

```bash
# A2A 에이전트 (각각 별도 터미널)
python -m agents.flight.server &       # 9001
python -m agents.itinerary.server &    # 9002
python -m agents.accommodation.server & # 9003
python -m agents.rental_car.server &   # 9004
python -m agents.public_transit.server & # 9005
python -m agents.booking.server &      # 9006

# Session Agent + Frontend
python main.py                         # 9000
```

### 5.4 MCP 서버 (선택)

```bash
uv run --with mcp mcp_servers/flight/server.py   # 8001
uv run --with mcp mcp_servers/hotel/server.py    # 8002
# ...
```

---

## 6. 환경 변수

### 6.1 LLM 설정 (Itinerary Agent)

Itinerary Agent는 OpenAI 호환 API를 사용합니다. **OpenAI** 또는 **OpenRouter**를 통해 Gemini 3.1 Pro 등 다양한 모델을 사용할 수 있습니다.

| 변수 | 기본값 | 설명 |
|------|--------|------|
| OPENAI_API_KEY | | API 키 (OpenAI 또는 OpenRouter) |
| OPENAI_BASE_URL | (없음) | OpenAI 외 다른 엔드포인트 사용 시 (예: OpenRouter) |
| LLM_MODEL | gpt-4o-mini | 사용할 모델명 |

**Gemini 3.1 Pro (OpenRouter 경유)** 예시:

```env
OPENAI_API_KEY=sk-or-v1-xxxxxxxx   # OpenRouter API 키 (https://openrouter.ai)
OPENAI_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=google/gemini-3.1-pro-preview
```

OpenRouter에서 API 키를 발급받고 `.env`에 위와 같이 설정하면 됩니다. 다른 모델(`google/gemini-2.5-pro`, `google/gemini-2.0-flash` 등)도 [OpenRouter 모델 목록](https://openrouter.ai/docs/features/models)에서 선택 가능합니다.

### 6.2 Flight API (실제 항공편 검색)

| 변수 | 설명 |
|------|------|
| TRAVELPAYOUTS_API_TOKEN | [Travelpayouts](https://travelpayouts.com/) Data API 토큰. **SerpApi·Amadeus에 결과가 없을 때** 캐시 최저가·Aviasales 링크 **참고** ([발급](https://www.travelpayouts.com/programs/100/tools/api)) |
| TRAVELPAYOUTS_MARKER | Aviasales 예약 딥링크용 제휴 마커 (권장) |
| SERPAPI_API_KEY | [SerpApi](https://serpapi.com) — **항공 검색 1순위** (Google Flights). 일정 명소 **입장·주차**는 `GOOGLE_CSE_CX`가 없을 때 **Google 웹 검색**(SerpApi `engine=google`, 명소당 2회) 스니펫 → LLM `fees_other` |
| AMADEUS_CLIENT_ID | (선택) [Amadeus](https://developers.amadeus.com). SerpApi 한도 초과 시 fallback |
| AMADEUS_CLIENT_SECRET | (선택) Amadeus API Secret |

**순서**: SerpApi → Amadeus(429 시) → Travelpayouts(캐시 최저가 참고) → Mock. **대한항공·아시아나(KE/OZ)** 는 마일리지 계획을 위해 SerpApi·Amadeus 단계에서 전용 필터 검색으로 보강 병합합니다. 상세·렌트카 제휴 URL은 [FLIGHT_API_SETUP.md](FLIGHT_API_SETUP.md), [docs/TRAVELPAYOUTS_API_GUIDE.md](docs/TRAVELPAYOUTS_API_GUIDE.md) 참조.

**SerpApi**는 월 250회 무료. 한도 점검은 [FLIGHT_API_SETUP.md §5](FLIGHT_API_SETUP.md#5-serpapi-한도-초과-시-점검-방법) 참조.

### 6.2.1 렌트카 (SerpApi + 차급 스펙 + EconomyBookings, 제휴 선택)

| 변수 | 설명 |
|------|------|
| TRAVELPAYOUTS_RENTAL_BOOKING_URL | 대시보드에서 생성한 렌트카 제휴 URL. 목록 **하단**에 제휴 카드. `economybookings.tpk.ro/…` 이면 EB 공항·일정·차급 카드 링크에 **btag·tpo_uid** 병합(검색당 제휴 URL 1회 HEAD/GET) |
| AMADEUS_CLIENT_ID / AMADEUS_CLIENT_SECRET | **항공**용(SerpApi 429 시 fallback). 렌트 단계에서는 트랜스퍼를 호출하지 않음 |
| SERPAPI_API_KEY | 항공과 **동일 키**(권장). 렌트 단계에서 **Google 검색**으로 OTA·비교 사이트 후보와 스니펫 기반 **원화 추정가**를 카드에 표시. 키가 없으면 SerpApi 후보·스니펫 가격은 나오지 않음 |

**마일리지 선호 항공사 우선 표시**: 여행 정보에 마일리지 프로그램(Skypass, Asiana, Miles & More 등)을 입력하면, 해당 마일리지가 적립되는 항공사 편을 상단에 우선 노출하며 가능한 편은 모두 표시합니다 (스크롤 지원).

**API 키 발급 및 .env 설정** 상세 절차는 [FLIGHT_API_SETUP.md](FLIGHT_API_SETUP.md)를 참조하세요.

### 6.2.2 일정 명소 이미지 (위키·Commons·Google Places·선택 SerpApi)

| 변수 | 기본 | 설명 |
|------|------|------|
| GOOGLE_PLACES_API_KEY | | **명소 사진·Place Details·좌표** (Google Maps Platform). 동일 키로 **Directions API**(거점→명소 주행 분)·**Geocoding API**(목적지·거점 좌표)·**맛집 단계 Nearby Search**(명소 주변 식당)를 씁니다. Cloud Console에서 **Places API, Directions API, Geocoding API**가 사용(Enabled)되어 있어야 `parking`의 **○분**이 API로 채워집니다. 월 $200 무료 크레딧 범위 참고. ([발급 가이드](docs/GOOGLE_PLACES_API_GUIDE.md)) |
| GOOGLE_CSE_CX | | (선택) [Programmable Search Engine](https://programmablesearchengine.google.com/) **검색 엔진 ID(cx)**. 설정 시 입장·주차 요금은 **Google 웹 검색**(Custom Search JSON API) 스니펫만 사용(SerpApi보다 우선). Cloud에서 **Custom Search API**를 켜고 키는 `GOOGLE_PLACES_API_KEY`와 동일해도 됨. ([가이드](docs/GOOGLE_PLACES_API_GUIDE.md) §7) |
| PLACE_IMAGES_USE_SERPAPI | false | `true`이면 영문·이탈 위키·Wikimedia Commons로 찾지 못할 때 **SerpApi Google 이미지** 검색(`SERPAPI_API_KEY` 필요). API 한도 소모·원 게시자 저작권 유의. [docs/IMAGES_AND_LICENSES.md](docs/IMAGES_AND_LICENSES.md) |

위키·Commons는 검색 후보 중 **문서·파일 제목이 명소명과 맞는 경우만** 쓰고, 한 일정의 명소 목록에서는 **같은 이미지 URL을 두 카드에 쓰지 않습니다**. 확실한 매칭이 없으면 **사진을 비우고** 안내 문구만 표시합니다(Unsplash 일반 풍경으로 채우지 않음).

### 6.3 A2A Agent / MCP

| 변수 | 기본값 | 설명 |
|------|--------|------|
| FLIGHT_AGENT_URL | http://localhost:9001 | Flight Agent A2A URL |
| ITINERARY_AGENT_URL | http://localhost:9002 | Itinerary Agent URL |
| ACCOMMODATION_AGENT_URL | http://localhost:9003 | Accommodation Agent URL |
| RENTAL_CAR_AGENT_URL | http://localhost:9004 | Rental Car Agent URL |
| TRANSIT_AGENT_URL | http://localhost:9005 | Public Transit Agent URL |
| BOOKING_AGENT_URL | http://localhost:9006 | Booking Agent URL |
| A2A_TIMEOUT_SECONDS | 120 | Session → Flight·숙소 등 A2A 호출 HTTP 타임아웃(초) |
| A2A_ITINERARY_TIMEOUT_SECONDS | 900 | Session → **Itinerary** A2A 타임아웃(초). 명소·LLM·이미지 보강이 길면 늘림. **Nginx·로드밸런서** `proxy_read_timeout`(또는 idle timeout)도 이 값 이상 권장(HTTP 504 완화). |
| FLIGHT_MCP_URL | http://localhost:8001/mcp | Flight MCP Server URL |
| HOTEL_MCP_URL | http://localhost:8002/mcp | Hotel MCP Server URL |
| RENTAL_CAR_MCP_URL | http://localhost:8003/mcp | Rental Car MCP Server URL |
| TRANSIT_MCP_URL | http://localhost:8004/mcp | Transit MCP Server URL |

---

## 7. 사용 흐름

명소 수집·거점·요금·이미지 파이프라인(구글 중심, 지역 큐레이션의 역할)은 [docs/ATTRACTION_PIPELINE.md](docs/ATTRACTION_PIPELINE.md)를 참고하세요.

1. **여행 정보 입력**: 출발지·목적지(공항 코드 또는 도시), 출발일·귀환일(달력 버튼으로 날짜 선택), 일행 구성(남·여·아동), 날짜 유연성(±일), 숙소 선호 3순위, 현지 이동, 좌석 클래스, 마일리지·마일리지 프로그램 등. 도시 입력 시 국제선/국내선 규칙에 따른 공항 선택 단계가 추가됨. 같은 화면에서 **항공편 검색·선택** 또는 **항공편 건너뛰기**(다구간 제외)를 고름
2. **항공편 선택**(건너뛰지 않은 경우): **왕복** 시 2a 출국편 → 2b 귀국편 (편도 검색). **편도** 시 1회 선택. **다구간** 시 구간별 순차 선택. 추천순·가격순·비행시간순 정렬. **선택이 끝나면(왕복·편도·마지막 구간)** 또는 **다음**을 누르면, API 호출 전에 **렌트·대중교통 검색 vs 건너뛰기**를 고르는 화면으로 이동
3. **렌트카/대중교통**: 검색을 고르면 세션이 항공(또는 항공 없음)에 맞춰 렌트·교통 후보를 요청. 렌트카 선택 시 **픽업·반납 일시·공항(IATA)** 입력란에 항공 일정이 채워지며 수정 후 **이 일정으로 다시 검색** 가능. `SERPAPI_API_KEY`가 있으면 **Google 검색**으로 셀프 드라이브 **후보·추정 가격 힌트**를 붙이고, **차급별 스펙 참고 카드**와 EconomyBookings 비교 링크가 이어집니다. 대중교통은 Transit MCP. 렌트 결과 화면에서 **다음**을 누르면 API 호출 전에 **여행 일정 설계 vs 건너뛰기**를 고름
4. **여행 일정**: 후보 명소 선택 → **경로·맛집 계획 받기** → 날짜별 점심·저녁 1·2순위 선택 → **일정 확정** → **다음**을 누르면 API 호출 전에 **숙소 후보 검색 vs 건너뛰기**를 고름
5. **숙소 선택**: 5개 혼합 후보 중 선택 (현지 이동 정보 포함)
6. **일정 확정** → 예약 절차 안내

- 상단 **단계 표시**를 클릭하면 해당 단계로 이동하여 확정된 내용을 확인·수정할 수 있음

**계획 저장·불러오기**: 여행 계획은 단계별로 시간이 걸리므로, 진행 상황을 저장하고 나중에 다시 불러올 수 있습니다. **파일 내보내기 / 불러오기(추천)** 를 이용하면 구글 드라이브나 메신저를 통해 `.json` 파일 하나로 집과 사무실 어디서든 즉각적으로 이어서 계획을 편집할 수 있습니다. 로컬 장비에 설치된 **서버 저장**을 활용할 수도 있습니다(저장 시 발급되는 '연결 코드'를 다른 기기에서 입력).

---

## 8. 주요 변경 사항 (Changelog)

> 주요 변경 시 이 섹션을 업데이트합니다.

| 날짜 | 변경 내용 |
|------|-----------|
| 2026-04-15 | **구글맵 식당 링크(한국 기본 지역 문제)**: `query_place_id`만 쓰면 로케일이 서울로 잡히는 경우가 있어, `query`(식당명·목적지)와 `query_place_id`를 함께 전달(`googleMapsSearchUrlWithPlaceId`). 맛집 카드·확정 일정 표 공통. `app.js?v=35`. |
| 2026-04-15 | **명소 변경 시 맛집 선택 유지**: 새 `route_restaurants` 응답 후 `mergePreservedMealChoices`로 날짜별 후보(당일 오전·오후·추가 명소 풀)에 남아 있는 Place id만 점심·저녁 선택을 복원. 명소 단계로 돌아갈 때 `mealChoices`를 비우지 않음. `app.js?v=34`. |
| 2026-04-15 | **명소 변경 후 일정 재생성**: `lastCommittedAttractionIds`로 확정 일정과 선택 명소가 일치할 때만 「여행 일정으로」바로가기. 불일치 시 확정 일정·동선·맛집 초기화 후 「경로·맛집 계획 받기」. 명소 단계에서 5단계로 잘못 열리던 `goToItinerarySectionForState` 수정. 4단계+확정 상태에서 뒤로는 렌트로. `app.js?v=33`. |
| 2026-04-15 | **확정 일정 표**: 명소·식당 이름에 **구글맵 링크**(명소: `google_maps_url` / `place_id` / 검색, 식당: `query_place_id`·이름+목적지). `app.js?v=32`, `styles.css?v=12`. |
| 2026-04-15 | **여행 일정 확정(complete)**: 일자별 요약을 JSON `<pre>` 대신 **표**(날짜·오전/오후/추가 명소·동선 메모·점심·저녁)로 표시. 명소 id는 카탈로그로 이름 해석. `app.js?v=31`, `styles.css?v=11`. |
| 2026-04-15 | **맛집 선택 UI**: 1·2순위 행을 세로로 고정하고 행마다 CSS Grid(`레이블 | select`)·인라인 스타일로 캐시/줄바꿈과 무관하게 `2순위`가 첫 번째 드롭다운 뒤로 붙지 않게 함. `app.js?v=30`, `styles.css?v=10`. |
| 2026-04-15 | **맛집: 오전·오후 명소→식당 승용차 분**: `daily_schedule`의 오전·오후 명소와 식당 좌표로 Directions를 호출해 각 식당에 `drive_from_slots_by_date`(날짜별 분·명소 이름)를 붙임. UI는 점심·저녁 후보 카드를 나누고 소개 앞에 각각 안내. `shared/restaurant_places.py` `enrich_restaurant_drives_from_daily_schedule`, `agents/itinerary/executor.py`, `app.js?v=28`, `styles.css?v=8`. |
| 2026-04-15 | **맛집 실데이터(Places API)**: `route_restaurants` 단계에서 `GOOGLE_PLACES_API_KEY`가 있으면 명소 좌표 주변 **Nearby Search** 후 각 후보 **Place Details**로 상호·평점·리뷰 수·소개(에디토리얼·리뷰·주소·가격대)·`website`·구글맵 `url`을 채워 가짜 「근처 맛집 A/B/C」를 대체. `shared/restaurant_places.py`, `agents/itinerary/executor.py`. |
| 2026-04-15 | **맛집 선택 UI(경로·맛집 단계)**: 드롭다운 `title`로 소개 미리보기, 날짜별 **맛집 후보 상세** 카드에 상호·평점·리뷰 수·소개·웹사이트·지도 링크. 선택한 후보는 카드 강조. 목업 `user_ratings_total`·`google_maps_url`, LLM 프롬프트에 식당 상세·URL 필드 요구. `app.js?v=27`, `styles.css?v=7`, `agents/itinerary/executor.py`. |
| 2026-04-15 | **저장·불러온 일정: 명소(4) ↔ 여행 일정(5) 단계 전환**: 상단 단계 클릭 시 완성 일정(`complete`)이어도 동선·맛집 번들을 지우지 않고, 명소 화면 렌더 시 워크플로를 `attractions`로 덮어쓰지 않음. 확정 `selectedItinerary`가 있으면 일정 단계에서 항상 복원 표시(`selectedItineraryLooksFinal`, `refreshStepView`, `goToItinerarySectionForState`). `frontend/app.js` `app.js?v=23`. |
| 2026-04-15 | **명소→여행 일정 단계 클릭 복구**: `navigateToStep('itinerary')`가 일정 본문이 비어 보일 때마다 4단계로 되돌리던 조건을 완화(`meals`/`complete`/`legacy` 진행 중이면 5단계 허용). 명소 목록 렌더 시 확정 일정 객체가 있으면 `itineraryWorkflowStep`을 `complete`로 맞춤. `daily_plan`·`route_plan` 등 저장 형태별 `selectedItineraryLooksFinal` 보강. `app.js?v=24`. |
| 2026-04-15 | **명소 화면 하단 버튼(여행 일정 복귀)**: 4단계에서 확정 일정이 있을 때 `경로·맛집 계획 받기`가 선택 id 없으면 비활성이던 문제를, 확정 일정이 있으면 **「여행 일정으로」**로 라벨·활성화. `complete` 상태로 명소만 볼 때도 **「다음 (숙소 선택)」** 대신 동일 동작. 클릭 시 `navigateToStep('itinerary')`. `isAttractionsSectionVisible`. `app.js?v=25`. |
| 2026-04-15 | **상단 단계 5 클릭**: `navigateToStep('itinerary')`에서 일정 본문이 비어 보일 때 4단계로 되돌리던 분기를 제거해, **5. 여행 일정**을 누르면 항상 일정 섹션으로 이동. 단계 표에 `z-index`로 다른 레이어에 가려 클릭이 안 되는 경우 완화. `app.js?v=26`, `styles.css?v=6`. |
| 2026-04-14 | **경로·맛집 단계: 선택 명소 부족 시 평점 순 자동 보강**: 사용자가 고른 명소만으로 **일수×2**(오전·오후) 슬롯을 채우기에 모자라면, 카탈로그에서 **선택하지 않은 후보**를 **평점·리뷰 수** 순으로 추가해 mock·LLM·Directions 파이프라인에 넘김. `route_plan.auto_filled_attraction_ids`·`lodging_strategy` 안내(`expand_selected_attractions_for_trip_days`, `agents/itinerary/executor.py` `route_restaurants`). |
| 2026-04-14 | **진행 단계 8분할: 명소 선택(4) ↔ 여행 일정(5)**: 상단 단계 표를 여행 정보→…→**명소 선택**→**여행 일정**→숙소→일정 확정→예약 안내로 분리. `#itinerary-step-panel`(명소 카드·버튼)을 `step-attractions` / `step-itinerary-plan` 마운트 간 이동. 5단계에서 **뒤로 (명소 선택)** 또는 단계 표 **4**로 동선·맛집 초안을 지우고 명소만 다시 고를 수 있음. `navigateToStep`·`goToItinerarySectionForState`·`getFullPlanState`/파일 내보내기에 동일 상태 유지. `frontend/index.html`, `app.js?v=22`. |
| 2026-04-14 | **여행 일정 단계: 명소 선택 ↔ 경로·맛집 상태 유지**: `localStorage` 초안(`trip-agent-itinerary-draft`)에 명소 카탈로그·선택 id·동선 번들·맛집 선택·워크플로 단계를 두고, 출발·목적·기간·공항·스킵 플래그가 같을 때만 복구. 명소 API 재호출 시 **place_id·이름**으로 선택 id 재매칭(`reconcileAttractionIdsAfterCatalogUpdate`). 일정 API 오류 시 전용 오류 섹션 대신 **일정 화면으로 복귀**해 선택이 유지되도록 `showAgentError`. 새 계획 확인에 일정 진행도 포함. `frontend/index.html` 안내 문구, `app.js?v=21`. |
| 2026-04-14 | **일정 2단계: 구글맵 동선·체류 반영**: 명소 선택 후 **경로·맛집** 단계에서 `GOOGLE_PLACES_API_KEY`(Directions·지오코딩)가 있으면 **도착 공항(또는 목적지 공항 코드)** 을 출발점으로 Nearest-Neighbor 방문 순을 잡고, **승용차 이동 분**·명소당 **추정 체류 분**(취향 `pace`·실무 필드 힌트)으로 일자별 `daily_schedule`을 서버가 다시 채움(`shared/itinerary_route_schedule.py`). 첫날 항공 도착이 **정오 이후**이면 오전 슬롯을 비우는 등 보조 로직. 선택 명소가 **하루 2곳**을 넘으면 마지막 날 `extra_attraction_ids`로 이어붙임. UI는 동선 요약·맛집 후보에 추가 명소 id 반영(`frontend/app.js` `app.js?v=20`). |
| 2026-04-02 | **명소 게이트웨이·루프(전 목적지)**: 목적지 중심 **공항 후보**(Places Nearby, 실패 시 Text Search) 중 출발지와 **대원거리 최단**을 게이트웨이로 두고, Directions로 **게이트웨이 → 입력 목적지들(최대 23) → 게이트웨이** 루프 샘플 주변에만 Places 검색·**약 110km**·평점·리뷰 수 정렬. **Grand Circle**은 서부 허브(LAX/LAS/PHX/SLC) + 고정 국립공원 루프 유지. 실패 시 기존 앵커·1000km(파타고니아 2400km) 폴백. `shared/route_corridor_places.py`(기존 `grand_circle_places.py` 통합). [docs/ATTRACTION_PIPELINE.md](docs/ATTRACTION_PIPELINE.md). |
| 2026-04-02 | **명소 파이프라인 일반화**: Places 후보를 **목적지·경로 샘플·(지역 렌트 구간) 출발지** 앵커까지의 **최단 거리**로 거르는 규칙(`shared/attraction_geo.py`, 기본 1000km / 파타고니아 2400km). 단일 앵커·과도한 km 한도로 생기던 오탐(예: 다른 대륙·도심 전망대)을 완화. 광역 목적지는 **추가 지오코드 시드·큐레이션**으로 검색 커버만 보강. **거점·주행분**을 `nearest_hub_display_name`·`drive_minutes_from_nearest_hub`로 노출·명소 카드 표시. [docs/ATTRACTION_PIPELINE.md](docs/ATTRACTION_PIPELINE.md). `frontend/app.js?v=19`. |
| 2026-04-02 | **UI: 단계별 진행 vs 건너뛰기(결정 화면)**: 여행 정보 폼에서 **항공편 검색·선택** / **항공편 건너뛰기**를 같은 화면에서 선택. 항공 선택 완료·항공 건너뛰기 후에는 **렌트·대중교통 검색 vs 건너뛰기**(`step-rental-decide`). 렌트 결과 후 **여행 일정 설계 vs 건너뛰기**(`step-itinerary-decide`). 일정 완료 후 **숙소 검색 vs 건너뛰기**(`step-accommodation-decide`). 세션은 `flight_skipped`·`rental_skipped` 유지(`agents/session/executor.py`). `frontend/app.js?v=18`. |
| 2026-04-02 | **일정: 국립공원·유명 명소**: 구글 Places 수집에 `national_park`·`national park` 키워드를 넣고 정렬에 `national_park` 유형을 자연 명소와 동일 우선(`attraction_scenic.py`). 일반 목적지 텍스트 검색에 national/state park·landmark 쿼리 추가. LLM 명소 프롬프트에 **동선 인근 국립공원 우선**·**design_notes에 대표 유명 명소 3곳 이상** 명시를 안내(`agents/itinerary/executor.py`). |
| 2026-04-02 | **Travelpayouts 400 (GRA not flightable)**: 목적지 문자열이 `Grand Circle` 등 **지역 묶음**일 때 `[:3]`로 잘리면 `GRA`처럼 잘못된 IATA가 됩니다. `travelpayouts_clients.py`에서 알려진 지역(Grand Circle→LAS, Patagonia→FTE 등)을 **게이트웨이 공항**으로 매핑하고, 공백이 있는 미해석 구문은 잘못된 3글자 추출을 막습니다. Aviasales 딥링크도 동일 규칙을 사용합니다. |
| 2026-04-02 | **Grand Circle 등 지역 묶음**: 목적지가 여러 국립공원 집합(예: Grand Circle / 그랜드 서클)일 때 **도착 공항 후보를 출발 공항과의 대원거리 순**으로 정렬(`airports.js` `AIRPORT_COORDS`, `getDestAirportsForOrigin`). 일정은 라스베이거스·스프링데일·페이지 등 **다중 지오코드 앵커**·전용 텍스트 검색·오프라인 큐레이션(`agents/itinerary/executor.py`). UI 안내 `app.js?v=16`, `airports.js?v=8`. |
| 2026-04-02 | **파타고니아 명소 오탐·부족**: 대륙 간 렌트 동선 경유지 Nearby로 팔공산·옐로스톤·유럽 케이블카 등이 섞이던 문제를 **출발~목적 거리 1200km 초과 시 경유 검색 생략**으로 차단. 지오코딩을 엘 칼라파테 등 남미 앵커로 고정, **나탈레스 2차 앵커**, Places 결과 **주소·거리(2400km) 필터**, 유럽형 텍스트 쿼리(funivia 등) 분기. **파타고니아 오프라인 큐레이션 풀**로 병합·보충 시 본문 없는 카드 최소화(`agents/itinerary/executor.py`). |
| 2026-04-02 | **HTTP 504**: 일정 A2A·Nginx 예시 타임아웃 기본을 **600초→900초**로 올림(`A2A_ITINERARY_TIMEOUT_SECONDS`, `proxy_read_timeout`/`proxy_send_timeout`). 프록시·ALB·Cloudflare(무료 100초 한도)는 [DEPLOYMENT.md](DEPLOYMENT.md) §504 점검. |
| 2026-04-02 | **목적지 파타고니아인데 MXP**: 이전 여행에서 남은 **목적지와 맞지 않는** 공항 코드만 제거하고, **목적지와 일치하는 저장값**(예: FTE)은 유지. 등록 도시인데 공항이 비어 있으면 `getDestAirportsForOrigin` 정렬의 **첫 공항을 기본값**으로 설정(`applyDefaultDestinationAirportIfMissing`). 파타고니아 후보의 `drive_hours`를 조정해 허브(EZE·SCL)가 ‘가까움’ 정렬에서 엘 칼라파테 등보다 앞서지 않게 함. 초기 로드·계획 불러오기·목적지 `blur`. `airports.js?v=7`, `app.js?v=15`. |
| 2026-04-02 | **마지막 8~9개가 계속 일반 보충**: `_dedupe_attractions_by_canonical_name`을 **fill 이전**에 적용해 풀이 69→61처럼 줄어든 뒤, `_fill_attraction_catalog_to_count`의 **pool이 이미 줄어든 리스트**라 구글 여분을 못 씀. **place_id만 dedupe한 `attraction_fill_pool`** + Places 수집 **max_count를 n_attr보다 크게** 해 보충·postprocess fill에 동일 소스 전달(`agents/itinerary/executor.py`). |
| 2026-04-02 | **명소 69개 중 끝 9개 미달(근본 원인)**: `max_count`를 동선·목적지에 **약 1:5 고정 분배**해, 동선 풀(`pool_route`)이 목표 슬롯(예: 13)보다 짧으면 **13+56=69를 절대 채울 수 없음**(실제 5+56=61 등). 검색 결과를 **한 풀**로 합쳐 정렬 후 `max_count`개만 자르도록 수정(`_fetch_top_attractions_from_google`). |
| 2026-04-02 | **Places 케이블카 후보 부족**: Nearby는 요청당 **최대 20건**이고 `type`+`keyword`만 쓰면 리프트역이 다른 primary type으로 빠지는 경우가 많음 → **`type` 없이 keyword만** 하는 Nearby(`funivia`, `seilbahn`, `ski lift` 등) 추가, keyword-only·리프트류 텍스트 검색은 **`next_page_token`으로 2페이지**까지 병합(`_fetch_top_attractions_from_google`). |
| 2026-04-02 | **전역: 전망·케이블카 우선 수집**: 돌로미티 전용이 아니라 **모든 목적지**에서 Nearby·텍스트 검색 키워드를 전망·케이블카·룩아웃·aerial tram 등 **공통 영어**로 앞쪽에 두고, 정렬에 `scenic_rank_bias`를 넣어 동일 평점 티어에서 **자연 지형·전망·리프트 이름**이 앞서게 함(`shared/attraction_scenic.py`, `_fetch_top_attractions_from_google`, `_place_itinerary_rank_key`). 여름 스키 필터 예외는 `name_suggests_viewpoint_cable_or_lift`로 통일. |
| 2026-04-02 | **돌로미티 큐레이션(케이블카 등)이 끝에 안 들어가던 이유**: 구글 후보가 이미 목표 개수를 채우면 큐레이션으로 **최악 구글만 교체**하는데, 교체 상한이 **8곳**이라 Tofana·Marmolada 등이 더 필요해도 막혔음 → 상한을 **약 n/3(최대 48)** 로 완화(`_merge_google_with_region_templates`). 여름 스키 필터가 `ski_resort`만 보고 케이블카역을 빼던 경우를 **이름 키워드**(Funivia, Marmolada, Tofana, Sassolungo 등)로 예외 처리(`shared/attraction_filters.py`). |
| 2026-04-02 | **명소 69개 중 끝부분이 일반 보충 템플릿**: Places 수집 시 리뷰 수가 적으면 **아예 풀에서 제외(99)** 되어 구글 후보가 짧아지던 문제를, **4.3 미만도 평점순 티어(5)** 로 포함하도록 수정(`_place_itinerary_rank_key`, `agents/itinerary/executor.py`). |
| 2026-04-02 | **HTTP 504(게이트웨이 타임아웃) 완화**: Session → Itinerary A2A 기본 타임아웃을 **60초→600초**로 분리(`A2A_ITINERARY_TIMEOUT_SECONDS`, `A2A_TIMEOUT_SECONDS`). Nginx 예시 `proxy_read_timeout`을 **600s**로 맞춤([DEPLOYMENT.md](DEPLOYMENT.md)). |
| 2026-04-02 | **명소 후보 일수×3 강제**: `postprocess`에서 이미지·중복 제거 후 보강이 `merged_pre_llm`이 있을 때만 실행되던 조건을 제거하고, **최종 반환 직전**에도 부족하면 일반 템플릿으로 채움. 구글 병합 직후 **dedupe**로 줄어든 경우에도 `_fill_attraction_catalog_to_count`로 다시 **일수×3**까지 맞춤(`agents/itinerary/executor.py`, `app.js?v=12`). |
| 2026-04-02 | **일정 일수 = 선택 항공 기준**: 세션에서 일정 에이전트로 넘기던 `start_date`/`end_date`가 **폼(초기 6/25 등)** 만 쓰여, 실제 편(6/23 도착 등)과 어긋나 **21일**·명소 **40개**로 보이던 문제를 수정. `_extract_rental_dates_from_flight`로 구한 날짜를 **itinerary 페이로드·mock 폴백**에 사용(`agents/session/executor.py`). 항공 확정 직후 `applyFlightDatesToTravelForm()`으로 폼 날짜도 동기화(`frontend/app.js`, `app.js?v=11`). |
| 2026-04-02 | **일정 API 날짜 동기화**: `state.travelInput`가 항공 확정 시점에만 갱신되어, 이후 폼에서 귀환일을 바꿔도 **옛 `start_date`/`end_date`**가 세션·일정으로 전달되던 문제 수정. `syncTravelInputFromForm()`으로 렌트 다음·일정·숙소 단계 **API 호출 직전**에 폼과 동기화(`frontend/app.js`, `app.js?v=10`). **구글 후보가 짧을 때** 큐레이션 풀만으로 `일수×3` 미달 가능하던 경우를 `_merge_google_with_region_templates` 끝에서 **일반 템플릿으로 보충**(`agents/itinerary/executor.py`). |
| 2026-04-02 | **일정 명소 후보**: 여행 **포함 일수**는 서버 `YYYY-MM-DD` 기준 `(종료−시작)+1` 유지. 프론트는 `new Date` 대신 **로컬 달력** `inclusiveCalendarDays`로 표시해 날짜-only 입력 시 일수 오차를 줄임. **후보 명소는 일수×3개를 목표로 채움**(상한 200). 구글 Places는 **4.3★·품질 통과** 우선, 부족 시 **낮은 평점(높은 순)**으로 보강. LLM 청크는 **정확히** 목표 개수 출력하도록 지시. `postprocess`에서 중복 제거 후에도 개수가 줄면 `merged_pre_llm`으로 다시 채움(`agents/itinerary/executor.py`, `agents/session/executor.py`, `frontend/app.js`, `frontend/index.html` `app.js?v=9`). |
| 2026-04-02 | **명소 Commons 이미지**: 고정 URL·Special:FilePath 대신 **Commons `list=search` + 파일 제목 점수 + `imageinfo.thumburl`** 만 사용(경로 만료·429·엉뚱한 첫 결과 완화). 랜드마크별 **보강 검색어**(`build_commons_extra_search_queries`). 지도·로고류 파일명 제외. 프론트 정적 URL 보강 제거(`frontend/app.js`, `app.js?v=8`). |
| 2026-04-02 | **Val di Funes·Cadini 사진 미표시**: Wikimedia `upload…/thumb/…` 직접 URL이 **429**(썸네일 정책)·구 해시 **404**로 브라우저에서 깨짐 → **`commons.wikimedia.org/wiki/Special:FilePath/…?width=800`** 로 교체(서버 폴백·mock·프론트 동일). `shared/place_images.py`, `agents/itinerary/executor.py`, `frontend/app.js`, `app.js?v=7`. |
| 2026-04-02 | **명소 사진(클라이언트 폴백)**: Val di Funes·Cadini di Misurina 등 알려진 Commons URL을 **`image_url`이 비어 있을 때** 브라우저에서도 보강(`applyKnownAttractionImageFallbacks`). 명소 단계 렌더 시마다 `sanitizeAttractionCatalogInPlace` 호출로 저장 JSON·단계 복귀 시에도 적용. `app.js?v=6` (`frontend/app.js`, `frontend/index.html`). |
| 2026-04-02 | **명소 정적 사진 우선**: `_wikimedia_commons_fallback`(Val di Funes·Cadini 등)을 **Place Details·resolve**보다 **먼저** 적용해, 이름은 맞는데 `place_id`·`used_keys` 때문에 Commons가 스킵되던 경우를 줄임. 목록 번호(`3.` 등) 제거 정규화, Val di Funes는 **푸네스+전망/드라이브** 조합도 인정 (`shared/place_images.py`). |
| 2026-04-02 | **명소 사진 누락(Val di Funes·Cadini 등)**: 동일 명소 병합 시 **설명만 긴 카드가 이기며 대표 사진이 사라지던** 문제를 `score`에 **`https` 이미지 우선**을 넣어 수정. 이름만 갱신할 때 **현재 카드에 사진이 없고 다른 후보에만 있으면** `image_url`·크레딧·출처를 복사. `enrich` **최종 단계**에서도 여전히 `https`가 없으면 **Wikimedia Commons 정적 폴백**을 한 번 더 시도(`image_source`에 `_final`). Commons 키워드 매칭에 **NFKC·공백 정리**, Cadini·Val di Funes·전망 포인트 표기 **느슨한 매칭** 보강 (`shared/place_images.py`, `agents/itinerary/executor.py`, `docs/IMAGES_AND_LICENSES.md`). |
| 2026-04-02 | **명소 이미지 추가 검색**: 1차(Wikipedia·Commons·Places·SerpApi) 후에도 `https`가 없으면 **SerpApi(완화 필터)·Places·Commons(파일 제목 관련성 생략)** 로 한 번 더 검색(`_extra_search_image_when_missing`). 동일 URL이 앞 카드와 겹쳐도 **빈 카드보다는 표시**하도록 중복 시에도 URL 유지. `fetch_commons_unique_thumbnail(require_file_relevance=…)`, `fetch_serpapi_google_image_unique(skip_region_filter=…)` (`shared/place_images.py`, `docs/IMAGES_AND_LICENSES.md`). |
| 2026-04-02 | **Google Place Photo 보강**: Text Search 응답에 `photos`가 없어도 **Place Details(photos)** 후 **Place Photo URL**로 받도록 `fetch_google_places_unique` 보강(별도 Photos API가 아니라 Places 패밀리). 검색어는 **`_clean_name_for_places_search`** 로 한글 부제·전망 문구 제거(`shared/place_images.py`, `docs/IMAGES_AND_LICENSES.md`). |
| 2026-04-02 | **명소 대표 사진(Cadini 등)**: 한글·괄호가 붙은 명소명이 토큰 수를 늘려 Google/Commons **제목 관련성** 검사가 과하게 엄격해지던 문제를 **`_tokens_attraction_match`(라틴 지명 토큰 우선)** 로 완화(`shared/place_images.py`). 알려진 Wikimedia 정적 폴백(예: Cadini di Misurina)을 **검색·Places 실패 시보다 먼저** 시도하고, 한글 표기 **카디니+미수리나** 폴백 규칙 추가. |
| 2026-04-02 | **명소 후보 개수**: `일수×3`이 **45로 잘리던** 상한을 **90**(`MAX_ITINERARY_ATTRACTION_CANDIDATES`)으로 올려 21일(63곳) 등이 반영되도록 함. `postprocess`에서 **https 대표 사진이 없다고 명소를 삭제**하던 동작을 없애고, **이미지 있는 카드만 앞으로 정렬**하되 개수는 유지(이미지 없음은 UI 플레이스홀더). Mock·Places `max_count` 기본값도 상한에 맞춤(`agents/itinerary/executor.py`). |
| 2026-04-02 | **명소 검색 일반화(지역 비특화)**: 모든 목적지에 동일하게 Nearby·Text Search에 `cable car`·`funicular`·`gondola`·전망·호수·트레일 등 **일반** 키워드 적용. **품질 필터**는 지역 한정 없이 자연·`tourist_attraction`·`point_of_interest`에 리뷰 수 완화. 구글 후보는 **평점·리뷰 점수**로 정렬·상한 채움; **지역 큐레이션 풀**(현재 돌로미티 등)이 있을 때만 상한만 채워진 경우 **낮은 점수 구글 후보**를 풀의 대표 랜드마크와 **교체**(돌로미티 전용 검색어·우선 시드 제거). **따뜻한 계절 스키 제외**는 기존 유지(`shared/attraction_filters.py`). |
| 2026-04-02 | **계절 반영 명소 추천**: 여행 **시작~종료** 날짜에 포함된 **월**이 5~9월과 겹치면 `ski_resort`·스키 학교·스노우파크 등 겨울 전용 시설을 후보에서 제외(`filter_attractions_warm_season_no_ski`, `should_exclude_warm_season_ski_place`). 겨울(해당 월 없음) 일정은 스키장 후보 유지. Places 수집에 `end_date` 전달·LLM 프롬프트에 계절 지시 보강. |
| 2026-04-02 | **명소에서 투어·가이드 업체 제외**: Places `travel_agency` 타입·이름 패턴(예: `Vercellioutdoor`, `local guide`, `tour agency`, `…outdoor` 복합 상표 등)으로 현지 가이드·투어사를 걸러냄. 자연 POI(`natural_feature`·`park` 등)는 유지. `shared/attraction_filters.py`, Nearby 수집·LLM 병합·`postprocess_attraction_list_for_catalog`·Places 상세 `place_types` 저장(`shared/google_place_details.py`). |
| 2026-04-02 | **프론트 정적 캐시**: `index.html`에서 `app.js`·`styles.css`·`airports.js` 쿼리 버전 `v=5`로 올려 브라우저가 옛 스크립트를 쓰지 않게 함. `loadPlanIntoState`·명소 API 응답 시 `sanitizeAttractionCatalogInPlace`로 `description`에 남은 단독 `Google Maps` 줄을 즉시 정리(저장 JSON에도 반영). 지도 링크 표시는 `지도`+`aria-label="Google Maps"`. |
| 2026-04-02 | **명소 description Google Maps 잡음**: 단독 줄 `Google Maps`를 `**Google Maps**`·목록 접두(`- `) 등 **마크다운 꾸밈까지 벗겨** 감지해 **전부 제거**(첫 줄 유지 로직 제거). `<br>`을 줄바꿈으로 취급. 프론트·`sanitize_attraction_description_for_catalog` 동일(`shared/google_place_details.py`, `frontend/app.js`). |
| 2026-04-02 | **명소 description 서버 정리**: `postprocess_attraction_list_for_catalog` 끝에서 `sanitize_attraction_description_for_catalog`로 `google_maps_url`이 있을 때 단독 줄 `Google Maps` 제거, URL 직후 라벨 제거, 같은 줄 중복 제거(NFKC·제로폭 정규화). 프론트 `prepareAttractionDescription`도 동일 규칙으로 맞춤(`shared/google_place_details.py`, `agents/itinerary/executor.py`, `frontend/app.js`). |
| 2026-04-02 | **명소 UI**: 소개 본문에 `google_maps_url`과 동일한 URL이 있을 때 **URL 직후** 중복 라벨 `Google Maps` 한 번 제거. 카드에 지도 링크가 있으면 **줄 전체가 `Google Maps`뿐인 줄**은 링크와 중복이므로 제거(연속 두 줄 등). 문장 안 `Google Maps 기준` 등은 유지. `입장료·톨·기타`는 `http(s)://` URL을 새 탭 링크로 표시(`renderPracticalDetailsHtml`, `frontend/styles.css`). |
| 2026-04-02 | **명소 소개 URL**: `description`에 `http(s)://`가 있으면 새 탭으로 여는 링크로 표시(`linkifyUrlsInPlainText`, `frontend/app.js`, `frontend/styles.css`). |
| 2026-04-02 | **fees_other 시드**: Places 보강 시 입장료 칸에 **절차·메타 문단**을 넣지 않고 비우거나 `공식 웹에서 요금 확인: URL`만 둠. `_merge_practical`은 `fees_other`를 **덮어쓸 때 빈 문자열 허용**. 폴리시 프롬프트에 **수치만·절차 설명 금지** 명시 (`shared/google_place_details.py`). |
| 2026-04-02 | **입장료는 Google 웹 검색만**: Places API가 아니라 **Google 검색 스니펫**만 사용한다는 점을 시드·프롬프트에 명시. **Custom Search JSON API**(`GOOGLE_CSE_CX`+키) 우선, 없으면 **SerpApi `engine=google`**. 페이로드 키 `google_web_search_snippets`. |
| 2026-04-02 | **입장·주차 = Google 웹 검색 스니펫**: Places API로 입장료를 받지 않고, `GOOGLE_CSE_CX`+키가 있으면 **Custom Search JSON API**로, 없으면 **SerpApi `engine=google`**으로 `이름+입장료`·`이름+주차비` 검색 스니펫을 모아 LLM이 `fees_other` 정리. `shared/fees_web_search.py`, `google_cse_cx` (`config.py`). |
| 2026-04-02 | **명소 카드 중복·일관성**: 소개(description)와 **준비·팁**에 평점이 겹치지 않도록 Places 시드에서 tips는 비우고, 폴리시에 `tips`·`fees_other`·`reservation_note` 지시 보강. **예약·운영**에서 Maps URL 줄 제거(카드 링크와 중복). 요일별 영업이 **전부 동일**하면 한 줄로 압축. 입장료 칸은 리뷰 발췌 €와 모순 없게 서술하도록 안내. 프론트는 공식 웹·지도 URL이 같으면 링크 한 줄(`shared/google_place_details.py`, `agents/itinerary/executor.py`, `frontend/app.js`). |
| 2026-04-02 | **도보·하이킹 리뷰 발췌**: Places `walking_hiking` 시드에서 리뷰를 **280자에서 자르지 않고** 합친 뒤, LLM 폴리시가 **1000자 이내 요약**하도록 프롬프트 명시. 폴리시 입력은 `walking_hiking`만 **최대 12000자**까지 전달. 폴리시 후에도 길면 **문장·발췌 단위**로 압축(`walking_hiking_clamp_smart`). `OPENAI_API_KEY` 없을 때는 요약 대신 경계 기반 압축 (`shared/google_place_details.py`, `agents/itinerary/executor.py`). |
| 2026-04-02 | **parking 문구**: `…에서 이 명소까지 승용차` → **`…에서 승용차`** 로 더 짧게 (`shared/directions_parking.py`, `shared/google_place_details.py`). |
| 2026-04-02 | **parking 문구 간결화**: `(가) 거점 … (나) …` 이중 문장 대신 **`{거점}에서 승용차 약 N분 (Google Maps 도로 검색 기준).`** 한 줄로 표시. LLM 구조 필드 조합·`parking_requires` 판정 동일 형식 반영 (`shared/directions_parking.py`, `shared/google_place_details.py`). |
| 2026-04-02 | **거점 표시명 역지오코딩**: 거점 좌표의 도시·마을 라벨을 **영어(`en`) 우선**, 없으면 **한국어(`ko`)** Geocoding으로 가져와 유럽 지명이 자연스럽게 나오도록 함 (`shared/directions_parking.py`). |
| 2026-04-02 | **parking 주행 분 API 확정**: `GOOGLE_PLACES_API_KEY`로 **Geocoding**(목적지)·**Places Nearby**(locality)·**Directions**(승용차)를 호출해 거점 후보 중 **주행 시간이 가장 짧은** 도심을 고르고, `(나)`의 **분**을 LLM이 아닌 **Directions 결과**로 채움. Place Details에 `geometry` 요청·`attr_lat`/`attr_lng` 저장 (`shared/directions_parking.py`, `shared/google_place_details.py`, `agents/itinerary/executor.py`). Console에서 **Directions·Geocoding API** 활성화 필요. |
| 2026-04-02 | **거점 = 지도상 가장 가까운 마을**: 광역 지명(예: Dolomites) 지오코딩을 거점으로 쓰지 않고, Places **Nearby `rankby=distance`·`type=locality`** 첫 결과(실패 시 반경+직선거리 최소)로 거점명을 정한 뒤 그 좌표→명소 **Directions**로 분만 표시. 인구 문구 제거 (`shared/directions_parking.py`). |
| 2026-04-02 | **일정 보강 경로 통일**: Session이 itinerary A2A에 실패하거나 빈 응답일 때 쓰는 **목(mock) 명소**도 Itinerary와 동일하게 `postprocess_attraction_list_for_catalog`(Places·**OPENAI_API_KEY**·이미지)를 거치도록 수정. 이전에는 이미지만 붙이고 **parking LLM 보강이 아예 실행되지 않았음**. A2A 실패 시 `session` 로그에 경고. (`agents/session/executor.py`, `agents/itinerary/executor.py`) |
| 2026-04-02 | **명소 실무**: Places는 `parking`을 **비워** LLM이 **인구 3천+ 거점·승용차 ○분**만 채우게 함(내비 검색어 스텁 제거). **`parking_requires_llm_hub_distance`**·`내비 검색어` 플레이스홀더·재폴리시. 일정·숙소 근거 문구를 프롬프트에 명시 (`shared/google_place_details.py`, `agents/itinerary/executor.py`). Tre Cime 등 **중복 병합**, 사진 Details·Commons (`shared/place_images.py`). **LLM 폴리시 결과 병합을 청크 배열 순서 우선 + 이름 폴백**으로 바꾸고, parking 전용·거점 최종 패스는 **`idx`로 병합**해 이름 불일치로 거점·주행 시간이 UI에 안 나오던 문제를 줄임. |
| 2026-04-02 | **parking 검증 완화**: `인구`라는 글자 없이 `○○명`만으로 인구를 적은 문장도 **합격**으로 처리해, 모델이 정상 출력한 거점·분 정보가 **검증 실패로 무한 재폴리시·덮어쓰기 꼬임** 나지 않게 함. `openai` 폴리시 실패 시 **무음 예외 제거**·로그 (`shared/google_place_details.py`, `agents/itinerary/executor.py`). |
| 2026-04-02 | **parking 병합·보강**: 메인 폴리시에서 **비어 있지 않은 새 `parking`은 검증과 무관하게 반영**(기존 문구가 잘못 ‘합격’해 더 나은 새 문구가 버려지던 문제 수정). **영어 `minutes`/population 표기**도 합격 처리. `_need_polish`가 전부 False여도 **거점 전용 repair·최종 패스는 계속 실행**. 청크 폴리시 실패 로그를 `warning`으로 상향 (`shared/google_place_details.py`). |
| 2026-04-02 | **전 명소 parking 강제**: 보강 마지막에 **모든 명소**를 대상으로 `parking`만 재작성(거점 도시·인구·승용차 ○분·€)하는 청크 패스 + 미달 시 1회 재시도. 1차 명소 생성 프롬프트에도 **어느 도시에서 몇 분**을 문단 필수로 명시 (`shared/google_place_details.py`, `agents/itinerary/executor.py`). |
| 2026-04-02 | **parking (가)(나) 서버 조합**: 강제 패스에서 LLM이 **자유 문단** 대신 `hub_place_name`, `population_ko`/`population`, `drive_minutes`, `parking_and_toll_eur` 필드만 채우면, 서버가 **`(가) 거점 … (나) …분`** 형식으로 합쳐 UI에 고정 노출. `parking_requires`는 `(가)(나)`+분이 있으면 보강 생략 (`shared/google_place_details.py`). 명소 카드 라벨: **주차·도로 (거점·승용차 분)** (`frontend/app.js`). |
| 2026-04-01 | **명소 실무 정보(주소·웹·영업·리뷰)**: 각 `place_id`에 대해 **Places Details API**로 주소·전화·웹·Maps 링크·영업시간·리뷰 일부를 가져와 `practical_details`와 평점-only `description`을 자동 보강하고, 여전히 짧거나 기본 문구가 남으면 **추가 LLM 패스**로 구체화한다. 프론트 명소 카드에 **공식 웹·Google Maps** 링크를 표시한다(`shared/google_place_details.py`). |
| 2026-04-01 | **명소 후보·설명·이미지 품질**: Places **Nearby**를 `tourist_attraction`뿐 아니라 `park`·`natural_feature`·`point_of_interest`와 영어 키워드(hiking, trail, lake 등)로 확장하고, **Text Search**로 호수·트레일 후보를 보강. 리뷰 수 기준을 완화해 고산 호수·트레일처럼 리뷰가 적어도 평점이 높은 곳을 포함. **여름(6~9월)에는 `ski_resort` 유형**을 제외. 구글만으로 개수가 부족하면 **돌로미티 오프라인 명소 풀**로 일수×3까지 채움. LLM 프롬프트에서 **이름 복사·조사형 설명·계절·내부 관람형 제외 규칙**을 강화하고, 박물관·공연장은 입장 정보가 없으면 후보에서 제거. 명소 이미지: Places Text Search에 **지역 bias·이름-결과 일치 검증**, SerpApi는 **한국 소매 등 오탐 제목 필터**, `enrich`의 **place_id 중복 시 카드 누락 버그** 제거. |
| 2026-04-01 | **편도 일정 시 여행 일수(귀환일) 누락 버그 수정**: 편도(One-way) 여정 선택 시 프론트엔드(`app.js`)에서 사용자가 입력한 귀환일을 무시하고 출발일로 덮어쓰는 바람에 전체 일정이 무조건 1일로 고정 계산되던 치명적인 버그를 수정했습니다. 이제 편도 항공편을 이용해도 21일 등 장기 여행 일정을 정상적으로 계획하고 명소(일수x3)를 추천받을 수 있습니다. |
| 2026-04-01 | **명소 추천 개선 (1:4 경로 비율 및 구간 동선 검색)**: 구글 Directions API를 활용해 차량 이동 경로를 5개 구간으로 나누어 탐색하고, 명소를 동선 상에서 1/5, 최종 목적지에서 4/5 비율로 분배. `radius`를 45,000m로 제한해 엉뚱한 해외 관광지 노출 방지. 병원, 치과, 숙박시설 등 불필요한 장소를 Type 블랙리스트로 걸러냄. LLM이 명소 설명 시 단순 요약이 아닌 '여행지로서의 가치와 매력'을 구체적으로 설명하도록 프롬프트 업데이트. 명소 수를 여행 일수의 3배수로 정확히 출력하도록 개수 계산 로직 조정. |
| 2026-04-01 | **일정 에이전트 상세정보 고도화**: LLM 토큰 초과 방지를 위해 최대 요총 30개로 제한. 비행기 출발지("서울")가 렌트카 동선 지오코딩에 혼입되는 버그(`transit_origin` 분리) 해결. 구글맵 명소 리스트의 "이름"을 LLM에 주입하여 이름표는 구글맵 기반으로, 주차·요금·소요 시간 정보는 LLM이 작성하도록 콜라보레이션 연동 설계. |
| 2026-04-01 | **일정명소 탐색 최적화**: 렌트카 구간 다중 거점 기반 반경(35km)을 활용한 Google Places API 탐색 적용 (로마 등 엉뚱한 타지역 노출 차단). `place_id`를 활용한 철저한 이중 명소 중복(Deduplication) 필터 적용. Google Places Photo API의 고품질 사진을 100% 최우선 연동하도록 `resolve_place_image` 우선순위 상향. 12일 고정 버그를 수정하여 `start_date` 및 `end_date` 기반 정확한 실제 단위의 `trip_days` 출력 반영. |
| 2026-03-31 | **파일 내보내기/불러오기 기능 추가**: 서버나 브라우저 `localStorage`에 의존하지 않고, 여행 계획 전체를 데스크톱/클라우드 등 어떤 환경에서든 즉시 복원할 수 있도록 단일 `.json` 파일 내보내기와 불러오기 버튼을 추가했습니다. |
| 2026-03-31 | **도커 빌드 최적화**: 윈도우(WSL2) 도커 빌드 시 `transferring context` 단계에서 가상환경 파일들(`.venv`, `__pycache__` 등) 전송 병목으로 무한 대기하던 현상을 해결하기 위해 `.dockerignore` 파일을 추가했습니다. |
| 2026-03-23 | **명소 이미지**: 위키·Commons는 **검색 다중 후보 중 제목·명소명 관련성** 통과 후만 채택, **목록 내 동일 URL 중복 방지**, 실패 시 **Unsplash 폴백 없음**(사진 없음 + 안내). 선택 `PLACE_IMAGES_USE_SERPAPI`+`SERPAPI_API_KEY`로 Google 이미지 보강. `shared/place_images.py` · [docs/IMAGES_AND_LICENSES.md](docs/IMAGES_AND_LICENSES.md) |
| 2026-03-23 | **명소 1단계**: 유형만이 아니라 **구체 관광지명·사진·실무 정보**(주차·예약·€대략·케이블카·도보 시간)를 카드로 표시. LLM·mock 스키마 `image_url`·`practical_details`. 돌로미티 키워드 시 Tre Cime·Seceda 등 구체 명소·요금 안내가 포함된 오프라인 후보 |
| 2026-03-23 | **여행 일정**: 문화/휴양/액티비티 3안 대신 **다단계 일정** — 명소 후보(체류일수×3)·동선·추천 동네·공항 구간 볼거리·명소별 맛집 3곳(평점순)·날짜별 점심·저녁 1·2순위·최종 요약. 세션 `itinerary_phase`, Itinerary Agent·프론트 워크플로. 구형 3안 JSON은 레거시로 표시 |
| 2026-03-23 | Amadeus fallback: **편도(출국)**일 때 날짜 유연성이 빠지던 문제 수정 — 출발일 ±N일 쌍(`_one_way_departure_date_pairs_for_amadeus`). KE/OZ 보강 날짜쌍 2→5. `FLIGHT_API_SETUP.md` 반영 |
| 2026-03-23 | 귀국 동일 항공사 안내: **SerpApi `include_airlines` 1차 0건** 설명으로 명확화(Amadeus·날짜유연성 구분). `FLIGHT_API_SETUP.md` 작동 원리 보강. 단일 날짜 경고 `dict.fromkeys`로 중복 제거 |
| 2026-03-23 | 공항 선택: 국제선 **8h·같은 나라 우선**, 국내선 **3h 이상** 우선(완화). 왕복 **귀국편**에 출국 항공사 우선(`preferred_return_airline_code`, Flight Agent·MCP). README·스키마·UI 문구 반영 |
| 2026-03-23 | 렌트: Travelpayouts `tpemd` **검색 위젯** 연동 제거(항공 일정·픽업/반납과 **자동 연계할 공개 스펙 없음**). `TRAVELPAYOUTS_RENTAL_WIDGET_SCRIPT_URL`·세션/프론트 위젯 필드 삭제 |
| 2026-03-23 | 렌트: EB 일당 스크레이프 **보수화** — 마케팅 €9 등은 제외, **15~350€ 구간·중앙값**, 스크립트 제거. `price_basis` 문구 정리 |
| 2026-03-23 | 렌트: **가격·비교** — EB HTML에서 € 토큰 폭넓게 파싱, 차급 카드에 **공항 일당 폴백×계수** 추정, 카드별 `price_label_ko`·**가격순 정렬**. EconomyBookings **`/en/cars/results?plc=…`** 실시간 목록 링크(`eb_cars_results_url`)·UI 버튼 복구 |
| 2026-03-23 | 렌트 **선택 불가 수정**: 세션 `local_transport` 파싱을 BOM·공백·코드펜스 허용(`_parse_agent_json_array`). 프론트 `normalizeLocalTransport`·목록 비었을 때 안내·선택 힌트·`btn-next-rental` 가드. 카드 HTML `escapeHtml`. 렌트 MCP 응답 strip |
| 2026-03-23 | 렌트: 차급 카드 **버튼 URL을 차종별 EB 딥링크로 분리**(기존 공항 URL 3중복 제거). 공항 랜딩 **`/en/car-rental/…`**. 전 카드에 `rental_schedule_line`·인원 메타. 제휴 추적은 **검색당 1회** `fetch` 후 `apply_economybookings_tracking_to_url`. 프론트 버튼 문구·`.rental-schedule` 스타일 |
| 2026-03-23 | 렌트: `economybookings.tpk.ro` 제휴 URL에서 **btag·tpo_uid** 추출해 EconomyBookings **비교·차급** 예약 링크에 병합(`travelpayouts_economybookings.py`). 제휴 카드 문구는 병합 성공 여부에 따라 분기. 문서 반영 |
| 2026-03-24 | 렌트: EB **`cars/results` 딥링크 제거**(빈 결과 이슈) → 사용자 링크는 **공항 랜딩+날짜·시각**만. `TRAVELPAYOUTS_RENTAL_BOOKING_URL`이 항공 URL이면 제휴 카드 생략·로그. 프론트 제휴 버튼 문구 |
| 2026-03-24 | 렌트: EconomyBookings **`/[lang]/cars/results?plc&py&pm&pd&pt…`** 딥링크(공항 페이지 `mergedLocationId` 1회 조회·캐시). SEO 차종·공항 랜딩은 가격 스크레이프만. SerpApi **항공 전용** organic 제외. `economybookings_links.py` |
| 2026-03-24 | 렌트: 차급 카드 **일행~일행×1.5좌석** 범위만 표시(폴백 시 최소 적합 티어만). EB **차종별 딥링크**+날짜·시각 쿼리, HTML **From 일당** 파싱으로 차급·공항 카드 **가격 힌트**(SerpApi 최저와 병합). `economybookings_hint.py` |
| 2026-03-23 | 렌트: **Amadeus 트랜스퍼·안내 카드 제거**(셀프 드라이브 중심). SerpApi **영문+현지어** 검색 병합, **차급 스펙 카드**(`vehicle_class_guide`)·EconomyBookings·제휴(하단) 순. 프론트 면책·문서·`.env.example` 정리 |
| 2026-03-23 | 렌트: **SERPAPI_API_KEY**로 SerpApi Google 검색 → 일정·일행 반영 셀프 드라이브 **후보 카드**(출처 URL, 스니펫 기반 추정 원화·`price_basis`). Amadeus 트랜스퍼 카드에 `termsUrl` 링크. `mcp_servers/rental_car/serpapi_rental.py` |
| 2026-03-23 | 렌트카 기본 시각: 픽업 **도착 1시간 후**, 반납 **출발 2시간 전** (세션 `_build_local_transport_payload`, 프론트 `fillRentalSearchFormFromFlight`) |
| 2026-03-23 | **렌트카 단계**: 항공 기준 픽업·반납 **일시 편집** + `rental_search`로 재검색. Amadeus **Transfer Offers**(공항↔시내)로 견적 카드(`offer_kind`, `price_total_krw`). 가짜 브랜드 참고 카드 제거. 세션 `_merge_rental_search`·`pickup_datetime`/`dropoff_datetime` 페이로드. 문서·`.env.example` 반영 |
| 2026-03-23 | 항공 선택 완료 시 **렌트카/대중교통 단계 자동 진행**(`advanceToLocalTransportStep`). 세션: `_build_local_transport_payload`로 공항 IATA·항공 도착 시각·체류 일수 반영. 대중교통: Transit MCP `search_routes` + `get_transit_passes` 병합 호출 |
| 2026-03-23 | 프론트: 항공 목록 렌더 시 편도·귀국편 단계에서 `ret`가 null일 때 `duration_hours` 접근으로 크래시 나던 문제 수정 (`frontend/app.js` optional chaining) |
| 2026-03-23 | 항공: 마일리지 계획용 **대한항공·아시아나(KE/OZ) 필수 노출** — SerpApi `include_airlines` 보강 병합, Amadeus fallback 시 `includedAirlineCodes=KE,OZ` 항상 병합, KE/OZ `mileage_eligible` 배지는 프로그램 미선택 시에도 표시. FLIGHT_API_SETUP·MCP 도구 설명 반영 |
| 2026-03-21 | 항공 검색: **SerpApi 우선**, Amadeus(429)·이어서 **Travelpayouts는 캐시 최저가 참고용**(SerpApi·Amadeus 모두 0건일 때). README·FLIGHT_API_SETUP·DEPLOYMENT·MCP 서버 문구 반영 |
| 2026-03-20 | FLIGHT_API_SETUP §4.1: Travelpayouts `cheap`/월 재시도가 “전 항공사 시장 검색”이 아니라 캐시 기반이라 `data={}`·특정 항공사 부재가 날 수 있음을 문서화 |
| 2026-03-20 | Travelpayouts: 공항 코드(ICN·MXP 등)로 `cheap`이 빈 `data`일 때 도시 IATA(SEL·MIL 등)로 자동 재시도, 이후 월(yyyy-mm) 재조회·`/v2/prices/week-matrix`(show_to_affiliates=false) 보조 조회. Aviasales 링크·표시 구간은 사용자 입력 공항 코드 유지. 빈 캐시 시 진단 문구 정리 |
| 2025-03-20 | Travelpayouts: 연결 성공/HTTP 오류/토큰 거부/캐시 0건 등 `[Travelpayouts 진단]` 경고를 항상 남기고, SerpApi 단계로 넘어갈 때도 동일 경고가 목록 상단에 유지되도록 수정 |
| 2025-03-20 | Travelpayouts: `data`가 배열이거나 목적지 키 아래 티켓이 바로 올 때·`value`/`depart_date` 필드 등 기존 파서가 0건으로 버리던 응답을 수집하도록 수정. 쿼리에 `token` 병행, `success`·`error` 처리 보강 |
| 2025-03-20 | 항공 검색 응답·UI에 `flight_search_api` 표시(실제 사용된 API·엔드포인트 안내). 계획 저장 시 `flightSearchApi` 포함 |
| 2025-03-20 | 항공: Travelpayouts Data API 1순위(SerpApi·Amadeus·Mock 순 fallback). 렌트카: `TRAVELPAYOUTS_RENTAL_BOOKING_URL` 시 제휴 카드 최상단. `docker-compose`에 `env_file: .env` 추가, 배포 가이드·FLIGHT_API_SETUP·README 반영 |
| 2025-03-17 | 렌트카: 근거 없는 가격 제거, EconomyBookings.com 선호 예약 사이트로 통합 |
| 2025-03-17 | 렌트카: EconomyBookings 600+ 업체 비교 카드 검색 결과 상단 포함, 공항별 URL 매핑 |
| 2025-03-17 | 렌트카: 탑승 가능한 차량 모두 표시(필터 완화), 결과 수 표시 |
| 2025-03-17 | 렌트카: 일행 수 x 1.5 좌석(여행가방 고려) → 추천 배지로 표시 |
| 2025-03-17 | 렌트카: 상세 차량 정보(모델명·설명·특징·수하물·사진) 및 예약 사이트 연결 버튼 추가 |
| 2025-03-17 | A2AClient: result.parts 형식(플랫 메시지) 응답에서 텍스트 추출 지원, 렌트카 목록이 메시지로 감싸져 전달되던 버그 수정 |
| 2025-03-17 | 렌트카: 항공편 선택 후 현지 도착일·출발일을 렌트카 대여 기간으로 자동 반영, 일행 수에 맞는 차량만 검색 (passengers·seats) |
| 2025-03-17 | Amadeus: Skypass/아시아나 시 선호 항공사 전용 검색(includedAirlineCodes) 병합, 대한항공 누락 방지 |
| 2025-03-17 | Amadeus fallback에 날짜 유연성 적용 (여러 날짜쌍 병렬 검색 후 병합) |
| 2025-03-17 | 1단계 편도 전부 0건+SerpAPI 한도 초과 시 2·3단계 생략, 즉시 Amadeus fallback으로 전달 |
| 2025-03-17 | Amadeus fallback: asyncio.run() in running loop 오류 수정 (ThreadPoolExecutor로 별도 스레드에서 실행) |
| 2025-03-17 | SerpApi 429 시 Amadeus fallback 실행 순서 수정 (날짜 유연성 early return보다 먼저). Amadeus 미설정 시 .env 안내 메시지 |
| 2025-03-17 | SerpApi 한도 초과(429) 시 Amadeus API fallback 추가. AMADEUS_CLIENT_ID, AMADEUS_CLIENT_SECRET 설정 시 자동 전환 |
| 2025-03-17 | 직항 전용 검색 0건 시 메인 결과 유지(최저가 5건만 표시하지 않음). Amadeus Test 직항 데이터 제한 안내 |
| 2025-03-17 | 직항 우선 검색(stops=1/nonStop) + 최저가 5건 참고 병합. 직항 결과 상단, 최저가 5건 하단 참고 |
| 2025-03-17 | 날짜 유연성: 0건 시 flex 0/None이면 flex=2로 자동 재시도 (전달 누락 회피), form.elements로 날짜 유연성 입력 확실히 읽기 |
| 2025-03-17 | 날짜 유연성: 출발/귀환 각각 ±N shift 추가 (기존 동시 shift에 더해 더 많은 날짜 조합 검색) |
| 2025-03-17 | SerpApi 429(한도초과) 시 상세 안내 표시, FLIGHT_API_SETUP에 점검 방법 추가 |
| 2025-03-17 | SerpApi 0건 시 메시지 수정: "예약 기간" 가정 제거, no_cache 추가로 빈 결과 버그 완화 |
| 2025-03-17 | 왕복 가격: SerpApi 왕복 검색(one_way=False)으로 출발+귀환 포함 총 왕복 가격 표시, 한 번에 선택 |
| 2025-03-17 | 계획 서버 저장: 사용자별 서버 저장 구조 (api/plans, SQLite), 연결 코드로 다른 기기 접속, 나중에 가입·로그인 연동 가능 |
| 2025-03-16 | 헤더 문구 한 줄 표시, 항공편 선택 복귀 시 선택 항공편 날짜·시간·비행시간·구간 상세 표시 |
| 2025-03-16 | 왕복 항공편: 출국+귀국 선택 후 다음 시 렌트카 단계로 정확히 이동 (fallback 시 rental 재요청) |
| 2025-03-16 | 새로 만들기/저장 버튼: DOMContentLoaded 후 초기화, 취소/실패 시 안내 메시지 표시 |
| 2025-03-16 | 계획 저장·불러오기: 단계별 진행 내용을 저장·열기·다른 이름으로 저장 (localStorage, 파일 편집처럼 이어서 계획 가능) |
| 2025-03-03 | "귀국편 검색" 버튼 미표시 수정: showFlightSummaryForEdit·show()·취소 시 updateFlightNextButtonLabel 호출 보강 |
| 2025-03-03 | 왕복 귀국: 출국 선택 후 "귀국편 검색" 버튼 표시, trip_type form 직참조 |
| 2025-03-03 | 항공편 가격 disclaimer: SerpApi 가격이 Google Flights와 다를 수 있음을 UI에 안내 |
| 2025-03-03 | 왕복: 출국 선택 후 귀국 선택 단계로 정확히 이동, 응답 fallback 처리 강화 |
| 2025-03-03 | 항공권→렌트카/대중교통→일정 순서 확실히 적용 (data.step 분기) |
| 2025-03-03 | Cursor 규칙: 변경 시 문서·GitHub·서버 안내를 사용자 요청 없이 자동 수행 (.cursor/rules/README-updates.mdc) |
| 2025-03-03 | 다구간 항공편: 각 구간별 검색·선택 지원 (multi_city_0, multi_city_1, ...) |
| 2025-03-03 | 단계 표시 버튼 클릭: 해당 단계로 이동, 확정된 정보 확인·수정 가능 |
| 2025-03-03 | 항공편 선택 흐름 개선: 왕복 시 출국→귀국 2단계 선택(편도 검색), 항공편 선택 후 렌트카/대중교통 단계 추가 |
| 2025-03-03 | 초기 구현 완료: 7개 A2A Agent, 4개 MCP Server, 반응형 Web UI, Docker Compose |
| 2025-03-03 | DEPLOYMENT.md 추가: GitHub 업로드, Ubuntu 서버 배포, systemd, Nginx 가이드 |
| 2025-03-03 | LLM 설정 안내 추가: OpenRouter 경유 Gemini 3.1 Pro 사용 방법 (README, DEPLOYMENT) |
| 2025-03-03 | 방화벽/포트 설정 안내 추가: UFW, 클라우드 보안 그룹 (DEPLOYMENT 2.5, README) |
| 2025-03-03 | Nginx 역방향 프록시 상세: 보안 이점, Rate limiting, 방화벽 80/443만 개방 (DEPLOYMENT §5) |
| 2025-03-03 | 가정/사무실 배포: DuckDNS + KT 공유기 포트포워딩 + Nginx 설정 가이드 (DEPLOYMENT §6) |
| 2025-03-03 | main.py: uvicorn 서버 실행 코드 추가 (502 Bad Gateway 수정) |
| 2025-03-03 | 트러블슈팅: 502 Bad Gateway, Docker 권한 오류 상세 (DEPLOYMENT §8) |
| 2025-03-03 | docker-compose: version 필드 제거 (Deprecated 경고 해소) |
| 2025-03-03 | a2a-sdk 0.3.x 호환: shared.utils.new_agent_text_message 추가, MessagePart→Part/TextPart |
| 2025-03-03 | AgentSkill: a2a-sdk 필수 필드 description 추가 |
| 2025-03-03 | 배포 정상화: a2a-sdk 0.3.x 호환 트러블슈팅·체크리스트 (DEPLOYMENT §8) |
| 2025-03-03 | 여행 정보 입력 설계 원칙 5항목: 출발지/목적지(공항), 귀환일, 날짜유연성, 숙소3순위, 단계·다음버튼 (README §1.2, 구현 반영) |
| 2025-03-03 | 단계 인디케이터: 7단계 화살표 흐름(여행정보→항공편→렌트카/대중교통→일정→숙소→확정→예약), 현재 단계 강조 |
| 2025-03-03 | 8시간 이내 공항 선택: 출발지/목적지가 도시일 때 지상·해상 8시간 이내 공항 목록 선택 UI (airports.js, step-origin-airports, step-destination-airports) |
| 2025-03-03 | 달력 UI: 출발일·귀환일 달력에서 날짜 선택 (calendar-picker, 월 이동, 클릭 선택) |
| 2025-03-03 | Cursor 규칙: 수정 시 README Changelog + GitHub push 반드시 수행 (.cursor/rules/README-updates.mdc) |
| 2025-03-03 | 달력: 귀환일 달력 미선택 시 출발일 달을 기본으로 표시 |
| 2025-03-03 | 일행 구성: 여행 정보 입력 시 남성·여성·아동 인원 입력 (TravelerComposition, travelers) |
| 2025-03-03 | 초기 로드 시 단계 인디케이터 '여행 정보' 활성 표시 |
| 2025-03-03 | 돌로미티/도로미티 공항 추가(VCE, VRN, INN 등) |
| 2025-03-03 | 405 Method Not Allowed 대응: API 경로 /a2a/ (trailing slash), Accept 헤더 |
| 2025-03-03 | 목적지 공항: MXP(밀라노 말펜사) 추가, 직항·마일리지(Skypass) 우선 정렬, 배지 표시 |
| 2025-03-03 | 귀환일≥출발일 검증, localStorage로 입력값 저장/복원, 항공편 Mock·표시 개선(노선별·포맷) |
| 2025-03-03 | Amadeus + Kiwi + RapidAPI(Skyscanner) 멀티소스 항공편 검색, 무료 한도 관리·경고 |
| 2025-03-03 | No response 대응: 응답 파싱 강화(result.parts, 중첩 메시지), Session 예외 처리, mock에 공항코드 반영 |
| 2025-03-03 | Mock 사용 시 UI 배너: "예시(Mock) 데이터입니다" 명시 표시, source:mock 추가 |
| 2025-03-03 | FLIGHT_API_SETUP.md: Amadeus/Kiwi/RapidAPI API 키 발급 절차 및 .env 설정 상세 가이드 |
| 2025-03-03 | FLIGHT_API_SETUP: Kiwi 초대제 전환, RapidAPI Skyscanner 제공 중단 반영, Amadeus 단독 사용 권장 |
| 2025-03-03 | Amadeus 401 수정: Test 환경(test.api.amadeus.com) 기본값, AMADEUS_BASE_URL 지원 |
| 2025-03-03 | Mock fallback: API 정상 연결·0건 시 '아직 예약 가능한 기간이 아닙니다' 사유 안내 |
| 2025-03-03 | Mock 메시지: 401 등 API 오류 시 '예약 기간' 문구 표시하지 않음 (실제 API 결과 없음만 표시) |
| 2025-03-03 | Amadeus 401: Test↔Production 자동 재시도, 401 해결 가이드 (FLIGHT_API_SETUP §1.5) |
| 2025-03-03 | Amadeus no apiproduct match: Flight Inspiration Search 자동 대체, §1.6 문서화 |
| 2025-03-03 | flightapi.io 연동 추가 (100회/월 무료), RapidAPI 항공편 API 옵션 문서화 |
| 2025-03-03 | "this event loop is already running" 수정: uvicorn 내 이벤트 루프 중첩 방지, ThreadPoolExecutor 활용 |
| 2025-03-03 | Amadeus 제거: 401 등 결과 미제공으로 flightapi.io·Kiwi·RapidAPI만 사용 |
| 2025-03-03 | 마일리지 선호 항공사 우선: mileage_program 입력 시 해당 항공사 편 상단 노출, 전편 표시, 스크롤 UI |
| 2025-03-03 | Cursor 규칙: 수정 시 관련 문서(README, FLIGHT_API_SETUP, DEPLOYMENT 등)·GitHub 반영 필수 |
| 2025-03-03 | Docker: PYTHONUNBUFFERED 추가, Exited(1) 진단 절차 보강 (DEPLOYMENT §8) |
| 2025-03-03 | Settings extra=ignore: .env에 과거 amadeus 변수 남아 있어도 검증 통과 |
| 2025-03-03 | Korean Air 노출 개선: API 결과 10→25건 확대, Skypass 시 KE 없으면 참고용 mock 보충 |
| 2025-03-03 | 돌로미티+Skypass: MXP(대한항공 직항) 최우선, 다중 공항 검색, 마일리지 직항 공항 정렬·권장 배지 |
| 2025-03-03 | Flight API SerpApi 전환: Duffel 제거, SerpApi Google Flights 사용 (한국 가입 가능, 월 250회 무료) |
| 2025-03-03 | 추천순 정렬: 1) 선호 직항 2) 선호 경유(비행시간↑) 3) 나머지 직항 4) 나머지 경유(비행시간↑). 동일 그룹 내 비행시간↑ 최저가↑ |
| 2025-03-03 | Duffel → SerpApi 전환: api_clients, services, config, 문서 전체 (한국 가입 가능, 월 250회 무료) |
| 2025-03-03 | 날짜 유연성 적용: date_flexibility_days > 0 시 ±일 범위 내 병렬 검색 후 결과 통합 |
| 2025-03-03 | Mock 보충 제거: 검색 결과 있을 때 선호 항공사 mock_reference 혼입 금지 (혼동 방지) |

---

## 9. 배포

GitHub 업로드 및 Ubuntu 서버 서비스 배포 방법은 [DEPLOYMENT.md](DEPLOYMENT.md)를 참조하세요.

- **포트**: 웹 UI는 9000, Agent는 9001~9006. 외부 접속 시 방화벽에서 9000 허용
- **Nginx 역방향 프록시 (권장)**: 80/443만 열고, 내부에서 9000으로 프록시하면 HTTPS 적용이 쉽고 Trip Agent를 외부에 노출하지 않아 더 안전합니다. [§ 5장](DEPLOYMENT.md#5-nginx-역방향-프록시-선택-프로덕션)
- **가정/사무실 (DuckDNS + KT 공유기)**: 클라우드 없이 집·사무실 서버에서 운영할 때는 공유기 포트포워딩(80, 443)과 DuckDNS 설정이 필요합니다. [§ 6장](DEPLOYMENT.md#6-가정사무실-배포-duckdns--kt-공유기)
- **a2a-sdk 0.3.x**: Docker 컨테이너 Exited(1) 시 [트러블슈팅 §8](DEPLOYMENT.md#8-트러블슈팅) 참고

---

## 10. 참고

- **구현 계획**: `.cursor/plans/` 또는 계획 파일 참조
- **MCP**: [Model Context Protocol](https://modelcontextprotocol.io/)
- **A2A**: [Agent2Agent Protocol](https://google.github.io/A2A/)

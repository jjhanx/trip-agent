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
| **Itinerary Planner Agent** | 명소 후보(일수×3)·동선·숙소 동네·명소별 맛집·최종 일정 (다단계, LLM·mock) |
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
| GOOGLE_PLACES_API_KEY | | **명소 사진·Place Details·좌표** (Google Maps Platform). 동일 키로 **Directions API**(거점→명소 주행 분)·**Geocoding API**(목적지·거점 좌표)를 씁니다. Cloud Console에서 **Places API, Directions API, Geocoding API**가 사용(Enabled)되어 있어야 `parking`의 **○분**이 API로 채워집니다. 월 $200 무료 크레딧 범위 참고. ([발급 가이드](docs/GOOGLE_PLACES_API_GUIDE.md)) |
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
| FLIGHT_MCP_URL | http://localhost:8001/mcp | Flight MCP Server URL |
| HOTEL_MCP_URL | http://localhost:8002/mcp | Hotel MCP Server URL |
| RENTAL_CAR_MCP_URL | http://localhost:8003/mcp | Rental Car MCP Server URL |
| TRANSIT_MCP_URL | http://localhost:8004/mcp | Transit MCP Server URL |

---

## 7. 사용 흐름

1. **여행 정보 입력**: 출발지·목적지(공항 코드 또는 도시), 출발일·귀환일(달력 버튼으로 날짜 선택), 일행 구성(남·여·아동), 날짜 유연성(±일), 숙소 선호 3순위, 현지 이동, 좌석 클래스, 마일리지·마일리지 프로그램 등. 도시 입력 시 국제선/국내선 규칙에 따른 공항 선택 단계가 추가됨
2. **항공편 선택**: **왕복** 시 2a 출국편 → 2b 귀국편 (편도 검색). **편도** 시 1회 선택. **다구간** 시 구간별 순차 선택. 추천순·가격순·비행시간순 정렬. **선택이 끝나면(왕복·편도·마지막 구간)** 렌트카/대중교통 단계로 **자동 이동**하며 세션이 항공 일정에 맞춰 검색을 요청함 ( **다음** 버튼으로도 동일 진행 가능)
3. **렌트카/대중교통**: 렌트카 선택 시 **픽업·반납 일시·공항(IATA)** 입력란에 항공 일정이 채워지며 수정 후 **이 일정으로 다시 검색** 가능. `SERPAPI_API_KEY`가 있으면 **Google 검색**으로 셀프 드라이브 **후보·추정 가격 힌트**를 붙이고, **차급별 스펙 참고 카드**와 EconomyBookings 비교 링크가 이어집니다. 대중교통은 Transit MCP
4. **다음** → 여행 일정: 후보 명소 선택 → **경로·맛집 계획 받기** → 날짜별 점심·저녁 1·2순위 선택 → **일정 확정** → **다음**으로 숙소 단계
5. **다음** → 숙소 선택: 5개 혼합 후보 중 선택 (현지 이동 정보 포함)
6. **일정 확정** → 예약 절차 안내

- 상단 **단계 표시**를 클릭하면 해당 단계로 이동하여 확정된 내용을 확인·수정할 수 있음

**계획 저장·불러오기**: 여행 계획은 단계별로 시간이 걸리므로, 진행 상황을 저장하고 나중에 다시 불러올 수 있습니다. **파일 내보내기 / 불러오기(추천)** 를 이용하면 구글 드라이브나 메신저를 통해 `.json` 파일 하나로 집과 사무실 어디서든 즉각적으로 이어서 계획을 편집할 수 있습니다. 로컬 장비에 설치된 **서버 저장**을 활용할 수도 있습니다(저장 시 발급되는 '연결 코드'를 다른 기기에서 입력).

---

## 8. 주요 변경 사항 (Changelog)

> 주요 변경 시 이 섹션을 업데이트합니다.

| 날짜 | 변경 내용 |
|------|-----------|
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

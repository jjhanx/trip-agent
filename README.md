# Trip Agent

여행 지역·기간·취향을 입력하면 **최저가 또는 마일리지** 항공편, **일정 3안**, **숙소 5개**를 제시하고, 전체 일정 확정 후 **예약 안내**까지 해주는 멀티 에이전트 기반 여행 플래너입니다.

---

## 1. 질의응답 배경 (설계 근거)

### 1.1 요구사항 요약

- **입력**: 여행 지역, 기간, 시작 무렵, 여행 취향, 보유 마일리지, 선호 좌석 클래스, 현지 이동 방법, 선호 숙소 형태
- **출력 순서**:
  1. 최저가 또는 마일리지 활용 항공편 (가격순 정렬)
  2. 선택 항공 + 취향 기반 일정 3안
  3. 숙박 필요 구간별 숙소 5개 비교·선택
  4. 일정 확정 시 예약 안내

### 1.2 여행 정보 입력 설계 원칙

> 다음 5가지 원칙은 구상과 효용에 핵심이므로 구현에 반드시 반영됩니다.

**1. 출발지·목적지: 공항 코드 또는 도시/관광지**

- 출발지·목적지는 **공항 코드**(ICN, KIX 등)일 수도, **도시·관광지 이름**(오사카, 제주 등)일 수 있음
- 지상·해상 교통으로 **8시간 이상** 걸리는 거리면, 항공편 검색을 위해:
  - **출발지**: 8시간 이내 접근 가능한 공항 코드를 사용자에게 선택하게 함
  - **목적지**: 결정 후, 목적지에서 8시간 이내인 공항들을 **출발지 선택 공항 기준 비행시간 짧은 순**으로 제시해 선택하게 함

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
| **Itinerary Planner Agent** | 선택 항공 + 취향 기반 일정 3안 설계 (LLM 활용 가능) |
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
| SERPAPI_API_KEY | [SerpApi](https://serpapi.com) API Key (Google Flights 연동, 대한항공·아시아나 포함) |
| AMADEUS_CLIENT_ID | (선택) [Amadeus](https://developers.amadeus.com) API Key. SerpApi 한도 초과 시 fallback용 |
| AMADEUS_CLIENT_SECRET | (선택) Amadeus API Secret |

**SerpApi**는 월 250회 무료. 한도 초과(429) 시 **Amadeus**로 자동 fallback. Amadeus 미설정이면 Mock 데이터로 대체. 한도 점검 절차는 [FLIGHT_API_SETUP.md §4](FLIGHT_API_SETUP.md#4-serpapi-한도-초과-시-점검-방법) 참조.

**마일리지 선호 항공사 우선 표시**: 여행 정보에 마일리지 프로그램(Skypass, Asiana, Miles & More 등)을 입력하면, 해당 마일리지가 적립되는 항공사 편을 상단에 우선 노출하며 가능한 편은 모두 표시합니다 (스크롤 지원).

**API 키 발급 및 .env 설정** 상세 절차는 [FLIGHT_API_SETUP.md](FLIGHT_API_SETUP.md)를 참조하세요.

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

1. **여행 정보 입력**: 출발지·목적지(공항 코드 또는 도시), 출발일·귀환일(달력 버튼으로 날짜 선택), 일행 구성(남·여·아동), 날짜 유연성(±일), 숙소 선호 3순위, 현지 이동, 좌석 클래스, 마일리지·마일리지 프로그램 등. 도시 입력 시 8시간 이내 공항 선택 단계가 추가됨
2. **다음** → 항공편 선택: **왕복** 시 2a 출국편 → 2b 귀국편 (편도 검색). **편도** 시 1회 선택. **다구간** 시 구간별 순차 선택. 추천순·가격순·비행시간순 정렬
3. **다음** → 렌트카/대중교통: 선택한 현지 이동 수단의 옵션 확인 후 선택
4. **다음** → 일정 선택: 3개 일정안 중 선택 (조기 도착 우선 고려)
5. **다음** → 숙소 선택: 5개 혼합 후보 중 선택 (현지 이동 정보 포함)
6. **일정 확정** → 예약 절차 안내

- 상단 **단계 표시**를 클릭하면 해당 단계로 이동하여 확정된 내용을 확인·수정할 수 있음

**계획 저장·불러오기 (파일처럼 편집)**: 여행 계획은 단계별로 시간이 걸리므로, 상단 **저장** / **다른 이름으로** / **열기** 버튼으로 진행 상황을 저장하고 나중에 다시 불러와 이어서 편집할 수 있습니다. **서버 저장**을 사용하면 사무실·집 등 다른 기기에서 같은 계획을 이어서 편집할 수 있습니다. **열기** 모달에서 **연결 코드**를 확인해 두고, 다른 기기에서는 해당 코드를 입력하면 계획 목록을 불러올 수 있습니다. (나중에 가입·로그인을 붙일 수 있도록 user_id 기반 구조)

---

## 8. 주요 변경 사항 (Changelog)

> 주요 변경 시 이 섹션을 업데이트합니다.

| 날짜 | 변경 내용 |
|------|-----------|
| 2025-03-17 | Amadeus: Skypass/아시아나 시 선호 항공사 전용 검색(includedAirlineCodes) 병합, 대한항공 누락 방지 |
| 2025-03-17 | Amadeus fallback에 날짜 유연성 적용 (여러 날짜쌍 병렬 검색 후 병합) |
| 2025-03-17 | 1단계 편도 전부 0건+SerpAPI 한도 초과 시 2·3단계 생략, 즉시 Amadeus fallback으로 전달 |
| 2025-03-17 | Amadeus fallback: asyncio.run() in running loop 오류 수정 (ThreadPoolExecutor로 별도 스레드에서 실행) |
| 2025-03-17 | SerpApi 429 시 Amadeus fallback 실행 순서 수정 (날짜 유연성 early return보다 먼저). Amadeus 미설정 시 .env 안내 메시지 |
| 2025-03-17 | SerpApi 한도 초과(429) 시 Amadeus API fallback 추가. AMADEUS_CLIENT_ID, AMADEUS_CLIENT_SECRET 설정 시 자동 전환 |
| 2025-03-17 | 항공편 정렬: (원복) 선호 직항→선호 경유→기타 직항→기타 경유, 카테고리 내 비행시간→가격 |
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

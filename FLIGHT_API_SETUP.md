# Flight API 키 발급 및 설정 가이드 (SerpApi → Amadeus → Travelpayouts 참고 → Mock)

항공편 검색은 **`SERPAPI_API_KEY`로 [SerpApi (Google Flights)](https://serpapi.com)** 를 **먼저** 사용합니다. SerpApi 한도 초과(429) 시 **Amadeus**(설정된 경우), **SerpApi·Amadeus 모두 표시할 결과가 없을 때만** `TRAVELPAYOUTS_API_TOKEN`이 있으면 [Travelpayouts Data API](https://api.travelpayouts.com/documentation)(`/v1/prices/cheap`, `/v1/prices/direct`)로 **캐시 기준 최저가·제휴(Aviasales) 링크를 참고**합니다. 그다음 **Mock(예시)** 순입니다.

> 상세 엔드포인트·숙소 API 등은 [docs/TRAVELPAYOUTS_API_GUIDE.md](docs/TRAVELPAYOUTS_API_GUIDE.md) 참고.

---

## 1. Travelpayouts (SerpApi·Amadeus 실패 시 참고, Data API)

### 발급
1. [Travelpayouts](https://travelpayouts.com/) 가입 후 [API 토큰](https://www.travelpayouts.com/programs/100/tools/api) 확인
2. Aviasales 검색 딥링크에 제휴 마커를 붙이려면 대시보드의 **marker**(제휴 ID)를 함께 설정

### `.env`
```env
TRAVELPAYOUTS_API_TOKEN=여기에_토큰
TRAVELPAYOUTS_MARKER=여기에_마커
```

- **MARKER**는 비워도 검색은 되지만, 항공편 카드의 **예약(Aviasales) 링크**가 생성되지 않습니다. 제휴 수익·딥링크를 쓰려면 설정하세요.
- 가격은 API `currency=krw`로 요청하며, 응답 통화가 다르면 표시용 대략 환산합니다. **최종 요금은 예약 사이트에서 확인**하세요.

---

## 2. SerpApi (Google Flights API, 1순위)

### 특징 및 지원 항공사
- **Google Flights** 검색 결과를 그대로 가져오므로, 대한항공, 아시아나항공 등 국적기를 포함한 100% 실제 데이터가 포함됩니다.
- 복잡한 항공사 인증이나 신용카드 등록 없이 이메일 가입만으로 API 키를 바로 발급받을 수 있습니다.

### 요금 구조 (2025년 기준)
| 구분 | 내용 |
|------|------|
| **무료 플랜 (Developer)** | 매월 **250회** 검색 무료 제공 |
| 한도 초과 시 | **Amadeus API**로 자동 fallback (AMADEUS_CLIENT_ID/SECRET 설정 시) |

※ 개발 및 소규모 테스트 목적이라면 무료 250건 한도로 충분합니다. 한도 초과 시 Amadeus API가 설정되어 있으면 실시간 검색이 계속되며, 없으면 Travelpayouts 캐시(토큰 설정 시)·이후 Mock 순으로 대체됩니다.

---

### 2.1 Amadeus API (SerpApi 한도 초과 시 fallback)

### 특징
- SerpApi 429(한도 초과) 응답 시 자동으로 Amadeus Flight Offers Search API를 호출합니다.
- [Amadeus for Developers](https://developers.amadeus.com) 무료 플랜으로 API 키 발급 가능합니다.

### 설정 (선택)
`.env`에 다음 변수를 추가합니다. 비워두면 fallback 시 Amadeus 호출을 건너뛰고 Mock으로 대체됩니다.

```env
AMADEUS_CLIENT_ID=발급받은_API_Key
AMADEUS_CLIENT_SECRET=발급받은_API_Secret
```

### 발급 절차
1. [developers.amadeus.com](https://developers.amadeus.com) 회원가입
2. My Self-Service APIs → Create New App
3. Flight Offers Search API 선택 후 App 생성
4. API Key / API Secret 복사하여 `.env`에 설정

### 429(요청 한도) 대응
- **Test 환경**: 10 TPS. 직항 보강·날짜 유연성 등으로 호출이 많으면 429 발생 가능.
- 대응: 토큰 재사용, 호출 간 250ms 지연, 날짜쌍 8→5 축소 적용.
- 429 시: 잠시 후 재검색하거나, Production API로 전환(40 TPS).

### 테스트 vs 프로덕션 환경
- **테스트(test.api.amadeus.com)**: 무료, **제한된 캐시 데이터**. 노선/항공사에 따라 대한항공·직항 노선이 누락될 수 있음. 직항 전용(nonStop) 검색이 0건이면 메인 검색 결과(직항 포함 가능)를 표시.
- **프로덕션(api.amadeus.com)**: 유료·실시간 전체 데이터. Production API Key 발급 후 사용.

### 대한항공·아시아나(KE, OZ) 보강 (마일리지 계획)
- **SerpApi**: 메인 Google Flights 결과에 KE 또는 OZ 편이 없으면, 동일 조건으로 `include_airlines=KE` / `OZ` 보조 검색을 **추가 호출**해 병합합니다. (노선에 해당 항공사가 없으면 0건 유지.)
- **Amadeus**(SerpApi 429 fallback): **항상** 일반 검색에 더해 `includedAirlineCodes=KE,OZ` 전용 검색을 병합합니다. 마일리지 프로그램이 스카이패스·아시아나가 아닌 경우(예: Miles&More)에는 해당 항공사 코드로 **추가** 전용 검색을 한 번 더 병합합니다.
- UI의 `mileage_eligible` 배지는 KE/OZ 편은 프로그램 미선택이어도 표시됩니다.

---

## 3. SerpApi 키 발급 및 `.env` 설정

### 3.1 가입 및 토큰 발급
1. **[serpapi.com](https://serpapi.com)** 에 접속하여 회원가입(Sign up)합니다.
2. 대시보드(Dashboard)의 **Your Private API Key**에서 발급된 키 문자를 복사합니다.

### 3.2 `.env` 설정
프로젝트 루트 폴더에 `.env` 파일을 열고(없다면 `.env.example`을 복사해 만드세요) 발급받은 API 키를 넣습니다.

```env
# Flight API - SerpApi (Google Flights 검색 지원)
SERPAPI_API_KEY=발급받은_api_key_입력
```

---

## 4. 작동 원리 (SerpApi → Amadeus → Travelpayouts 참고 → Mock)

Trip Agent의 항공편 검색 모듈은 다음 순서로 동작합니다.

1. **SerpApi**: `SERPAPI_API_KEY`로 Google Flights 결과를 조회합니다.
   - **왕복(Round-trip)**: `type=1` (UI상에서는 '가는 편', '오는 편'이 자동으로 분리되어 아코디언 패널에 표시됩니다.)
   - **편도(One-way)**: `type=2` (귀환일 검색 제외)
   - **다구간(Multi-city)**: `type=3` (최대 20개 구간의 출도착지/날짜 파라미터 배열 조합)
   - **날짜 유연성 (Date Flexibility)**: 2단계 검색. 1) 편도 검색으로 출발일±N·귀환일±N 중 가능한 날짜 조합 추출. 2) 추출된 조합별 왕복 검색(`deep_search=true`)으로 Google Flights와 동일한 실제 왕복가 획득. (최대 12쌍 왕복 검색)
   - **대한항공·아시아나 보강**: 메인 결과에 KE 또는 OZ가 없으면 `include_airlines`로 해당 항공사만 추가 검색해 병합합니다. (SerpApi 호출이 0~2회 늘 수 있음.)
   - **왕복 귀국편·출국과 동일 항공사**: 귀국 단계는 편도(`type=2`) 검색입니다. 먼저 SerpApi `include_airlines`로 출국편 편명에서 뽑은 IATA(예: OZ)만 걸어 검색하고, **그 1차 결과가 0건**이면 **필터 없이** 같은 귀환일로 다시 검색합니다. 화면에 뜨는 `[SerpApi·Google Flights] …` 안내는 이 **필터 전후**를 설명하는 것이며, **Amadeus fallback과 무관**합니다(한도 429로 Amadeus가 켜지기 전 단계). **날짜 유연성**: 여행 정보에서 ±N일을 넣으면 귀환일 기준으로 여러 날짜가 병렬 검색되며, 유연성이 **0**이면 **귀환일 하루**만 대상입니다.
   - 디버깅을 위해 `mcp_servers/flight/api_clients.py` 파일 내의 `DEBUG_SERPAPI = True` 플래그를 통해 검색 요청/응답 결과를 터미널에서 확인할 수 있습니다.
2. **Amadeus Fallback**: SerpApi 429(한도 초과) 등 **한도 관련** 응답이 감지되고 `AMADEUS_CLIENT_ID`/`AMADEUS_CLIENT_SECRET`이 설정되어 있으면 Amadeus Flight Offers Search API를 호출합니다. 이때 **일반 검색 + `includedAirlineCodes=KE,OZ` 전용 검색**을 항상 병합합니다.
3. **Travelpayouts (참고)**: SerpApi·Amadeus **모두** 표시할 결과가 없고 `TRAVELPAYOUTS_API_TOKEN`이 있으면 `/v1/prices/cheap`(및 직항 보강용 `/v1/prices/direct`)로 캐시 최저가를 조회합니다. Data API는 문서상 **도시 IATA**를 기대하는 경우가 많아, 입력이 공항 코드(예: ICN→SEL, MXP→MIL)이면 **같은 엔드포인트로 도시 코드 조합을 한 번 더** 시도합니다. 특정 일(yyyy-mm-dd)에 캐시가 없으면 **같은 URL에 출발·귀환을 yyyy-mm(월)**로 한 번 더 묻는 것은 API 관례이며, 그래도 비면 **`/v2/prices/week-matrix`**(`show_to_affiliates=false`)로 주변 날짜 매트릭스를 보조 조회합니다. **Aviasales 검색 링크와 구간 표시용 코드는 사용자가 입력한 공항 코드를 유지**합니다. 이 단계에서 `[Travelpayouts 진단]` 등으로 연결·토큰·캐시 0건이 구분되어 표시될 수 있습니다. `flight_search_api`는 **최종적으로 화면에 쓰인** 소스를 가리킵니다.
4. **Mock 데이터 (최후의 보루)**: 위 단계가 모두 실패하거나 출발일이 너무 멀어 예약 불가 구간이면 Mock 데이터를 표시합니다. (실제 데이터가 하나라도 나온 경우 Mock으로 덮어쓰지 않습니다.)

### 4.1. 흔한 오해: 월(yyyy-mm)까지 했는데 왜 대한항공 등이 “없나”?

Travelpayouts **`/v1/prices/cheap`**(및 일·월 재시도)은 Google Flights처럼 “그 달·그 노선의 **전 항공사**를 조회”하는 API가 **아닙니다**. 문서상으로도 가격은 “**검색 결과에 티켓이 올라온 시점**” 기준이며, **제휴(Aviasales) 쪽에 쌓인 캐시**에서 요청한 출발지·목적지·날짜(또는 월)에 맞는 **저장된 레코드**만 돌려줍니다.

- **`success: true` 인데 `data: {}`** → 그 조건에 맞는 캐시 **행이 한 건도 없다**는 뜻입니다. 실제로 대한항공이 이 구간을 운항해도, 캐시에 해당 조합이 없으면 빈 객체가 나옵니다.
- 월 단위로 넓혀도 마찬가지로 “**그 출발 월·귀환 월에 대한 캐시**”가 없으면 `{}`입니다. “월 검색 = 시장 전체”가 아닙니다.
- v2의 **`/v2/prices/latest`** 는 공식 문서에서 “**가장 최근 48시간** 동안 사용자가 찾은 가격”이라고 명시합니다. 즉 데이터 소스는 **실시간 GDS 전체가 아닙니다**. (`cheap`은 문구는 다르지만 동일하게 **캐시·집계 성격**입니다.)
- **특정 항공사 위주·실시간에 가까운 목록**은 SerpApi·Amadeus 단계를 써야 합니다.

---

## 5. SerpApi 한도 초과 시 점검 방법

검색 결과 대신 **"SerpApi 월 한도(250회) 초과"** 안내가 표시되면 아래 순서로 확인하세요.

### 5.1 대시보드에서 확인
1. [serpapi.com/dashboard](https://serpapi.com/dashboard) 로그인
2. 대시보드에서 **이번 달 사용량**(Searches used)과 **잔여 횟수**(Searches left) 확인
3. 무료 플랜(250회/월) 초과 시: 다음 달 1일 리셋 대기, 또는 유료 플랜 업그레이드

### 5.2 Account API로 조회 (터미널)
API 키로 잔여 횟수를 직접 확인하려면:

```bash
curl "https://serpapi.com/account.json?api_key=YOUR_API_KEY"
```

응답 예시:
```json
{
  "plan_searches_left": 120,
  "this_month_usage": 130,
  "searches_per_month": 250,
  "last_hour_searches": 5,
  "account_rate_limit_per_hour": 50
}
```

| 필드 | 설명 |
|------|------|
| `plan_searches_left` | 이번 달 남은 검색 횟수 |
| `this_month_usage` | 이번 달 사용량 |
| `searches_per_month` | 월 한도 (무료: 250) |
| `last_hour_searches` | 최근 1시간 사용량 |
| `account_rate_limit_per_hour` | 시간당 한도 (초과 시에도 429) |

Account API 호출은 **검색 한도에 포함되지 않음** (무료).

### 5.3 대응 방법
- **월 한도 소진**: 다음 달 1일까지 대기, 또는 [Pricing](https://serpapi.com/pricing)에서 플랜 업그레이드
- **시간당 한도 초과**: 1시간 후 재시도

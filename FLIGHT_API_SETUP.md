# Flight API 키 발급 및 설정 가이드 (SerpApi Google Flights)

항공편 검색에 **SerpApi (Google Flights 연동)**를 사용합니다. 대한항공·아시아나를 포함한 전 세계 주요 항공사의 실제 운항 데이터를 구글 항공권(Google Flights) 검색엔진을 통해 제공받습니다.

> API 키를 설정하지 않거나 무료 한도를 모두 소진하면 자동으로 Playwright 기반 크롤링으로 전환(Fallback)되며, 이마저 실패할 경우 **Mock(예시) 데이터**가 표시됩니다.

---

## 1. SerpApi (Google Flights API) 개요

### 특징 및 지원 항공사
- **Google Flights** 검색 결과를 그대로 가져오므로, 대한항공, 아시아나항공 등 국적기를 포함한 100% 실제 데이터가 포함됩니다.
- 복잡한 항공사 인증이나 신용카드 등록 없이 이메일 가입만으로 API 키를 바로 발급받을 수 있습니다.

### 요금 구조 (2025년 기준)
| 구분 | 내용 |
|------|------|
| **무료 플랜 (Developer)** | 매월 **250회** 검색 무료 제공 |
| 한도 초과 시 | 자동 Playwright 브라우저 크롤링으로 대체 (Trip Agent 내재 기능) |

※ 개발 및 소규모 테스트 목적이라면 무료 250건 한도로 충분하며, 한도 초과 시 내장된 Playwright가 자동으로 작동하여 Google Flights 웹페이지를 긁어오므로 검색이 멈추지 않습니다.

---

## 2. 키 발급 및 `.env` 설정

### 2.1 가입 및 토큰 발급
1. **[serpapi.com](https://serpapi.com)** 에 접속하여 회원가입(Sign up)합니다.
2. 대시보드(Dashboard)의 **Your Private API Key**에서 발급된 키 문자를 복사합니다.

### 2.2 `.env` 설정
프로젝트 루트 폴더에 `.env` 파일을 열고(없다면 `.env.example`을 복사해 만드세요) 발급받은 API 키를 넣습니다.

```env
# Flight API - SerpApi (Google Flights 검색 지원)
SERPAPI_API_KEY=발급받은_api_key_입력
```

---

## 3. 작동 원리 (SerpApi + Play로켓 Fallback)

Trip Agent의 항공편 검색 모듈은 3단계 오케스트레이션으로 작동합니다.

1. **SerpApi 호출**: `SERPAPI_API_KEY`를 이용해 구글 플라이트 결과를 조회합니다.
   - **왕복(Round-trip)**: `type=1` (UI상에서는 '가는 편', '오는 편'이 자동으로 분리되어 아코디언 패널에 표시됩니다.)
   - **편도(One-way)**: `type=2` (귀환일 검색 제외)
   - **다구간(Multi-city)**: `type=3` (최대 20개 구간의 출도착지/날짜 파라미터 배열 조합)
   - **날짜 유연성 (Date Flexibility)**: 사용자가 앱 내에서 "날짜 유연성 (±일)"에 입력한 값(예: 3)에 따라 출발일·귀환일을 ±n일 범위로 여러 날짜 쌍을 병렬 검색한 후 결과를 통합합니다. (최대 5쌍 검색, SerpApi 한도 고려)
   - 디버깅을 위해 `mcp_servers/flight/api_clients.py` 파일 내의 `DEBUG_SERPAPI = True` 플래그를 통해 검색 요청/응답 결과를 터미널에서 확인할 수 있습니다.
2. **Playwright Fallback**: 월 무료 250건 한도를 다 썼거나 SerpApi 쪽에 오류가 나면 사용자 화면에 `SerpApi 무료 한도 초과: Playwright 크롤링으로 전환합니다...`라는 경고를 띄우고, 백그라운드 브라우저(Headless Chrome)를 열어 스크래핑을 시도합니다. 
3. **Mock 데이터 (최후의 보루)**: 위 1, 2번이 모두 실패하거나 출발일이 너무 멀어서 예약 불가능한 기간일 경우 Mock 데이터를 화면에 뿌리고 에러 상황을 우회합니다. (실제 데이터가 단 하나라도 검색 가능한 상황에서는 Mock 데이터가 강제로 주입되지 않습니다.)

---

## 4. SerpApi 한도 초과 시 점검 방법

검색 결과 대신 **"SerpApi 월 한도(250회) 초과"** 안내가 표시되면 아래 순서로 확인하세요.

### 4.1 대시보드에서 확인
1. [serpapi.com/dashboard](https://serpapi.com/dashboard) 로그인
2. 대시보드에서 **이번 달 사용량**(Searches used)과 **잔여 횟수**(Searches left) 확인
3. 무료 플랜(250회/월) 초과 시: 다음 달 1일 리셋 대기, 또는 유료 플랜 업그레이드

### 4.2 Account API로 조회 (터미널)
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

### 4.3 대응 방법
- **월 한도 소진**: 다음 달 1일까지 대기, 또는 [Pricing](https://serpapi.com/pricing)에서 플랜 업그레이드
- **시간당 한도 초과**: 1시간 후 재시도

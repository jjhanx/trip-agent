# Flight API 키 발급 및 설정 가이드

항공편 검색에 사용하는 **Amadeus** API 키 발급 절차와 `.env` 설정 방법을 안내합니다.

> API 키를 설정하지 않으면 **Mock(예시) 데이터**가 표시됩니다. Mock 사용 시 UI에 **"예시(Mock) 데이터입니다"**가 명시되며, 실제 예약·가격과 무관합니다.

**현재 활용 가능한 API**: **Amadeus**만 무료 가입 후 즉시 사용 가능합니다. Kiwi Tequila는 초대제로 전환되었고, RapidAPI Skyscanner는 현재 제공이 중단된 것으로 보입니다.

---

## 1. Amadeus (월 2,000회 무료)

### 1.1 가입 및 앱 생성

1. **[developers.amadeus.com](https://developers.amadeus.com)** 접속
2. **Sign Up** → 이메일·비밀번호로 계정 생성 (이메일 인증)
3. 로그인 후 **"My Self-Service Workspace"** → **"My apps"** → **"Create new app"**
4. 앱 이름 입력 (예: `Trip Agent Dev`) 후 **Create** 클릭
5. **API 선택 체크박스는 없음** — Self-Service 앱은 한 번 생성하면 동일 키로 여러 API 사용 가능

### 1.2 Client ID / Secret 확인

1. 생성된 앱 클릭 → **"App Keys"** 또는 **"API Key"** 탭
2. **API Key** = `AMADEUS_CLIENT_ID`, **API Secret** = `AMADEUS_CLIENT_SECRET`
3. Secret은 한 번만 표시되므로 반드시 복사해 두세요.

### 1.2.1 Credentials 검증 (선택)

Quick Start 예제는 **Flight Inspiration Search** (`/v1/shopping/flight-destinations`)를 사용합니다. 우리 앱은 **Flight Offers Search** (`/v1/shopping/flight-offers`)를 사용합니다. 먼저 credentials가 정상인지 확인하려면:

```bash
# 1. 토큰 발급 (client_id, client_secret을 실제 값으로 교체)
curl "https://test.api.amadeus.com/v1/security/oauth2/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=YOUR_API_KEY&client_secret=YOUR_API_SECRET"

# 응답에 "access_token"이 있으면 성공
```

```bash
# 2. Flight Inspiration Search 호출 (위에서 받은 access_token 사용)
curl 'https://test.api.amadeus.com/v1/shopping/flight-destinations?origin=PAR&maxPrice=200' \
  -H 'Authorization: Bearer 여기에_access_token_붙여넣기'
```

1번에서 토큰을 받으면 credentials는 정상입니다. **단, 토큰 성공 ≠ Flight Offers Search 사용 가능** — §1.6 참조.

### 1.3 API 환경 (Test / Production)

- **신규 가입 시**: 기본으로 **Test 환경** (`test.api.amadeus.com`)만 활성화됨
- **401 인증 실패**가 나면 `.env`에 `AMADEUS_BASE_URL=https://test.api.amadeus.com` 추가 후 재시도
- 프로덕션 승인 후: `AMADEUS_BASE_URL=https://api.amadeus.com` 로 변경 (미설정 시 Test가 기본값)

### 1.4 무료 한도

- 월 **2,000회** Flight Offers Search
- 본 프로젝트의 `usage_tracker`가 한도 도달 시 자동 중단·경고 표시

### 1.5 401 오류 해결

- **자동 재시도**: 401 발생 시 Test↔Production URL을 자동으로 바꿔 한 번 더 시도합니다.
- **확인 사항**:
  1. **§1.2.1** curl로 토큰 발급이 되는지 확인. 성공하면 credentials는 유효함
  2. `.env`에 API Key / Secret 앞뒤 공백·따옴표 없는지 (예: `AMADEUS_CLIENT_ID=abc123` 형태)
  3. Test 환경: `AMADEUS_BASE_URL=https://test.api.amadeus.com` (기본값, 미설정 시 자동)
  4. Production 사용: `AMADEUS_BASE_URL=https://api.amadeus.com` (프로덕션 승인 후)
  5. credentials가 만료·revoke되었다면 Amadeus 대시보드에서 앱을 새로 만들고 새 키로 시도
  6. **서버에서 직접 curl 테스트**: Trip Agent가 돌아가는 Ubuntu 서버에서 §1.2.1 curl을 실행해 보세요. 로컬 PC에서는 되는데 서버에서는 401이면 `.env`가 서버에 제대로 로드되지 않았을 수 있음 (경로·권한·Docker env_file 등)

### 1.6 "no apiproduct match found" 오류

토큰은 받지만 `flight-offers` 호출 시 아래 오류가 나면:

```json
{"fault":{"faultstring":"Invalid API call as no apiproduct match found","detail":{"errorcode":"keymanagement.service.InvalidAPICallAsNoApiProductMatchFound"}}}
```

**원인**: 해당 앱에 **Flight Offers Search** API 제품이 연결되어 있지 않음. (토큰·Flight Inspiration Search는 가능해도 Flight Offers Search는 별도 API 제품)

**대응 방법**:
1. **Trip Agent 자동 대체**: 이 오류 발생 시 **Flight Inspiration Search**로 자동 전환합니다. 목적지·가격 정보만 표시되고 편명은 없습니다. (Mock보다 실제 API 데이터 사용)
2. **새 앱 생성**: My Self-Service → Create new app → 새 앱으로 API Key/Secret 발급. 일부 앱은 Flight Offers Search가 기본 포함될 수 있음
3. **기존 앱 설정 확인**: 해당 앱 → Settings / API Products / Subscriptions 등에서 Flight Offers Search 추가·구독 여부 확인 (UI는 버전에 따라 상이할 수 있음)
4. **Amadeus 지원 문의**: [developers.amadeus.com/support](https://developers.amadeus.com/support) — "Add Flight Offers Search API to my app" 요청

---

## 2. Kiwi Tequila (선택, 초대제)

2024년 이후 Kiwi Tequila는 **초대제 파트너십**으로 전환되었습니다. 일반 가입·로그인이 어렵거나 "Unable to authenticate. Please verify your email" 오류가 발생할 수 있습니다.

- **가입 문의**: affiliates@kiwi.com
- API 키를 이미 보유한 경우 `.env`에 `KIWI_API_KEY` 설정 시 사용됩니다.
- **미사용 가능**: Amadeus만으로도 항공편 검색이 정상 동작합니다.

---

## 3. RapidAPI Skyscanner (제공 중단)

RapidAPI에서 Skyscanner Flight Search API가 **현재 제공되지 않거나 검색되지 않습니다**. 해당 API를 사용할 수 없는 상태입니다.

- `RAPIDAPI_KEY`는 설정하지 않아도 됩니다.
- 향후 RapidAPI에 다른 항공편 API가 추가되면 코드 수정 후 연동 가능합니다.

---

## 4. `.env` 변수 설정

### 4.1 파일 생성

프로젝트 루트에 `.env` 파일이 없다면 `.env.example`을 복사합니다.

```bash
cp .env.example .env
```

### 4.2 Flight API 변수 설정

`.env` 파일을 열고 **Amadeus** credentials를 입력합니다 (가장 확실하게 사용 가능).

```env
# Flight APIs (무료 한도 초과 전 자동 중단)
AMADEUS_CLIENT_ID=여기에_Amadeus_API_Key_붙여넣기
AMADEUS_CLIENT_SECRET=여기에_Amadeus_API_Secret_붙여넣기
# KIWI_API_KEY=  (초대제, 미보유 시 비워둠)
# RAPIDAPI_KEY=  (Skyscanner API 제공 중단, 비워둠)
```

### 4.3 예시 (실제 값은 비공개)

```env
AMADEUS_CLIENT_ID=AbCdEfGhIjKlMnOp
AMADEUS_CLIENT_SECRET=QrStUvWxYz1234567890AbCdEf
```

### 4.4 주의 사항

- `.env`는 **절대 Git에 커밋하지 마세요**. (`.gitignore`에 포함됨)
- **Amadeus만 설정해도** 항공편 검색이 정상 동작합니다. Kiwi/RapidAPI는 선택 사항입니다.

---

## 5. 서버에서 할 일 (배포 시)

### 5.1 환경 변수 전달

- **단일 프로세스 실행**: `main.py` 실행 시 `.env`가 자동 로드됩니다. (`python-dotenv` 사용)
- **Docker Compose**: `docker-compose.yml`의 `env_file: .env` 또는 `environment` 섹션에 변수 지정
- **systemd**: `EnvironmentFile=/path/to/trip-agent/.env` 또는 `Environment=AMADEUS_CLIENT_ID=...` 등으로 설정

### 5.2 확인

1. 서버 재시작 후 항공편 검색 실행
2. **실제 API 결과**가 있으면 항공편 목록에 Mock 배너가 나타나지 않음
3. **API 키 미설정 또는 결과 없음** 시:  
   - UI 상단에 **"예시(Mock) 데이터입니다. 실제 예약·가격과 무관합니다."** 배너 표시
   - `#flight-warnings` 영역에 경고 메시지 (예: "API 키가 설정되지 않았습니다")

---

## 6. 요약 표

| 서비스 | 가입 URL | 발급 항목 | .env 변수 | 비고 |
|--------|----------|-----------|-----------|------|
| **Amadeus** | [developers.amadeus.com](https://developers.amadeus.com) | API Key, API Secret | AMADEUS_CLIENT_ID, AMADEUS_CLIENT_SECRET | **권장** · 월 2,000회 무료 |
| Kiwi Tequila | [tequila.kiwi.com](https://tequila.kiwi.com) | API Key | KIWI_API_KEY | 초대제, 일반 가입 어려움 |
| RapidAPI Skyscanner | — | — | RAPIDAPI_KEY | **제공 중단** (RapidAPI에서 검색 불가) |

---

## 7. Mock 사용 시 동작

- API 키가 없거나, 모든 API가 한도 초과했거나, 실제 검색 결과가 **0건**인 경우
- **Mock(예시) 데이터**로 자동 대체
- 화면에 **"예시(Mock) 데이터입니다. 실제 예약·가격과 무관합니다."** 배너가 반드시 표시됨

# Flight API 키 발급 및 설정 가이드

항공편 검색에 사용하는 **Amadeus** API 키 발급 절차와 `.env` 설정 방법을 안내합니다.

> API 키를 설정하지 않으면 **Mock(예시) 데이터**가 표시됩니다. Mock 사용 시 UI에 **"예시(Mock) 데이터입니다"**가 명시되며, 실제 예약·가격과 무관합니다.

**현재 활용 가능한 API**: **Amadeus**만 무료 가입 후 즉시 사용 가능합니다. Kiwi Tequila는 초대제로 전환되었고, RapidAPI Skyscanner는 현재 제공이 중단된 것으로 보입니다.

---

## 1. Amadeus (월 2,000회 무료)

### 1.1 가입 및 앱 생성

1. **[developers.amadeus.com](https://developers.amadeus.com)** 접속
2. **Sign Up** → 이메일·비밀번호로 계정 생성 (이메일 인증)
3. 로그인 후 상단 **"My Self-Service"** 또는 **"Dashboard"** 클릭
4. **"Create new app"** 선택
5. 앱 정보 입력:
   - **App name**: 예) `Trip Agent Dev`
   - **Description**: 예) `항공편 검색 테스트`
   - **API**: **Flight Create Orders** 또는 **Flight Offers Search** 체크
   - (선택) **Callback URL**: 로컬 개발 시 비워둬도 됨
6. **Create** 클릭

### 1.2 Client ID / Secret 확인

1. 생성된 앱 목록에서 해당 앱 클릭
2. **API Key** 또는 **Credentials** 탭에서:
   - **API Key** = `AMADEUS_CLIENT_ID`
   - **API Secret** = `AMADEUS_CLIENT_SECRET`
3. Secret은 한 번만 표시되므로 반드시 복사해 두세요.

### 1.3 API 환경 (Test / Production)

- **신규 가입 시**: 기본으로 **Test 환경** (`test.api.amadeus.com`)만 활성화됨
- **401 인증 실패**가 나면 `.env`에 `AMADEUS_BASE_URL=https://test.api.amadeus.com` 추가 후 재시도
- 프로덕션 승인 후: `AMADEUS_BASE_URL=https://api.amadeus.com` 로 변경 (미설정 시 Test가 기본값)

### 1.4 무료 한도

- 월 **2,000회** Flight Offers Search
- 본 프로젝트의 `usage_tracker`가 한도 도달 시 자동 중단·경고 표시

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

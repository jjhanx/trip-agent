# Flight API 키 발급 및 설정 가이드

항공편 검색에 사용하는 **flightapi.io**, Kiwi, RapidAPI 키 발급 및 `.env` 설정 방법을 안내합니다.

> API 키를 설정하지 않으면 **Mock(예시) 데이터**가 표시됩니다. Mock 사용 시 UI에 **"예시(Mock) 데이터입니다"**가 명시되며, 실제 예약·가격과 무관합니다.

**현재 활용 가능한 API**: **flightapi.io**가 무료 가입 후 즉시 사용 가능합니다. Kiwi Tequila는 초대제로 전환되었고, RapidAPI 항공편 API는 플랜별로 제공됩니다.

---

## 1. flightapi.io (100회/월 무료, 권장)

### 1.1 가입 및 키 발급

1. **[flightapi.io](https://www.flightapi.io/)** 접속 → Sign Up
2. **Dashboard** → **API Keys** → Create / 복사
3. `.env`에 `FLIGHTAPI_KEY=발급받은키` 추가
4. Round Trip API 사용 (출발지↔도착지 왕복 검색)

### 1.2 무료 한도

- 월 **100회** (프로젝트 `usage_tracker`가 한도 도달 시 자동 중단·경고 표시)

---

## 2. Kiwi Tequila (선택, 초대제)

2024년 이후 Kiwi Tequila는 **초대제 파트너십**으로 전환되었습니다. 일반 가입·로그인이 어렵거나 "Unable to authenticate. Please verify your email" 오류가 발생할 수 있습니다.

- **가입 문의**: affiliates@kiwi.com
- API 키를 이미 보유한 경우 `.env`에 `KIWI_API_KEY` 설정 시 사용됩니다.
- **미보유 시**: flightapi.io만으로도 항공편 검색이 정상 동작합니다.

---

## 3. RapidAPI 항공편 API (대안)

RapidAPI [flight 검색](https://rapidapi.com/search/flight)에서 여러 항공편 API가 있습니다. 각 API는 구독 후 X-RapidAPI-Key로 호출 가능하며, 엔드포인트·파라미터가 API마다 다릅니다.

| API | 무료 한도 | 비고 |
|-----|----------|------|
| [Flight Price Comparison](https://rapidapi.com/manthankool/api/flight-price-comparison) | 100회/월 | flightapi.io와 동일 백엔드 |
| [Compare Flight Prices](https://rapidapi.com/obryan-software-obryan-software-default/api/compare-flight-prices) | 플랜별 | 별도 엔드포인트 |
| [Multi Site Flight Search](https://rapidapi.com/airlineconsolidator/api/multi-site-flight-search) | 플랜별 | |

원하는 RapidAPI 항공 API를 선택한 뒤, 해당 API 문서의 엔드포인트·파라미터에 맞춰 `mcp_servers/flight/api_clients.py`에 클라이언트를 추가할 수 있습니다.

---

## 4. `.env` 변수 설정

### 4.1 파일 생성

프로젝트 루트에 `.env` 파일이 없다면 `.env.example`을 복사합니다.

```bash
cp .env.example .env
```

### 4.2 Flight API 변수 설정

`.env` 파일을 열고 **flightapi.io** 키를 입력합니다.

```env
# Flight APIs (무료 한도 초과 전 자동 중단)
FLIGHTAPI_KEY=여기에_flightapi_키_붙여넣기
# KIWI_API_KEY=  (초대제, 미보유 시 비워둠)
# RAPIDAPI_KEY=  (선택)
```

### 4.3 주의 사항

- `.env`는 **절대 Git에 커밋하지 마세요**. (`.gitignore`에 포함됨)
- **flightapi.io만 설정해도** 항공편 검색이 정상 동작합니다.

---

## 5. 마일리지 선호 항공사 우선 표시

여행 정보에 **마일리지 프로그램**을 입력하면:
- 해당 마일리지가 적립되는 항공사 편을 **우선 상단**에 표시
- 해당 항공사의 가능한 비행편은 모두 노출 (스크롤 지원)
- **지역 목적지**(돌로미티 등) 시: 마일리지 직항 있는 공항(MXP 등)이 **최우선 검색 대상**

예: 돌로미티 + Skypass → ICN-MXP(밀라노, 대한항공 직항) 최우선 노출. MUC, VCE, VRN 등 여러 공항을 직항 우선순으로 검색 후 병합합니다.

지원 프로그램: Skypass(대한항공), Asiana(아시아나), Miles & More(루프트한자·스위스·오스트리아 항공 등)

---

## 6. Mock 사용 시 동작

- API 키가 없거나, 모든 API가 한도 초과했거나, 실제 검색 결과가 **0건**인 경우
- **Mock(예시) 데이터**로 자동 대체
- 화면에 **"예시(Mock) 데이터입니다. 실제 예약·가격과 무관합니다."** 배너가 반드시 표시됨

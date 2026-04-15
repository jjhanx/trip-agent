# Google Places API Key 발급 및 설정 가이드

Trip Agent 플래너에서 명소의 고화질 대표 사진을 가져오기 위해 가장 추천하는 방식은 **Google Places API**를 연동하는 것입니다. API 키를 발급받는 방법은 다음과 같습니다.

## 1. Google Cloud Console 접속 및 프로젝트 생성

1. [Google Cloud Console](https://console.cloud.google.com/)에 접속합니다. (구글 계정 로그인 필요)
2. 상단의 프로젝트 드롭다운을 클릭하고 **[새 프로젝트]**를 생성합니다. (원하는 이름 지정, 예: `trip-agent-places`)

## 2. 결제 계정 연결 (월 $200 무료 크레딧)

Google Maps Platform을 사용하려면 결제 수단을 등록해야 합니다. **안심하세요!**
- Google Maps Platform은 모든 사용자에게 **매월 $200의 무료 크레딧**을 제공합니다.
- 명소 사진 검색(Text Search + Photo)은 건당 약 $0.007 ~ $0.017가 차감되므로, 단순 계산으로도 한 달에 만 건 이상의 사진을 **과금 없이 무료로** 불러올 수 있습니다.
- [결제 설정 페이지]에서 카드 정보를 등록하고 활성화합니다.

## 3. Places API (New) 및 Places API 활성화

1. 좌측 햄버거 메뉴(≡) > **[API 및 서비스]** > **[라이브러리]**로 이동합니다.
2. 검색창에 **Places API**를 검색합니다.
   - `Places API (New)` 또는 `Places API`를 찾아 클릭 후 **[사용]** 버튼을 누릅니다.

## 4. API 키 발급 및 보안 설정

1. 좌측 메뉴의 **[API 및 서비스]** > **[사용자 인증 정보]**로 이동합니다.
2. 상단 **[+ 사용자 인증 정보 만들기]** > **[API 키]**를 클릭하여 키를 생성합니다.
3. **(중요)** 생성된 키를 클릭하여 엽니다.
4. 하단 **API 제한사항**에서 **키 제한**을 선택할 때, 아래를 함께 허용합니다(일정 `parking`의 **거점→명소 주행 분**에 **Directions API**·**Geocoding API**가 필요하고, **숙소 검색**에는 **Distance Matrix API**가 추가로 필요합니다).
   - `Places API` (또는 Places API (New))
   - `Directions API`
   - `Geocoding API`
   - `Distance Matrix API` (숙소~명소 주행 분 합산 — [HOTEL_SEARCH_API.md](HOTEL_SEARCH_API.md))

## 5. `.env` 파일에 적용

발급받은 키(`AIzaSy...` 로 시작하는 문자열)를 복사하여 `trip-agent` 프로젝트 루트의 `.env` 파일에 추가합니다.

```env
# 일정 명소 이미지: 위키·커먼스 등 무료 API 한계 시 Google Places API 사용 (월 $200 무료 제공)
GOOGLE_PLACES_API_KEY=AIzaSy_여기에_복사한_키를_붙여넣으세요
```

이제 서버를 재시작하면, Itinerary Agent가 명소를 추천할 때 이 API를 이용해 고화질 사진·Place Details·좌표를 가져오고, **Directions·Geocoding**이 켜져 있으면 명소 카드 `parking`의 **승용차 ○분**을 지도 도로 기준으로 채웁니다.

## 6. Directions API / Geocoding API (선택이 아님 — 주행 분 자동 입력용)

라이브러리에서 **Directions API**, **Geocoding API**를 각각 검색한 뒤 **[사용]**으로 활성화합니다. 키 제한을 쓰는 경우 위 API들이 허용 목록에 포함되어야 합니다. 과금은 [Maps Platform 가격](https://developers.google.com/maps/billing-and-pricing/pricing)을 참고하세요(무료 크레딧 범위 내 활용 가능).

## 7. 입장료·주차비 (Google 웹 검색 스니펫 — Places API 아님)

Place Details에는 **입장·주차 금액 필드가 없는 경우가 많습니다.** Trip Agent는 입장료를 **Places가 아니라 Google 웹 검색 결과**(검색어: `{이름} 입장료`, `{이름} 주차비`, 이름이 짧으면 목적지 포함)에서 나온 **스니펫**을 모아 LLM이 **입장료·톨·기타** 문단을 씁니다.

**연동 우선순위**

1. **`GOOGLE_CSE_CX`** + **`GOOGLE_PLACES_API_KEY`**(또는 Custom Search용 키): [Google Programmable Search](https://programmablesearchengine.google.com/)에서 검색 엔진을 만들고 `cx`를 복사합니다. Google Cloud에서 **Custom Search API**를 사용(Enabled)으로 켭니다. 무료 일일 쿼터(약 100회)가 있으니 명소 수에 맞게 참고하세요.
2. **`SERPAPI_API_KEY`**만 있는 경우: [SerpApi](https://serpapi.com)의 **`engine=google`**으로 동일하게 Google 검색 결과 페이지를 JSON으로 받습니다(항공·렌트와 동일 키 가능). 명소당 검색 2회가 들어가므로 SerpApi 무료 한도도 참고하세요.

둘 다 **본질적으로 google.com 검색 질의**에 대한 요약·스니펫을 가져오는 방식입니다.

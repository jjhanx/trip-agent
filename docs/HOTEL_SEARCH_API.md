# 숙소 검색 API 설정 (경로 최적화)

숙소 단계에서는 **목(mock) 데이터 대신** 다음이 가능할 때 실제 후보를 씁니다.

1. **Google Maps Platform** — 동일 키로 **Places API**, **Geocoding API**, **Distance Matrix API**를 사용합니다.  
   - **Nearby Search** (`type=lodging`): 일정 명소 좌표의 **중심·반경** 또는 목적지 지오코드 주변의 숙소 후보 수집  
   - **Place Details**: 이름, 주소, 평점, 사진, 구글맵 URL  
   - **Distance Matrix**: 각 숙소에서 일정 **명소 좌표**까지 **승용차(도로) 편도 분** — 합이 작은 순으로 상위 5곳 선정  

2. **Travelpayouts / Hotellook** (선택) — 본 저장소의 숙소 경로는 우선 구글 기반입니다. 캐시 최저가·제휴 링크만 필요하면 [TRAVELPAYOUTS_API_GUIDE.md](TRAVELPAYOUTS_API_GUIDE.md) §4를 참고해 별도 확장할 수 있습니다.

## 필수 환경 변수

| 변수 | 설명 |
|------|------|
| `GOOGLE_PLACES_API_KEY` | Maps Platform API 키 ([발급](GOOGLE_PLACES_API_GUIDE.md)). Hotel MCP 컨테이너/프로세스에도 동일 값 전달 |

## Google Cloud Console에서 켜야 할 API

1. [API 및 서비스 → 라이브러리](https://console.cloud.google.com/apis/library)에서 다음을 **사용**으로 설정합니다.  
   - **Places API** (기존 일정·명소와 동일)  
   - **Geocoding API**  
   - **Directions API** (일정 동선과 동일)  
   - **Distance Matrix API** ← **숙소~명소 주행 분 합산에 필요**  

2. 동일 키의 **API 제한**을 쓰는 경우, 위 API가 허용 목록에 포함되어야 합니다.

## 동작 조건

- 키가 없거나 API 오류 시 → 기존과 같이 **mock** 숙소로 폴백합니다.  
- **명소 카탈로그**(`itinerary_attraction_catalog`)에 `attr_lat` / `attr_lng`가 있고, 일정에 해당 **명소 id**가 있으면 그 좌표들을 사용합니다.  
- 명소 좌표가 없으면 **목적지 문자열 지오코드** 주변으로만 검색하고, 주행 분 합산은 생략합니다.

## 렌트카를 고른 경우

세션은 숙소 단계 응답에서 **`local_transport`를 빈 배열**로 돌려, 렌트카·대중교통 카드를 다시 붙이지 않습니다. 이동 시간은 **숙소 카드 안의 “숙소 → 일정 명소(승용차)”** 블록에만 반영됩니다.

## 과금·한도

- Places Nearby / Details, Distance Matrix, Geocoding 호출이 발생합니다. 월 $200 무료 크레딧 등 [Maps 가격](https://developers.google.com/maps/billing-and-pricing/pricing)을 참고하세요.  
- 명소가 25곳을 넘으면 Distance Matrix 한 요청 제한 때문에 **상위 25곳만** 반영합니다(응답에 안내 문구).

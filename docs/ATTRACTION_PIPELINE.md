# 명소·보강 파이프라인 (요구사항 대응)

이 문서는 “특정 지역만 하드코딩한 명소 목록”이 아니라, **Google Maps / Places를 중심으로 한 일반 파이프라인**과, 그래도 **일부 목적지 문자열에서만** 쓰는 **보조 앵커(선택)**의 역할을 구분해 설명합니다.

## 1. 목적: 어디로 가든 경로·목적지 주변 명소 (구글 평점 중심)

- **지오코딩**: 목적지 문자열(쉼표로 여러 개 가능)을 위도·경도로 바꿉니다. 모호한 문자열(예: 광역 자연권)은 `_patagonia_geocode_query` / `_grand_circle_geocode_query`로 **한 지점으로 고정**해 검색이 엉뚱한 대륙으로 가지 않게 합니다.
- **게이트웨이·루프(기본)**: `shared/route_corridor_places.py` — 목적지를 지오코딩한 뒤 **목적지 중심 근처 공항**(Places Nearby `type=airport`, 실패 시 Text Search 보강) 후보 중 **출발지와 대원거리가 가장 짧은** 좌표를 게이트웨이로 선택합니다(직항 스케줄 API 없이 **지리적 프록시**). **Grand Circle**만 예외적으로 서부 허브(LAX/LAS/PHX/SLC) + 고정 국립공원 루프를 유지합니다. Google **Directions**로 `게이트웨이 → 목적지 문자열들(최대 23개) → 게이트웨이` 루프를 만들고, 각 leg의 step 끝점을 샘플해 그 **도로 주변**에만 Nearby(최대 반경 50km) + Text Search를 돌립니다. 해외 출발지 좌표는 앵커에 넣지 않아 **다른 대륙·도심 전망대 오탐**을 줄입니다.
- **폴백(루프 실패 또는 `GOOGLE_PLACES_API_KEY` 없음)**: 예전과 같이 **목적지 지오코드**만 앵커로 쓰고, 렌트카이며 출발~목적이 **≤ 약 1200km**이면 출발지→목적지 Directions **중간 샘플**을 추가합니다. 대륙 간이면 출발지 경로는 생략합니다.
- **정렬(루프 성공 시)**: 지리 필터 후 **평점·리뷰 수** 내림차순을 한 번 더 적용합니다. 루프가 아닐 때는 `shared/attraction_scenic.py`의 `scenic_rank_bias` 티어 정렬이 우선입니다.

### 왜 “지역별 오프라인 큐레이션”이 아직 있나?

- Places만으로 **목표 개수(일수×3)** 를 항상 채우기 어렵고, **이름만 있는 광역 목적지**는 지오코딩이 한 점에 고정되어 주변 풀이 짧을 수 있습니다.
- `_region_curated_attraction_templates` / `_merge_google_with_region_templates`는 **구글 풀이 부족할 때** 대표 랜드마크가 빠지지 않게 **보충·교체**하는 용도입니다.

### 지리 필터 (`shared/attraction_geo.py`)

- **루프 모드 성공 시**: 앵커는 게이트웨이·루프 샘플·목적지 지점이며, POI는 **어느 앵커에든 직선 약 110km** 이내면 통과합니다.
- **루프 모드가 아닐 때**: **목적지·경로 샘플·(지역 구간일 때) 출발지** 좌표를 앵커로 두고, 상한은 기본 **1000km**, 파타고니아 등 광역 자연권은 **2400km**.

## 2. 거점 도시·승용차 시간 (숙소·일정 참고)

- `shared/directions_parking.py`의 `enrich_attractions_parking_directions`: 명소 좌표 근처 **인구 있는 거점(locality)** 을 Nearby로 고르고, **Directions driving duration**으로 분을 구해 `parking` 한 줄을 채웁니다.
- 구조화 필드: `nearest_hub_display_name`, `drive_minutes_from_nearest_hub` (프론트 명소 카드에도 표시).

## 3. 소개·입장료·케이블카·주차

- `shared/google_place_details.py`: Places **Details**로 주소·웹·리뷰 일부·평점 기반 설명.
- `shared/fees_web_search.py` + `polish_practical_details_with_llm`: **Google 웹 검색 스니펫**(CSE/SerpApi)과 LLM으로 `fees_other`, `cable_car_lift`, `parking` 등을 보강(Places에 없는 입장료·주차 상세).

## 4. 사진 (저작권·품질)

- `shared/place_images.py`: **Wikimedia Commons**·Places Photo(라이선스 조건에 맞는 사용) 등으로 수집, 중복·품질 순 정리.  
  UI 안내: 사용자 리뷰 사진은 API·라이선스 이슈로 자동 수집하지 않음.

## 관련 코드 위치

| 단계 | 주요 모듈 |
|------|-----------|
| Places 수집·필터 | `agents/itinerary/executor.py` → `_fetch_top_attractions_from_google` |
| 게이트웨이·루프 | `shared/route_corridor_places.py` |
| 앵커·거리 상한 | `shared/attraction_geo.py` |
| 거점·주행분 | `shared/directions_parking.py` |
| Details·폴리시 | `shared/google_place_details.py` |
| 이미지 | `shared/place_images.py` |

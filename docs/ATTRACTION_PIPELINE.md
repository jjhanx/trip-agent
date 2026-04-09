# 명소·보강 파이프라인 (요구사항 대응)

이 문서는 “특정 지역만 하드코딩한 명소 목록”이 아니라, **Google Maps / Places를 중심으로 한 일반 파이프라인**과, 그래도 **일부 목적지 문자열에서만** 쓰는 **보조 앵커(선택)**의 역할을 구분해 설명합니다.

## 1. 목적: 어디로 가든 경로·목적지 주변 명소 (구글 평점 중심)

- **지오코딩**: 목적지 문자열(쉼표로 여러 개 가능)을 위도·경도로 바꿉니다. 모호한 문자열(예: 광역 자연권)은 `_patagonia_geocode_query` / `_grand_circle_geocode_query`로 **한 지점으로 고정**해 검색이 엉뚱한 대륙으로 가지 않게 합니다.
- **렌트카 + 지역 구간(출발~목적 대원거리 ≤ 약 1200km)**: Google **Directions**로 출발지→목적지 경로의 **중간 샘플 좌표**를 뽑아, 그 주변에 **Nearby Search**를 돌립니다. (대륙 간 편도는 경로 검색을 끄고 목적지 주변만 검색 — 한국·유럽·미국 POI가 섞이는 문제 방지)
- **목적지 주변**: 동일한 type·keyword 조합으로 **여러 앵커**(목적지 좌표 + 필요 시 추가 시드)에서 Nearby + Text Search.
- **정렬**: `shared/attraction_scenic.py`의 `scenic_rank_bias` 등으로 **국립공원·전망·케이블카**류가 밀리지 않도록 티어·가중치 적용 후 `ingest_pool_tiered`에서 합칩니다.

### 왜 “지역별 오프라인 큐레이션”이 아직 있나?

- Places만으로 **목표 개수(일수×3)** 를 항상 채우기 어렵고, **이름만 있는 광역 목적지**는 지오코딩이 한 점에 고정되어 주변 풀이 짧을 수 있습니다.
- `_region_curated_attraction_templates` / `_merge_google_with_region_templates`는 **구글 풀이 부족할 때** 대표 랜드마크가 빠지지 않게 **보충·교체**하는 용도입니다.

### Grand Circle 전용 (`shared/grand_circle_places.py`)

- 출발지를 지오코딩한 뒤 **LAX / LAS / PHX / SLC** 중 **대원거리가 가장 짧은** 공항을 게이트웨이로 선택합니다.
- Google **Directions**로 게이트웨이 → 그랜드캐년(남림) → 자이언 → 브라이스 → 페이지 → 모뉴먼트 밸리 → 아치스 → 게이트웨이 **루프**를 만들고, 각 leg의 step 끝점을 샘플해 루프 주변에만 **Nearby**(최대 반경 50km) + Text Search.
- POI는 루프 앵커까지 직선 **약 110km** 이내만 남기고, **평점·리뷰 수** 내림차순 정렬합니다.

### 그 외 목적지: 지리 필터 (`shared/attraction_geo.py`)

- **목적지·경로 샘플·(지역 구간일 때) 출발지** 좌표를 **앵커 집합**으로 두고, 각 POI는 **어느 앵커에든 가까우면** 통과합니다. 상한은 기본 **1000km**, 파타고니아 등 광역 자연권은 **2400km**.

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
| 앵커·거리 상한 | `shared/attraction_geo.py` |
| 거점·주행분 | `shared/directions_parking.py` |
| Details·폴리시 | `shared/google_place_details.py` |
| 이미지 | `shared/place_images.py` |

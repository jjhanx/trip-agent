# 명소 카드 이미지와 저작권

## 구글맵 “사진” 탭과의 차이

- 구글맵에 **사용자 리뷰 사진**처럼 보이는 이미지는 **여전히 저작권이 원 게시자·Google 표시 조건**에 있습니다. API 없이 임의로 가져와 서비스에 넣는 것은 **약관·저작권 리스크**가 큽니다.
- **위성/지도 타일**은 앞서 안내한 대로 재배포가 제한됩니다.

## 이 앱에서 쓰는 방식 (실제 장소 위주)

1. **Google Places API** (별도 “Photos API” 상품명은 없음): **Text Search**로 `place_id`를 고른 뒤, 응답에 `photos`가 비어 있어도 **Place Details**(`fields=photos`)로 `photo_reference`를 받고, **Place Photo**(미디어) 요청 URL(`.../place/photo?photoreference=...`)으로 카드에 붙입니다. 명소명에 한글 부제가 있으면 검색·매칭용으로 **라틴 지명 위주로 정리**한 뒤 검색합니다. 매월 제공되는 $200 무료 크레딧 한도 내에서 사용합니다. ([발급 가이드](GOOGLE_PLACES_API_GUIDE.md))
2. **영문·이탈리아어 위키백과** API: 장소명으로 검색해 여러 후보 중 **문서 제목이 명소명과 충분히 겹치는 경우만** 대표 썸네일을 씁니다.
3. **Wikimedia Commons** API: 파일 검색 후 **파일 제목이 명소와 관련되는 경우만** 스케일된 이미지 URL + 라이선스 메타(가능 시). 일부 지역명은 **키워드 고정 썸네일**(Commons URL)로 직접 보강합니다.
4. **(선택)** `.env`에서 `PLACE_IMAGES_USE_SERPAPI=true` 이고 `SERPAPI_API_KEY`가 있으면 **SerpApi Google 이미지 검색**으로 보강합니다. **저작권은 원 게시자**에게 있으며, API 한도가 소모됩니다.
5. 한 명소 목록 안에서는 **이미 쓴 이미지 URL은 다른 카드에 재사용하지 않습니다**(정규화한 키로 중복 제거).
6. 위 과정에서 **확실한 매칭이 없으면** 잘못된 풍경 사진을 넣지 않기 위해 **`image_url`을 비우고**, `image_credit`에 안내 문구를 둡니다. **Unsplash 일반 풍경 폴백은 사용하지 않습니다.** 일정 에이전트는 **`https` 대표 사진이 없는 후보를 목록에서 제외**할 수 있습니다.

구현: `shared/place_images.py` (`enrich_attractions_images`).

## Unsplash

- 프로젝트의 `shared/image_fallbacks.py` 등 **다른 UI**에서 쓸 수 있는 라이선스는 그대로이나, **명소 카드 자동 이미지 파이프라인**에서는 Unsplash로 채우지 않습니다.

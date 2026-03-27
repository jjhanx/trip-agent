# 명소 카드 이미지와 저작권

## 구글맵 “사진” 탭과의 차이

- 구글맵에 **사용자 리뷰 사진**처럼 보이는 이미지는 **여전히 저작권이 원 게시자·Google 표시 조건**에 있습니다. API 없이 임의로 가져와 서비스에 넣는 것은 **약관·저작권 리스크**가 큽니다.
- **위성/지도 타일**은 앞서 안내한 대로 재배포가 제한됩니다.

## 이 앱에서 쓰는 방식 (실제 장소 위주)

1. **영문·이탈리아어 위키백과** API: 장소명으로 검색해 **문서 대표 썸네일**을 씁니다. 유명 관광지는 해당 장소 사진인 경우가 많습니다.
2. **Wikimedia Commons** API: 파일 네임스페이스 검색 후 **스케일된 이미지 URL** + 라이선스 메타(가능 시).
3. **(선택)** `.env`에서 `PLACE_IMAGES_USE_SERPAPI=true` 이고 `SERPAPI_API_KEY`가 있으면 **SerpApi Google 이미지 검색**으로 보강합니다. **저작권은 원 게시자**에게 있으며, API 한도가 소모됩니다.
4. 위가 모두 실패하면 **Unsplash** 풍경 예시(마지막 폴백).

구현: `shared/place_images.py` (`enrich_attractions_images`).

## Unsplash

- [Unsplash License](https://unsplash.com/license): 무료 사용에 가깝게 널리 허용. 폴백은 “풍경 예시”일 수 있음.

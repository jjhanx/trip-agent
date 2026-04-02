"""Google Places Details — 주소·웹·영업시간·리뷰로 practical_details·설명 보강."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx

from urllib.parse import urlencode

logger = logging.getLogger(__name__)

USER_AGENT = (
    "TripAgent/1.0 (https://github.com/jjhanx/trip-agent; place details; contact via repo)"
)

PRACTICAL_DETAIL_KEYS: tuple[str, ...] = (
    "parking",
    "cable_car_lift",
    "walking_hiking",
    "fees_other",
    "reservation_note",
    "tips",
)

# _ensure_attraction_record가 채우는 기본 문구와 동일·유사하면 덮어쓴다.
_PLACEHOLDER_MARKERS = (
    "방문 시즌마다 바뀌므로 현지 공식 안내",
    "예상 도보·트레일 시간과 난이도는 코스 선택에 따라",
    "연도별로 달라질 수 있습니다",
    "케이블카·리프트가 없거나 미이용 시 도보·셔틀만 해당됩니다",
    "성수기·주말에는 주차·입장·보트 등 사전 예약이 필요할 수 있습니다",
    "날씨·일몰 시각·개장 시간을 출발 전에 확인하세요",
    "현지 안내를 확인하세요",
    "명확하게 확인하세요",
    "공식 안내를 확인하세요",
    "미리 확인하세요",
    "출발 전에 확인하세요",
    "제한 구역 주의",
    "사전 확인. 없으면 도보/차량 판단",
    "여유 있게 잡을 것",
    "명확하게 파악",
    "출발 전 확인 권장",
    "혼잡도 회피 계획",
    "명시한다",
    "채운다",
    "요약한다",
    "€ 또는 현지 통화로 명시",
    "예약 경로를 명시",
    "인구 약 3,000명 이상**인 가장 가까운 도시",
    "밝히는 것이 원칙입니다",
    "1000자 전후로 요약해 정리합니다",
    "Places API에는 개별 입장료가 항상 표시되지 않습니다",
    "일정 보강 단계에서 별도로 적",
    "확인하십시오",
    "확인하세요",
    "현지 표지·공식 안내를",
    "지도·현지 표지를",
    "공식 웹에서 요금을",
    "내비 검색어",
)


def _field_needs_replace(val: str) -> bool:
    v = (val or "").strip()
    if not v:
        return True
    return any(m in v for m in _PLACEHOLDER_MARKERS)


def _text_mentions_population_at_least_3000(t: str) -> bool:
    """인구 3천 이상이 한국어·숫자로 드러나는지. '인구' 단어 없이 '5,800명'만 쓴 경우도 인정한다."""
    if not t:
        return False
    if re.search(r"3[.,]?\s*000\s*명\s*이상|3[.,]?\s*천\s*명\s*이상|삼천\s*명\s*이상", t):
        return True
    if re.search(r"\d+(?:\.\d+)?\s*만\s*명", t):
        return True
    segments: list[str] = [t]
    if "인구" in t:
        pos = t.find("인구")
        segments.append(t[pos : pos + 220])
    for segment in segments:
        if re.search(r"3[.,]?\s*000\s*명\s*이상|3[.,]?\s*천\s*명\s*이상|삼천\s*명\s*이상", segment):
            return True
        if re.search(r"\d+(?:\.\d+)?\s*만\s*명", segment):
            return True
        for m in re.finditer(r"([\d][\d.,\s]*)\s*명", segment):
            digits_only = re.sub(r"\D", "", m.group(1))
            if not digits_only:
                continue
            try:
                num = int(digits_only)
            except ValueError:
                continue
            if num >= 3000:
                return True
    # English (모델이 영어로만 쓸 때도 보강 루프가 무한 반복되지 않게)
    if re.search(r"\d+(?:\.\d+)?\s*thousand\s*(?:people|inhabitants)?", t, re.I):
        return True
    for m in re.finditer(r"population\s*(?:of|is|around|approximately|≈|~)?\s*([\d][\d,\s]*)", t, re.I):
        digits_only = re.sub(r"\D", "", m.group(1))
        if digits_only:
            try:
                if int(digits_only) >= 3000:
                    return True
            except ValueError:
                pass
    for m in re.finditer(r"([\d][\d,\s]*)\s*(?:inhabitants|people)\b", t, re.I):
        digits_only = re.sub(r"\D", "", m.group(1))
        if not digits_only:
            continue
        try:
            if int(digits_only) >= 3000:
                return True
        except ValueError:
            continue
    return False


def _text_has_drive_time_minutes(t: str) -> bool:
    """한국어 ○분 또는 영어 min(s)/minutes."""
    if re.search(r"\d+\s*분", t):
        return True
    if re.search(r"\d+\s*(?:min|mins|minutes)\b", t, re.I):
        return True
    return False


def parking_meets_nearest_city_pop3000_and_drive_minutes(text: str) -> bool:
    """주차·도로 문구에 '인구 3천 이상 거점' + '몇 분'이 모두 드러나는지."""
    t = (text or "").strip()
    if len(t) < 20:
        return False
    if not _text_has_drive_time_minutes(t):
        return False
    return _text_mentions_population_at_least_3000(t)


def parking_requires_llm_hub_distance(text: str) -> bool:
    """거점 도시(인구 3천+)·승용차 ○분이 없거나, 내비 검색어만 있는 스텁이면 LLM 보강 필요."""
    t = (text or "").strip()
    if not t:
        return True
    if "내비 검색어" in t or "내비검색어" in t.replace(" ", ""):
        return True
    # Directions API 한 줄 또는 예전 (가)(나) 조합
    if "Google Maps 도로 검색 기준" in t and _text_has_drive_time_minutes(t):
        return False
    if "(가)" in t and "(나)" in t and _text_has_drive_time_minutes(t):
        return False
    if not parking_meets_nearest_city_pop3000_and_drive_minutes(t):
        return True
    return False


def _parse_drive_minutes(val: Any) -> int | None:
    if val is None:
        return None
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        n = int(round(val))
        return n if 1 <= n <= 600 else None
    s = str(val).strip()
    m = re.search(r"(\d+)", s)
    if not m:
        return None
    n = int(m.group(1))
    return n if 1 <= n <= 600 else None


def _population_ko_from_item(it: dict[str, Any]) -> str:
    pk = str(it.get("population_ko") or "").strip()
    if pk:
        return pk
    raw = it.get("population")
    if raw is None:
        return ""
    try:
        n = int(float(str(raw)))
    except (TypeError, ValueError):
        return ""
    return f"약 {n}명"


def _parking_line_from_structured_item(it: dict[str, Any]) -> str:
    """LLM 구조 필드 → 한 줄 고정 형식. 자유 서술에 의존하지 않음."""
    hub = str(it.get("hub_place_name") or it.get("hub_city") or "").strip()
    mins = _parse_drive_minutes(it.get("drive_minutes"))
    extra = str(it.get("parking_and_toll_eur") or "").strip()
    if not hub or mins is None:
        return ""
    pop_show = _population_ko_from_item(it)
    pop_part = f" ({pop_show})" if pop_show else ""
    line = (
        f"{hub}{pop_part}에서 이 명소까지 승용차 약 {mins}분 "
        f"(Google Maps 도로 검색 기준)."
    )
    if extra:
        return f"{line} {extra}".strip()
    return line


def _parking_text_from_mandatory_item(it: dict[str, Any]) -> str:
    line = _parking_line_from_structured_item(it)
    if line:
        return line
    return str(it.get("parking") or "").strip()


def _is_google_stub_description(desc: str) -> bool:
    d = desc or ""
    return "구글맵 기준 평점" in d or "별도로 보강됩니다" in d


async def fetch_place_details_raw(place_id: str, api_key: str) -> dict[str, Any] | None:
    if not place_id or not api_key.strip():
        return None
    fields = (
        "name,geometry,formatted_address,formatted_phone_number,international_phone_number,"
        "website,url,opening_hours,rating,user_ratings_total,types,reviews,editorial_summary"
    )
    url = "https://maps.googleapis.com/maps/api/place/details/json?" + urlencode(
        {"place_id": place_id, "fields": fields, "key": api_key, "language": "ko"}
    )
    try:
        async with httpx.AsyncClient(timeout=18, headers={"User-Agent": USER_AGENT}) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.debug("place details failed: %s", e)
        return None
    if data.get("status") not in ("OK", "ZERO_RESULTS"):
        return None
    return data.get("result") or None


def _editorial_overview(details: dict[str, Any]) -> str:
    es = details.get("editorial_summary")
    if isinstance(es, dict):
        return (es.get("overview") or "").strip()
    return ""


def build_description_from_details(
    name: str,
    destination: str,
    details: dict[str, Any],
) -> str:
    parts: list[str] = []
    ov = _editorial_overview(details)
    if ov:
        parts.append(ov)
    reviews = details.get("reviews") or []
    if not ov and isinstance(reviews, list):
        for r in reviews[:2]:
            if isinstance(r, dict):
                t = (r.get("text") or "").strip()
                if len(t) > 30:
                    parts.append(f"방문자 코멘트 일부: {t[:220]}{'…' if len(t) > 220 else ''}")
                    break
    if not parts:
        parts.append(
            f"{name}은(는) {destination} 일대에서 방문할 만한 지점으로, "
            "아래 링크·실무 정보를 참고해 동선을 잡을 수 있습니다."
        )
    rating = details.get("rating")
    ur = int(details.get("user_ratings_total") or 0)
    if rating is not None:
        parts.append(f"Google Maps 기준 평점 {rating}★(리뷰 약 {ur}건).")
    return " ".join(parts)


def build_practical_from_details(
    name: str,
    destination: str,
    details: dict[str, Any],
) -> dict[str, str]:
    addr = (details.get("formatted_address") or "").strip()
    website = (details.get("website") or "").strip()
    maps_url = (details.get("url") or "").strip()
    phone = (details.get("formatted_phone_number") or details.get("international_phone_number") or "").strip()
    rating = details.get("rating")
    ur = int(details.get("user_ratings_total") or 0)
    oh = details.get("opening_hours") or {}
    weekday_text = oh.get("weekday_text") if isinstance(oh, dict) else None
    hours_line = ""
    if isinstance(weekday_text, list) and weekday_text:
        hours_line = " | ".join(weekday_text[:4])
        if len(weekday_text) > 4:
            hours_line += " …"

    reviews = details.get("reviews") or []
    review_bits: list[str] = []
    if isinstance(reviews, list):
        for r in reviews[:3]:
            if isinstance(r, dict):
                t = (r.get("text") or "").strip()
                if len(t) > 25:
                    review_bits.append(t[:140])

    # Places는 거점·주행분을 주지 않음. parking은 비워 두어 반드시 LLM 보강(인구 3천+ 거점 + 승용차 ○분)이 채우게 함.
    # (내비 검색어만 넣으면 사용자가 일정·숙소 판단 근거를 얻지 못함.)
    parking = ""

    # 케이블·리프트는 확인된 경우에만 표시(프론트는 빈 칸이면 항목 자체를 숨김).
    cable = ""

    walking_parts: list[str] = []
    if review_bits:
        joined = " | ".join(review_bits[:2])
        walking_parts.append(f"방문자 리뷰 발췌: {joined[:280]}{'…' if len(joined) > 280 else ''}")
    if not walking_parts:
        walking_parts.append(
            f"{name} 일대: 코스·난이도·소요 시간은 지형·시즌에 따라 다릅니다. (Places에 상세 코스 미등록)"
        )
    walking = " ".join(walking_parts)

    fees = "Places 응답에 입장료·톨·환경세 금액 필드는 없음."
    if website:
        fees += f" 공식 요금 페이지 URL: {website}"
    else:
        fees += " 공식 웹 URL 미등록(Places)."

    res_parts = []
    if addr:
        res_parts.append(f"등록 주소: {addr}")
    if hours_line:
        res_parts.append(f"개방·운영 시간(Places): {hours_line}")
    if website:
        res_parts.append(f"웹사이트: {website}")
    if maps_url:
        res_parts.append(f"Google Maps: {maps_url}")
    if phone:
        res_parts.append(f"전화: {phone}")
    reservation_note = " | ".join(res_parts) if res_parts else "관련 정보 없음 (Places에 연락·시간 미표시)."

    tips_parts = []
    if rating is not None:
        tips_parts.append(f"Google Maps 평점 {rating}★ · 리뷰 약 {ur}건.")
    tips = " ".join(tips_parts) if tips_parts else "관련 정보 없음 (평점 미표시)."

    return {
        "parking": parking,
        "cable_car_lift": cable,
        "walking_hiking": walking,
        "fees_other": fees,
        "reservation_note": reservation_note,
        "tips": tips,
    }


def _merge_practical(
    existing: dict[str, Any] | None,
    fresh: dict[str, str],
) -> dict[str, str]:
    keys = ("parking", "cable_car_lift", "walking_hiking", "fees_other", "reservation_note", "tips")
    base = {k: "" for k in keys}
    if isinstance(existing, dict):
        for k in keys:
            v = existing.get(k)
            if v is not None and str(v).strip():
                base[k] = str(v).strip()
    for k in keys:
        if _field_needs_replace(base[k]) and fresh.get(k):
            base[k] = fresh[k]
    return base


async def enrich_attractions_with_place_details(
    attractions: list[dict[str, Any]],
    api_key: str,
    destination: str,
) -> list[dict[str, Any]]:
    """place_id가 있으면 Details를 불러와 placeholder practical·stub 설명을 덮어쓴다."""
    if not attractions or not api_key.strip():
        return attractions

    sem = asyncio.Semaphore(8)

    async def one(idx: int) -> tuple[int, dict[str, Any]]:
        a = attractions[idx]
        if not isinstance(a, dict):
            return idx, a
        pid = (a.get("place_id") or "").strip()
        if not pid:
            return idx, a
        async with sem:
            raw = await fetch_place_details_raw(pid, api_key)
        if not raw:
            return idx, a
        item = dict(a)
        name = item.get("name") or raw.get("name") or "명소"
        geom = raw.get("geometry") or {}
        loc = geom.get("location") or {}
        if isinstance(loc.get("lat"), (int, float)) and isinstance(loc.get("lng"), (int, float)):
            item["attr_lat"] = float(loc["lat"])
            item["attr_lng"] = float(loc["lng"])
        fresh_pr = build_practical_from_details(name, destination, raw)
        pr = _merge_practical(item.get("practical_details"), fresh_pr)
        item["practical_details"] = pr
        if _is_google_stub_description(str(item.get("description") or "")):
            item["description"] = build_description_from_details(name, destination, raw)
        item["google_maps_url"] = (raw.get("url") or "").strip()
        item["official_website"] = (raw.get("website") or "").strip()
        return idx, item

    results = await asyncio.gather(*(one(i) for i in range(len(attractions))))
    results.sort(key=lambda x: x[0])
    return [x[1] for x in results]


def _still_placeholder_heavy(pr: dict[str, str]) -> bool:
    n = sum(1 for k in PRACTICAL_DETAIL_KEYS if _field_needs_replace(pr.get(k, "")))
    return n >= 4


def _needs_practical_polish(pr: dict[str, Any]) -> bool:
    """Places·LLM 후에도 너무 짧거나 기본 문구만 남은 경우 추가 보강."""
    if not isinstance(pr, dict):
        return True
    if _still_placeholder_heavy({k: str(pr.get(k) or "") for k in PRACTICAL_DETAIL_KEYS}):
        return True
    pk = str(pr.get("parking") or "")
    walk = str(pr.get("walking_hiking") or "")
    fees = str(pr.get("fees_other") or "")
    resv = str(pr.get("reservation_note") or "")
    if parking_requires_llm_hub_distance(pk):
        return True
    if len(pk.strip()) < 80 or len(walk.strip()) < 400:
        return True
    if len(fees.strip()) < 20 or len(resv.strip()) < 20:
        return True
    return False


async def polish_practical_details_with_llm(
    attractions: list[dict[str, Any]],
    *,
    client: Any,
    model: str,
    destination: str,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    """Places로도 부족한 항목을 LLM으로 보강(일반 지식 허용, 수치는 '참고·확인 필요' 명시)."""
    if not attractions:
        return attractions

    payload = []
    for a in attractions:
        if not isinstance(a, dict):
            continue
        pr = a.get("practical_details") or {}
        need = _needs_practical_polish(pr)
        payload.append(
            {
                "name": a.get("name"),
                "category": a.get("category"),
                "description_excerpt": (a.get("description") or "")[:400],
                "practical_details_before": {k: str(pr.get(k) or "")[:500] for k in PRACTICAL_DETAIL_KEYS},
                "google_maps_url": a.get("google_maps_url") or "",
                "official_website": a.get("official_website") or "",
                "_need_polish": need,
            }
        )

    chunk_size = 12
    out = [dict(x) for x in attractions]

    # 메인 폴리시만 생략 가능. parking 전용 repair/최종 패스는 아래에서 항상 검토한다.
    run_main_polish = any(p.get("_need_polish") for p in payload)

    def _merge_polish_practical(merged: dict[str, str], new_pr: dict[str, Any]) -> None:
        for k in PRACTICAL_DETAIL_KEYS:
            v = new_pr.get(k)
            if k == "cable_car_lift" and v is not None:
                merged[k] = str(v).strip()
                continue
            if v is None or not str(v).strip():
                continue
            nv = str(v).strip()
            old = str(merged.get(k) or "")
            if k == "parking":
                # 검증 통과 여부와 무관하게 비어 있지 않은 새 parking은 신뢰(기존 로직은 '가짜 합격' old 때문에 좋은 nv를 버릴 수 있음)
                if nv:
                    merged[k] = nv
                continue
            if _field_needs_replace(old) or len(old) < 40:
                merged[k] = nv

    if run_main_polish:
        for i in range(0, len(payload), chunk_size):
            chunk = payload[i : i + chunk_size]
            if not any(c.get("_need_polish") for c in chunk):
                continue
            prompt = f"""여행지 실무 카드 작성. 한국어만 사용.

목적지: {destination}
여행 기간: {start_date} ~ {end_date}

**[parking 목적]** 사용자는 **전체 일정·숙소 위치**를 정할 때 **어느 거점 도시를 기준으로 몇 분 거리인지**를 봅니다. **내비에 무엇을 검색할지**만 적는 것은 **실패 응답**이며 금지입니다.

아래 JSON 배열의 각 명소에 대해 `practical_details` 6키를 **판단에 도움이 되게** 채운다.

- parking (**주차·도로**, **모든 명소 필수**): **등록 주소·길찾기 주소 금지**(다른 칸에만). **반드시** ① 명소에서 **가장 가까운 인구 3,000명 이상** 거점(도시·읍·면) **실제 지명** + **인구(명)**. ② 그 거점 **도심·대표 접점**에서 **명소 입구·주차·트레일 헤드**까지 **승용차 약 ○분**(숫자+분). ③ 주차·톨 €. (지명·인구·분이 없으면 안 됨.)
- cable_car_lift: **케이블카·곤돌라·리프트가 실제로 있을 때만** 노선명·대략 요금(€)을 적는다. **없으면 빈 문자열 ""** (항목 미표시). "해당 없음" 문구 금지.
- walking_hiking: 대표 루트·분기·왕복 시간·난이도(쉬움/중간/어려움)·주차/셔틀 지점~트레일 헤드·철제 구간 등을 **약 1000자 전후**로 요약한다. 기존 설명이 길면 **핵심을 빼앗기지 말고** 정리할 것(지나치게 짧게 줄이지 말 것).
- fees_other: **입장료**·환경세·톨·보트 등 **반드시** 수치·통화로 적는다. 미확인 시 "관련 정보 없음".
- reservation_note: **개방·운영 시간**(요일별 가능 시), **예약 필수 여부**, 예약 경로·전화·링크.
- tips: 최적 시간대·준비물·혼잡

금지: "확인하세요", "확인하십시오", "권장합니다", "현지 예약 사이트 참고", "달라질 수 있습니다", "…을 확인하" 등 **사용자에게 가서 확인하라는** 표현. 반드시 **조사한 결과**(€·분·도시명·시간)를 문장으로 적는다.
**절대 금지**: 프롬프트에 나온 지시문을 그대로 출력(예: "…명시한다", "…채운다", "…원칙입니다", "…정리합니다"). 실제 **도시명·인구·€·분·주차 요금**만 적는다.
허용: 지역 일반 지식을 총동원하여 정확한 답변 작성. 확인 불가 시 차라리 "관련 정보 없음"이라고 명시.

입력:
{json.dumps(chunk, ensure_ascii=False)}

출력: JSON 객체 하나만.
{{ "items": [ {{ "name": "...", "practical_details": {{ ...6키... }} }} ] }}
이름은 입력과 동일하게 유지한다."""

            try:
                resp = await client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = resp.choices[0].message.content or ""
                parsed = _extract_json_object(text)
                items = (parsed or {}).get("items") or []
                items_list = [it for it in items if isinstance(it, dict)]
                by_name = {str(it.get("name") or "").strip(): it for it in items_list}
                chunk_len = len(chunk)
                for j in range(chunk_len):
                    idx = i + j
                    if idx >= len(out):
                        break
                    a = out[idx]
                    if not isinstance(a, dict):
                        continue
                    upd = None
                    if j < len(items_list):
                        upd = items_list[j]
                    if upd is None:
                        upd = by_name.get(str(a.get("name") or "").strip())
                    if not upd:
                        continue
                    new_pr = upd.get("practical_details")
                    if not isinstance(new_pr, dict):
                        continue
                    merged = dict(a.get("practical_details") or {})
                    _merge_polish_practical(merged, new_pr)
                    a["practical_details"] = merged
            except Exception as e:
                logger.warning("polish_practical_llm chunk failed: %s", e)

    # 전 명소 대상 parking 강제 채움: 거점 도시 + 승용차 ○분이 모든 카드에 들어가도록 단일 패스(청크)
    rows: list[dict[str, Any]] = []
    for idx, a in enumerate(out):
        if not isinstance(a, dict):
            continue
        rows.append(
            {
                "idx": idx,
                "name": a.get("name") or "",
                "existing_parking": str((a.get("practical_details") or {}).get("parking") or "")[:700],
                "google_maps_url": (a.get("google_maps_url") or "")[:220],
            }
        )
    if rows:
        mandatory_chunk = 8
        for c0 in range(0, len(rows), mandatory_chunk):
            chunk = rows[c0 : c0 + mandatory_chunk]
            mand_prompt = f"""목적지: {destination}
여행 기간: {start_date} ~ {end_date}

**역할**: 각 명소에 대해 **필드만** 채운다. **문장을 직접 쓰지 말고** 아래 JSON 키만 채운다. 서버가 `○○에서 이 명소까지 승용차 약 N분 (Google Maps 도로 검색 기준).` 형식으로 합친다.

**각 item 필수 키** (문자열은 한국어 위주):
- `idx`: 입력과 동일한 정수
- `hub_place_name`: 이 명소에 가장 가까운 **인구 3,000명 이상**인 거점의 **실제 지명**(도시·읍·면, 현지명도 가능)
- `population_ko`: 인구 표기. 예: `약 5,800명` (또는 숫자로 `population` 키에 5800)
- `drive_minutes`: **정수** — 그 거점 **도심**에서 이 명소 **입구·주차·트레일 헤드**까지 **승용차**로 **몇 분**인지 (1~600)
- `parking_and_toll_eur`: 주차·톨 € 등 **한 문장** (숫자·€ 포함)

**금지**: 내비 검색어만, 등록 주소만 복사, 빈 문자열로 두기.

입력:
{json.dumps(chunk, ensure_ascii=False)}

출력: JSON 객체 `{{"items":[...]}}` — `items` 길이는 **정확히 {len(chunk)}**개. 각 원소는 위 키를 모두 포함. `parking` 문자열은 **쓰지 않아도 됨**(서버가 조합)."""

            try:
                try:
                    resp = await client.chat.completions.create(
                        model=model,
                        messages=[{"role": "user", "content": mand_prompt}],
                        response_format={"type": "json_object"},
                    )
                except Exception:
                    resp = await client.chat.completions.create(
                        model=model,
                        messages=[{"role": "user", "content": mand_prompt}],
                    )
                text = resp.choices[0].message.content or ""
                parsed_m = _extract_json_object(text)
                items_m = (parsed_m or {}).get("items") or []
                for it in items_m:
                    if not isinstance(it, dict):
                        continue
                    try:
                        idx = int(it.get("idx", -1))
                    except (TypeError, ValueError):
                        continue
                    if idx < 0 or idx >= len(out):
                        continue
                    pk_new = _parking_text_from_mandatory_item(it)
                    if not pk_new:
                        continue
                    a = out[idx]
                    if not isinstance(a, dict):
                        continue
                    merged = dict(a.get("practical_details") or {})
                    merged["parking"] = pk_new
                    a["practical_details"] = merged
            except Exception as e:
                logger.warning("parking mandatory all-chunk failed: %s", e)

        # 강제 패스 후에도 미달이면 1회 재시도(실패한 idx만)
        retry_idx = [
            idx
            for idx, a in enumerate(out)
            if isinstance(a, dict)
            and parking_requires_llm_hub_distance(str((a.get("practical_details") or {}).get("parking") or ""))
        ]
        if retry_idx:
            chunk_r = [
                {
                    "idx": i,
                    "name": out[i].get("name") or "",
                    "existing_parking": str((out[i].get("practical_details") or {}).get("parking") or "")[:700],
                    "google_maps_url": (out[i].get("google_maps_url") or "")[:220],
                }
                for i in retry_idx
            ]
            mand_prompt2 = f"""목적지: {destination}
여행 기간: {start_date} ~ {end_date}

이전 응답이 규칙을 지키지 못했다. **다시** 각 명소에 대해 **필드만** 채운다.

필수 키(각 item): `idx`, `hub_place_name`, `population_ko` 또는 숫자 `population`, 정수 `drive_minutes`, `parking_and_toll_eur`.

입력:
{json.dumps(chunk_r, ensure_ascii=False)}

출력 JSON: {{"items":[...]}} — items는 **{len(chunk_r)}**개. 각 원소에 위 키 필수."""

            try:
                try:
                    resp2 = await client.chat.completions.create(
                        model=model,
                        messages=[{"role": "user", "content": mand_prompt2}],
                        response_format={"type": "json_object"},
                    )
                except Exception:
                    resp2 = await client.chat.completions.create(
                        model=model,
                        messages=[{"role": "user", "content": mand_prompt2}],
                    )
                text2 = resp2.choices[0].message.content or ""
                parsed_r = _extract_json_object(text2)
                for it in (parsed_r or {}).get("items") or []:
                    if not isinstance(it, dict):
                        continue
                    try:
                        idx = int(it.get("idx", -1))
                    except (TypeError, ValueError):
                        continue
                    if idx < 0 or idx >= len(out):
                        continue
                    pk_new = _parking_text_from_mandatory_item(it)
                    if not pk_new:
                        continue
                    a = out[idx]
                    if not isinstance(a, dict):
                        continue
                    merged = dict(a.get("practical_details") or {})
                    merged["parking"] = pk_new
                    a["practical_details"] = merged
            except Exception as e:
                logger.warning("parking mandatory retry failed: %s", e)

    return out


def _extract_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    t = text.strip()
    if "```" in t:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", t)
        if m:
            t = m.group(1).strip()
    s = t.find("{")
    e = t.rfind("}")
    if s < 0 or e <= s:
        return None
    try:
        return json.loads(t[s : e + 1])
    except json.JSONDecodeError:
        return None

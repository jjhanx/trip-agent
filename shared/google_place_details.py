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
)


def _field_needs_replace(val: str) -> bool:
    v = (val or "").strip()
    if not v:
        return True
    return any(m in v for m in _PLACEHOLDER_MARKERS)


def _is_google_stub_description(desc: str) -> bool:
    d = desc or ""
    return "구글맵 기준 평점" in d or "별도로 보강됩니다" in d


async def fetch_place_details_raw(place_id: str, api_key: str) -> dict[str, Any] | None:
    if not place_id or not api_key.strip():
        return None
    fields = (
        "name,formatted_address,formatted_phone_number,international_phone_number,"
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
            "아래 주소·링크·실무 정보를 참고해 동선을 잡을 수 있습니다."
        )
    addr = (details.get("formatted_address") or "").strip()
    if addr:
        parts.append(f"등록 주소: {addr}.")
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
    types = list(details.get("types") or [])
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

    type_set = set(types)
    is_nature = bool(type_set.intersection({"natural_feature", "park", "campground"}))

    parking_lines = []
    if addr:
        parking_lines.append(f"Google Places 등록 주소: {addr}.")
    parking_lines.append(
        f"차량 접근 시 내비·지도에서 '{name}' 또는 위 주소로 검색하고, "
        "주차장·톨·일방통행·환경 보호구역 통행 제한은 시즌·이벤트에 따라 바뀔 수 있습니다."
    )
    if is_nature:
        parking_lines.append(
            "자연·공원·계곡 구간은 주차장에서 트레일 헤드까지 도보·셔틀이 붙는 경우가 많습니다."
        )
    if website:
        parking_lines.append(f"공식·지자체 안내는 웹사이트를 우선 확인: {website}")
    parking = " ".join(parking_lines)

    if is_nature:
        cable = (
            "케이블카·리프트는 이 장소 유형상 필수는 아닙니다. "
            "인근 리프트·곤돌라를 쓰는 동선이면 별도로 역·요금을 확인하세요. 없으면 '해당 없음'으로 계획."
        )
    else:
        cable = (
            "등록 정보상 케이블카·리프트는 별도 확인이 필요합니다. "
            "없으면 도보·셔틀·버스만 고려하면 됩니다."
        )

    walking = (
        f"{name} 일대는 지형·코스에 따라 왕복 30분~수시간까지 달라질 수 있습니다. "
        "난이도·표고차·적설 여부는 지도·현지 표지·산악 지도로 확인하세요."
    )
    if review_bits:
        joined = " | ".join(review_bits)
        walking += f" 방문자 언급 참고: {joined[:320]}{'…' if len(joined) > 320 else ''}"

    fees = (
        "Places API에는 개별 입장료가 항상 표시되지 않습니다. "
        "자연 보호지역·톨·보트·박물관 등은 별도 요금이 붙을 수 있으니 공식 요금표를 확인하세요."
    )
    if website:
        fees += f" ({website})"

    res_parts = []
    if website:
        res_parts.append(f"웹사이트: {website}")
    if maps_url:
        res_parts.append(f"Google Maps 링크: {maps_url}")
    if phone:
        res_parts.append(f"전화: {phone}")
    reservation_note = " | ".join(res_parts)

    tips_parts = []
    if hours_line:
        tips_parts.append(f"영업·운영 시간(표시 시): {hours_line}")
    if rating is not None:
        tips_parts.append(f"평점 {rating}★ · 리뷰 약 {ur}건(참고용).")
    tips_parts.append("날씨·도로 통제·일몰 시각은 출발 전에 다시 확인하세요.")
    tips = " ".join(tips_parts)

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
    if len(pk.strip()) < 50 or len(walk.strip()) < 50:
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

    if not any(p.get("_need_polish") for p in payload):
        return out

    for i in range(0, len(payload), chunk_size):
        chunk = payload[i : i + chunk_size]
        if not any(c.get("_need_polish") for c in chunk):
            continue
        prompt = f"""여행지 실무 카드 작성. 한국어만 사용.

목적지: {destination}
여행 기간: {start_date} ~ {end_date}

아래 JSON 배열의 각 명소에 대해 `practical_details` 6키를 **판단에 도움이 되게** 채운다.
- parking: 구체적 지명·주차 구역·톨·도로 통제 가능성(€ 대략이 알려져 있으면 숫자, 불확실하면 '수십 유로대·시즌별' 등)
- cable_car_lift: 있으면 노선·대략 €, 없으면 명확히 '해당 없음' 또는 인근만 언급
- walking_hiking: 대표 루트·왕복 시간·난이도(쉬움/중간/어려움), 주차지~트레일 헤드 포함
- fees_other: 입장·톨·보트 등 알려진 범위
- reservation_note: 예약 링크·전화·필수 여부
- tips: 최적 시간대·준비물·혼잡

금지: "현지 공식 안내만 확인"만 단독으로 쓰기, 의미 없는 메타 문구.
허용: 지역 일반 지식(돌로미티·알프스 등) + 아래에 붙은 웹·설명 요약. 불확실하면 반드시 '출발 전 공식 사이트 확인'을 곁들인다.

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
            by_name = {str(it.get("name") or "").strip(): it for it in items if isinstance(it, dict)}
            for j, a in enumerate(out):
                if not isinstance(a, dict):
                    continue
                nm = str(a.get("name") or "").strip()
                upd = by_name.get(nm)
                if not upd:
                    continue
                new_pr = upd.get("practical_details")
                if not isinstance(new_pr, dict):
                    continue
                merged = dict(a.get("practical_details") or {})
                for k in PRACTICAL_DETAIL_KEYS:
                    v = new_pr.get(k)
                    if v is None or not str(v).strip():
                        continue
                    old = str(merged.get(k) or "")
                    if _field_needs_replace(old) or len(old) < 40:
                        merged[k] = str(v).strip()
                a["practical_details"] = merged
        except Exception as e:
            logger.debug("polish_practical_llm failed: %s", e)

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

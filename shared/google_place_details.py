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

    # 사용자에게는 사실만. LLM 프롬프트 문구(인구 3천·원칙 등)는 넣지 않는다 — polish 단계에서 수치를 채운다.
    parking_lines = []
    if addr:
        parking_lines.append(f"등록 주소: {addr}")
    parking_lines.append(
        f"내비·지도 검색: 「{name}」 또는 위 주소."
    )
    if is_nature:
        parking_lines.append("자연·공원 구간은 주차장에서 트레일까지 도보·셔틀이 이어지는 경우가 많습니다.")
    if website:
        parking_lines.append(f"공식 안내: {website}")
    parking = " ".join(parking_lines) + " 주차 요금·톨·거리는 현지 표지·공식 안내를 확인하십시오."

    # 케이블·리프트는 확인된 경우에만 표시(프론트는 빈 칸이면 항목 자체를 숨김).
    cable = ""

    walking_parts: list[str] = [
        f"{name} 일대 코스·난이도·소요 시간은 지형·시즌에 따라 다릅니다. 지도·현지 표지를 확인하십시오."
    ]
    if review_bits:
        joined = " | ".join(review_bits[:2])
        walking_parts.append(f"방문자 리뷰 발췌: {joined[:280]}{'…' if len(joined) > 280 else ''}")
    walking = " ".join(walking_parts)

    fees = "Places에 등록된 입장료·톨·환경세 금액은 없습니다."
    if website:
        fees += f" 공식 요금은 {website}에서 확인하십시오."
    else:
        fees += " 공식 웹에서 요금을 확인하십시오."

    res_parts = []
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
    tips_parts.append("날씨·도로 통제·일몰 시각은 출발 전에 확인하십시오.")
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
    fees = str(pr.get("fees_other") or "")
    resv = str(pr.get("reservation_note") or "")
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

- parking (**주차·도로 접근**): **구체적 도시(또는 읍·면) 이름**을 쓴 뒤, 그곳이 **인구 약 3,000명 이상**임을 한 문장으로 밝히고, **그 도심·대표 접점 → 명소 입구(또는 주차장·트레일 헤드)**까지 **승용차로 몇 분**을 숫자로 적는다. **주차 요금**(€/시간·일당)·주차장명·유료 여부·톨을 함께 적는다.
- cable_car_lift: **케이블카·곤돌라·리프트가 실제로 있을 때만** 노선명·대략 요금(€)을 적는다. **없으면 빈 문자열 ""** (항목 미표시). "해당 없음" 문구 금지.
- walking_hiking: 대표 루트·분기·왕복 시간·난이도(쉬움/중간/어려움)·주차/셔틀 지점~트레일 헤드·철제 구간 등을 **약 1000자 전후**로 요약한다. 기존 설명이 길면 **핵심을 빼앗기지 말고** 정리할 것(지나치게 짧게 줄이지 말 것).
- fees_other: **입장료**·환경세·톨·보트 등 **반드시** 수치·통화로 적는다. 미확인 시 "관련 정보 없음".
- reservation_note: **개방·운영 시간**(요일별 가능 시), **예약 필수 여부**, 예약 경로·전화·링크.
- tips: 최적 시간대·준비물·혼잡

금지: "확인하세요", "권장합니다", "현지 예약 사이트 참고", "달라질 수 있습니다" 등 답변을 회피하거나 떠넘기는 문구 절대 금지. 직접 조사한 구체적인 요금, 시간, 소요시간(숫자)을 기재할 것.
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
                    if k == "cable_car_lift" and v is not None:
                        merged[k] = str(v).strip()
                        continue
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

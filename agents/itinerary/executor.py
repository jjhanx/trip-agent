"""Itinerary Planner Agent — 명소 후보 → 경로·동네·맛집 → 식사 선택 → 최종 일정."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any

from a2a.server.agent_execution import RequestContext
from a2a.server.events import EventQueue

from agents.base_agent import BaseAgentExecutor
from config import Settings
from shared.utils import new_agent_text_message


def _trip_inclusive_days(start_date: str, end_date: str) -> int:
    d1 = datetime.strptime(start_date[:10], "%Y-%m-%d").date()
    d2 = datetime.strptime(end_date[:10], "%Y-%m-%d").date()
    return max(1, (d2 - d1).days + 1)


def _date_list(start_date: str, end_date: str) -> list[str]:
    d1 = datetime.strptime(start_date[:10], "%Y-%m-%d").date()
    d2 = datetime.strptime(end_date[:10], "%Y-%m-%d").date()
    out: list[str] = []
    cur = d1
    while cur <= d2:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def _extract_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    t = text.strip()
    if "```" in t:
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", t)
        if m:
            t = m.group(1).strip()
    start = t.find("{")
    end = t.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(t[start : end + 1])
    except json.JSONDecodeError:
        return None


def _mock_attractions(destination: str, trip_days: int, preference: dict) -> dict[str, Any]:
    n = min(trip_days * 3, 42)
    cats = ["문화·역사", "자연·전망", "체험·시장", "미술·건축", "야경·산책"]
    attractions = []
    for i in range(n):
        attractions.append(
            {
                "id": f"attr_{i+1:03d}",
                "name": f"{destination} 추천 명소 {i + 1}",
                "description": f"{cats[i % len(cats)]} 성격의 방문지입니다. 동선과 체류 시간을 고려해 선택하세요.",
                "category": cats[i % len(cats)],
            }
        )
    return {
        "itinerary_step": "select_attractions",
        "trip_days": trip_days,
        "time_ratio_note": (
            "이상적인 여행에서는 공항↔목적지 이동과 목적지 체류 시간 비율이 대략 4:1이 되도록 "
            "이동·관광을 배분하는 것을 권장합니다. 실제 항공·도로 상황에 맞게 조정하세요."
        ),
        "attractions": attractions,
        "design_notes": (
            f"{destination} 일정: 오전·오후로 하루 약 두 곳을 기준으로 명소를 고르고, "
            "숙소에서 차로 1시간을 넘기는 경우 동선상 숙소 이동을 검토하되 한 곳 거점은 최대한 유지하세요."
        ),
    }


def _mock_route_and_restaurants(
    destination: str,
    trip_days: int,
    dates: list[str],
    selected: list[dict[str, Any]],
    preference: dict,
) -> dict[str, Any]:
    ids = [a["id"] for a in selected]
    daily_schedule = []
    for i, d in enumerate(dates):
        am = ids[(i * 2) % len(ids)] if ids else "attr_001"
        pm = ids[(i * 2 + 1) % len(ids)] if len(ids) > 1 else am
        daily_schedule.append(
            {
                "date": d,
                "morning_attraction_id": am,
                "afternoon_attraction_id": pm,
                "overnight_area_hint": f"{destination} 중심부 또는 인접 동네",
            }
        )
    restaurants_by_attraction: dict[str, list[dict[str, Any]]] = {}
    for a in selected:
        aid = a["id"]
        restaurants_by_attraction[aid] = [
            {
                "id": f"{aid}_r1",
                "name": f"{a['name']} 근처 맛집 A",
                "rating": 4.6,
                "description": "현지인 단골, 점심·저녁 모두 가능.",
            },
            {
                "id": f"{aid}_r2",
                "name": f"{a['name']} 근처 맛집 B",
                "rating": 4.4,
                "description": "평점 좋은 브런치·라이트 저녁.",
            },
            {
                "id": f"{aid}_r3",
                "name": f"{a['name']} 근처 맛집 C",
                "rating": 4.2,
                "description": "가성비 좋은 현지 요리.",
            },
        ]
    return {
        "itinerary_step": "select_meals",
        "route_plan": {
            "destination_base_days": dates,
            "transit_legs": [
                {
                    "leg": "outbound",
                    "notes": "공항에서 목적지로 이동하는 동선에 볼거리가 있으면 하루 묵고 가는 형태로 넣을 수 있습니다.",
                    "suggested_overnight": None,
                    "sights_along_route": [],
                },
                {
                    "leg": "return",
                    "notes": "귀국 시에도 중간 도시에 중요한 관광지가 있으면 경유·숙박을 고려하세요.",
                    "suggested_overnight": None,
                    "sights_along_route": [],
                },
            ],
            "daily_schedule": daily_schedule,
            "lodging_strategy": (
                "가능하면 목적지 주변 한 거점에 머물고, 차로 1시간 초과 구간이 반복되면 동네 이동을 검토합니다."
            ),
        },
        "neighborhoods": [
            {
                "area_id": "nb_1",
                "name": f"{destination} 시내·중심가",
                "description": "교통·식사 접근성이 좋고 주요 명소와의 이동이 수월한 동네입니다.",
                "reachable_attraction_ids": ids[: min(8, len(ids))],
                "lodging_notes": "첫 숙박 후보로 적합합니다.",
            },
            {
                "area_id": "nb_2",
                "name": f"{destination} 인근 조용한 주거·관광지 일대",
                "description": "붐비는 시내를 피하고 싶을 때, 렌트 이용 시 주차 여유가 있는 편입니다.",
                "reachable_attraction_ids": ids[min(4, len(ids) - 1) :] if len(ids) > 4 else ids,
                "lodging_notes": "장기 체류·가족 여행에 맞출 수 있습니다.",
            },
        ],
        "restaurants_by_attraction": restaurants_by_attraction,
        "trip_dates": dates,
    }


def _resolve_restaurant_name(
    rid: str,
    restaurants_by_attraction: dict[str, list[dict[str, Any]]],
) -> str:
    for _aid, lst in restaurants_by_attraction.items():
        for r in lst:
            if r.get("id") == rid:
                return r.get("name") or rid
    return rid


def _finalize_merge(
    destination: str,
    route_bundle: dict[str, Any],
    meal_choices: dict[str, Any],
) -> dict[str, Any]:
    route_plan = route_bundle.get("route_plan") or {}
    restaurants_by_attraction = route_bundle.get("restaurants_by_attraction") or {}
    dates = route_bundle.get("trip_dates") or []
    daily_plan = []
    for d in dates:
        day_meals = meal_choices.get(d) or {}
        lunch = day_meals.get("lunch") or {}
        dinner = day_meals.get("dinner") or {}
        lunch_first = lunch.get("first")
        lunch_second = lunch.get("second")
        dinner_first = dinner.get("first")
        dinner_second = dinner.get("second")
        ds = next(
            (x for x in (route_plan.get("daily_schedule") or []) if x.get("date") == d),
            {},
        )
        daily_plan.append(
            {
                "date": d,
                "morning_attraction_id": ds.get("morning_attraction_id"),
                "afternoon_attraction_id": ds.get("afternoon_attraction_id"),
                "lunch": {
                    "first_choice_id": lunch_first,
                    "first_choice_name": _resolve_restaurant_name(
                        lunch_first, restaurants_by_attraction
                    )
                    if lunch_first
                    else None,
                    "second_choice_id": lunch_second,
                    "second_choice_name": _resolve_restaurant_name(
                        lunch_second, restaurants_by_attraction
                    )
                    if lunch_second
                    else None,
                },
                "dinner": {
                    "first_choice_id": dinner_first,
                    "first_choice_name": _resolve_restaurant_name(
                        dinner_first, restaurants_by_attraction
                    )
                    if dinner_first
                    else None,
                    "second_choice_id": dinner_second,
                    "second_choice_name": _resolve_restaurant_name(
                        dinner_second, restaurants_by_attraction
                    )
                    if dinner_second
                    else None,
                },
            }
        )
    return {
        "itinerary_step": "complete",
        "final_itinerary": {
            "title": f"{destination} 맞춤 일정",
            "summary": (
                f"{destination} 일정: 선택한 명소·동선·맛집 우선순위를 반영했습니다. "
                "숙소는 다음 단계에서 예약합니다."
            ),
            "route_plan": route_plan,
            "neighborhoods": route_bundle.get("neighborhoods") or [],
            "daily_plan": daily_plan,
            "meal_choices_raw": meal_choices,
        },
    }


class ItineraryPlannerExecutor(BaseAgentExecutor):
    """다단계 일정: 명소 후보 → 경로·맛집 → 식사 선택 → 완료."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()

    async def execute(
        self,
        context: RequestContext,
        event_queue: EventQueue,
    ) -> None:
        user_input = context.get_user_input()
        if not user_input:
            await event_queue.enqueue_event(new_agent_text_message("입력이 없습니다."))
            return
        try:
            data = json.loads(user_input)
        except Exception as e:
            await event_queue.enqueue_event(new_agent_text_message(f"입력 오류: {e}"))
            return

        destination = data.get("destination", "")
        start_date = data.get("start_date", "")
        end_date = data.get("end_date", "")
        preference = data.get("preference") or {}
        selected_flight = data.get("selected_flight") or {}
        phase = (data.get("itinerary_phase") or "attractions").strip().lower()

        trip_days = _trip_inclusive_days(start_date, end_date)
        dates = _date_list(start_date, end_date)

        if phase == "attractions":
            out = _mock_attractions(destination, trip_days, preference)
            if self.settings.openai_api_key:
                try:
                    from openai import AsyncOpenAI

                    client = AsyncOpenAI(
                        api_key=self.settings.openai_api_key,
                        base_url=self.settings.openai_base_url,
                    )
                    prompt = f"""당신은 여행 일정 설계 전문가입니다.
- 목적지 주변 명소 관광에 전체 체류의 대략 1/4를 할애한다고 가정하고, 하루는 오전·오후 두 번 방문으로 계획할 수 있게 후보를 낸다.
- 공항↔목적지 이동과 현지 체류의 균형(이상적 비율 약 4:1)을 안내 문구에 반영한다.

목적지: {destination}
여행 일수(포함): {trip_days}일
취향: {json.dumps(preference, ensure_ascii=False)}
선택 항공: {json.dumps(selected_flight, ensure_ascii=False)}

JSON 객체 하나만 출력:
- itinerary_step: "select_attractions"
- trip_days: {trip_days}
- time_ratio_note: 한국어
- attractions: 정확히 {min(trip_days * 3, 42)}개 배열. 각 항목: id(attr_001부터), name, description, category
- design_notes: 한국어"""
                    resp = await client.chat.completions.create(
                        model=self.settings.llm_model,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    content = resp.choices[0].message.content or ""
                    parsed = _extract_json_object(content)
                    if parsed and parsed.get("itinerary_step") == "select_attractions":
                        ats = parsed.get("attractions")
                        if isinstance(ats, list) and len(ats) >= 3:
                            out = parsed
                            out["trip_days"] = trip_days
                except Exception:
                    pass
            await event_queue.enqueue_event(
                new_agent_text_message(json.dumps(out, ensure_ascii=False))
            )
            return

        if phase == "route_restaurants":
            catalog = data.get("itinerary_attraction_catalog")
            selected_ids = data.get("selected_attraction_ids") or []
            if not isinstance(catalog, list):
                catalog = []
            id_set = {a.get("id") for a in catalog if isinstance(a, dict)}
            selected_objs = [a for a in catalog if isinstance(a, dict) and a.get("id") in selected_ids]
            if not selected_objs:
                for sid in selected_ids:
                    if sid in id_set:
                        selected_objs.append(next(x for x in catalog if x.get("id") == sid))
            if not selected_objs:
                await event_queue.enqueue_event(
                    new_agent_text_message(
                        json.dumps(
                            {
                                "error": "선택한 명소가 없습니다. 최소 한 곳 이상 선택해 주세요.",
                            },
                            ensure_ascii=False,
                        )
                    )
                )
                return
            out = _mock_route_and_restaurants(
                destination, trip_days, dates, selected_objs, preference
            )
            if self.settings.openai_api_key:
                try:
                    from openai import AsyncOpenAI

                    client = AsyncOpenAI(
                        api_key=self.settings.openai_api_key,
                        base_url=self.settings.openai_base_url,
                    )
                    prompt = f"""여행 일정 2단계. 한국어 JSON만 출력.

목적지: {destination}
일수: {trip_days}, 날짜 목록: {json.dumps(dates, ensure_ascii=False)}
선택된 명소: {json.dumps(selected_objs, ensure_ascii=False)}
취향: {json.dumps(preference, ensure_ascii=False)}
항공: {json.dumps(selected_flight, ensure_ascii=False)}

요구:
1) 동선을 고려해 일자별 오전·오후 명소 id를 배정. 숙소에서 차로 1시간 초과 거리면 숙소 이동을 검토하되 한 거점 유지를 우선.
2) 목적지 주변 추천 동네(숙소 후보 지역) 2~4개: area_id, name, description, reachable_attraction_ids, lodging_notes.
3) 공항↔목적지 구간에 볼거리가 있으면 transit_legs에 leg(outbound|return), notes, suggested_overnight(도시명 또는 null), sights_along_route(짧은 배열).
4) 각 선택 명소마다 식당 3곳: rating 내림차순, id는 고유문자열, description 짧게.

출력 JSON 키:
- itinerary_step: "select_meals"
- route_plan: daily_schedule( date, morning_attraction_id, afternoon_attraction_id, overnight_area_hint ), transit_legs, lodging_strategy, destination_base_days
- neighborhoods: 배열
- restaurants_by_attraction: 객체, 키는 명소 id, 값은 길이 3 배열 {{id,name,rating,description}}
- trip_dates: {json.dumps(dates, ensure_ascii=False)}"""
                    resp = await client.chat.completions.create(
                        model=self.settings.llm_model,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    content = resp.choices[0].message.content or ""
                    parsed = _extract_json_object(content)
                    if (
                        parsed
                        and parsed.get("itinerary_step") == "select_meals"
                        and isinstance(parsed.get("restaurants_by_attraction"), dict)
                    ):
                        parsed["trip_dates"] = dates
                        out = parsed
                except Exception:
                    pass
            await event_queue.enqueue_event(
                new_agent_text_message(json.dumps(out, ensure_ascii=False))
            )
            return

        if phase == "finalize":
            meal_choices = data.get("meal_choices") or {}
            route_bundle = data.get("route_plan_bundle") or {}
            if not isinstance(meal_choices, dict):
                meal_choices = {}
            out = _finalize_merge(destination, route_bundle, meal_choices)
            if self.settings.openai_api_key:
                try:
                    from openai import AsyncOpenAI

                    client = AsyncOpenAI(
                        api_key=self.settings.openai_api_key,
                        base_url=self.settings.openai_base_url,
                    )
                    prompt = f"""아래 데이터로 여행 일정 최종 요약을 한국어로 다듬는다. JSON만 출력.

목적지: {destination}
route_plan_bundle: {json.dumps(route_bundle, ensure_ascii=False)[:12000]}
meal_choices: {json.dumps(meal_choices, ensure_ascii=False)}

출력:
{{"itinerary_step":"complete","final_itinerary":{{"title","summary","route_plan","neighborhoods","daily_plan"(날짜별 점심·저녁 식당 이름 포함), "meal_choices_raw"}}}}"""
                    resp = await client.chat.completions.create(
                        model=self.settings.llm_model,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    content = resp.choices[0].message.content or ""
                    parsed = _extract_json_object(content)
                    if parsed and parsed.get("itinerary_step") == "complete":
                        out = parsed
                except Exception:
                    pass
            await event_queue.enqueue_event(
                new_agent_text_message(json.dumps(out, ensure_ascii=False))
            )
            return

        await event_queue.enqueue_event(
            new_agent_text_message(
                json.dumps({"error": f"알 수 없는 itinerary_phase: {phase}"}, ensure_ascii=False)
            )
        )

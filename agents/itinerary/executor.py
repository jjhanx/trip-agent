"""Itinerary Planner Agent - 선택된 항공편과 취향에 따른 일정 3안 설계."""

import json

from a2a.server.agent_execution import RequestContext
from a2a.server.events import EventQueue

from agents.base_agent import BaseAgentExecutor
from config import Settings
from shared.utils import new_agent_text_message


def _mock_itineraries(destination: str, days: int, preference: dict) -> list[dict]:
    """Generate 3 mock itinerary options."""
    return [
        {
            "option_id": "IT1",
            "title": "문화 탐방 코스",
            "summary": f"{destination}의 주요 문화유적과 박물관 중심 일정",
            "daily_activities": [
                {"date": "Day1", "title": "도착 및 시내 관광", "description": "공항 도착 후 시내 투어"},
                {"date": "Day2", "title": "박물관 관람", "description": "주요 박물관 관람"},
                {"date": f"Day{days}", "title": "마지막 쇼핑 및 귀국", "description": "기념품 쇼핑 후 공항 이동"},
            ],
            "accommodation_nights": [["Day1", destination], ["Day2", destination]],
        },
        {
            "option_id": "IT2",
            "title": "휴양 & 힐링 코스",
            "summary": f"{destination}에서 여유로운 휴양 중심",
            "daily_activities": [
                {"date": "Day1", "title": "호텔 체크인 및 휴식", "description": "도착 후 호텔에서 휴식"},
                {"date": "Day2", "title": "스파 & 웰니스", "description": "스파 이용"},
                {"date": f"Day{days}", "title": "귀국 준비", "description": "체크아웃 후 공항 이동"},
            ],
            "accommodation_nights": [["Day1", destination], ["Day2", destination]],
        },
        {
            "option_id": "IT3",
            "title": "액티브 어드벤처 코스",
            "summary": f"{destination}의 액티비티와 체험 중심",
            "daily_activities": [
                {"date": "Day1", "title": "도착 및 현지 투어", "description": " half-day 투어"},
                {"date": "Day2", "title": "액티비티 데이", "description": "트레킹/워터스포츠 등"},
                {"date": f"Day{days}", "title": "마무리 및 귀국", "description": "마지막 관광 후 귀국"},
            ],
            "accommodation_nights": [["Day1", destination], ["Day2", destination]],
        },
    ]


class ItineraryPlannerExecutor(BaseAgentExecutor):
    """Itinerary Planner Agent - designs 3 itinerary options."""

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
            destination = data.get("destination", "")
            start_date = data.get("start_date", "")
            end_date = data.get("end_date", "")
            preference = data.get("preference", {})
            selected_flight = data.get("selected_flight", {})
        except Exception as e:
            await event_queue.enqueue_event(new_agent_text_message(f"입력 오류: {e}"))
            return
        from datetime import datetime

        d1 = datetime.strptime(start_date, "%Y-%m-%d")
        d2 = datetime.strptime(end_date, "%Y-%m-%d")
        days = max(1, (d2 - d1).days)
        itineraries = _mock_itineraries(destination, days, preference)
        if self.settings.openai_api_key:
            try:
                from openai import AsyncOpenAI

                client = AsyncOpenAI(
                    api_key=self.settings.openai_api_key,
                    base_url=self.settings.openai_base_url,
                )
                prompt = f"""Create 3 travel itinerary options for {destination}, {days} days.
User preference: {json.dumps(preference)}
Selected flight: {json.dumps(selected_flight)}
Return JSON array with 3 objects, each with: option_id, title, summary, daily_activities (list of {{date, title, description}}), accommodation_nights (list of [date, location])."""
                resp = await client.chat.completions.create(
                    model=self.settings.llm_model,
                    messages=[{"role": "user", "content": prompt}],
                )
                content = resp.choices[0].message.content or ""
                if "[" in content:
                    start = content.index("[")
                    end = content.rindex("]") + 1
                    itineraries = json.loads(content[start:end])
            except Exception:
                pass
        await event_queue.enqueue_event(
            new_agent_text_message(json.dumps(itineraries, ensure_ascii=False))
        )

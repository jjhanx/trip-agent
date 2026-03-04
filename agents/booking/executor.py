"""Booking Orchestrator Agent - 일정 확정 및 예약 안내."""

import json

from a2a.server.agent_execution import RequestContext
from a2a.server.events import EventQueue

from agents.base_agent import BaseAgentExecutor
from shared.utils import new_agent_text_message


class BookingOrchestratorExecutor(BaseAgentExecutor):
    """Booking Orchestrator Agent - confirms itinerary and provides booking guidance."""

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
            confirmed_itinerary = data.get("confirmed_itinerary", {})
            selected_flight = data.get("selected_flight", {})
            selected_accommodation = data.get("selected_accommodation", {})
        except Exception as e:
            await event_queue.enqueue_event(new_agent_text_message(f"입력 오류: {e}"))
            return
        guidance = {
            "status": "confirmed",
            "summary": "일정이 확정되었습니다. 아래 순서로 예약을 진행해 주세요.",
            "steps": [
                {
                    "order": 1,
                    "item": "항공편",
                    "details": selected_flight,
                    "action": "해당 항공사 사이트 또는 여행사에서 예약",
                },
                {
                    "order": 2,
                    "item": "숙소",
                    "details": selected_accommodation,
                    "action": "해당 숙소 사이트에서 예약",
                },
                {
                    "order": 3,
                    "item": "일정",
                    "details": confirmed_itinerary,
                    "action": "일정표 저장 및 현지 교통권/패스 준비",
                },
            ],
        }
        await event_queue.enqueue_event(
            new_agent_text_message(json.dumps(guidance, ensure_ascii=False))
        )

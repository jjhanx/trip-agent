"""Public Transit Agent - 대중교통 검색."""

import json

from a2a.server.agent_execution import RequestContext
from a2a.server.events import EventQueue

from agents.base_agent import BaseAgentExecutor
from config import Settings
from shared.utils import MCPClient, new_agent_text_message


def _merge_transit_routes_and_passes(
    routes: list,
    passes: list,
    location_label: str,
) -> list:
    """MCP search_routes 결과 + get_transit_passes 를 UI 한 목록으로 병합."""
    out = list(routes) if isinstance(routes, list) else []
    if not isinstance(passes, list):
        return out
    for i, p in enumerate(passes):
        if not isinstance(p, dict):
            continue
        name = p.get("name") or "교통패스"
        out.append({
            "route_id": p.get("route_id") or f"PASS-{i + 1}",
            "description": f"{location_label}: {name} ({p.get('duration_days', 1)}일)",
            "duration_minutes": None,
            "pass_name": name,
            "pass_price_krw": p.get("price_krw"),
        })
    return out


class PublicTransitExecutor(BaseAgentExecutor):
    """Public Transit Agent - Transit MCP (노선 검색 + 체류일 맞춤 패스)."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.mcp = MCPClient(self.settings.transit_mcp_url)

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
            origin = (data.get("transit_origin") or data.get("origin") or "").strip()
            destination = (data.get("transit_destination") or data.get("destination") or "").strip()
            date_time = (data.get("date_time") or "").strip()
            trip_days = int(data.get("trip_days") or data.get("duration_days") or 1)
            trip_days = max(1, min(trip_days, 30))
            pass_days = max(1, min(trip_days, 14))
        except Exception as e:
            await event_queue.enqueue_event(new_agent_text_message(f"입력 오류: {e}"))
            return
        routes: list = []
        passes: list = []
        try:
            r1 = await self.mcp.call_tool(
                "search_routes",
                {
                    "origin": origin,
                    "destination": destination,
                    "date_time": date_time,
                    "trip_days": trip_days,
                },
            )
            text = r1.get("text", json.dumps(r1))
            routes = json.loads(text) if isinstance(text, str) else text
            if not isinstance(routes, list):
                routes = []
        except Exception:
            routes = []

        try:
            r2 = await self.mcp.call_tool(
                "get_transit_passes",
                {
                    "location": destination or origin,
                    "duration_days": pass_days,
                },
            )
            text2 = r2.get("text", json.dumps(r2))
            passes = json.loads(text2) if isinstance(text2, str) else text2
            if not isinstance(passes, list):
                passes = []
        except Exception:
            passes = []

        if not routes and not passes:
            routes = [
                {
                    "route_id": "TR001",
                    "description": "Metro + Bus (참고)",
                    "duration_minutes": 40,
                },
                {
                    "route_id": "TR002",
                    "description": "직행 버스 (참고)",
                    "duration_minutes": 55,
                    "pass_name": "시티패스 1일",
                    "pass_price_krw": 15000,
                },
            ]

        merged = _merge_transit_routes_and_passes(
            routes,
            passes,
            destination or origin or "현지",
        )
        await event_queue.enqueue_event(
            new_agent_text_message(json.dumps(merged, ensure_ascii=False))
        )

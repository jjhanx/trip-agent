"""Configuration for trip-agent."""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # .env에 과거 변수(amadeus_*)가 남아 있어도 무시
    )

    # OpenAI / LLM
    openai_api_key: str = ""
    openai_base_url: str | None = None  # For OpenRouter etc.
    llm_model: str = "gpt-4o-mini"

    # MCP server URLs (when running as separate processes)
    flight_mcp_url: str = "http://localhost:8001/mcp"
    hotel_mcp_url: str = "http://localhost:8002/mcp"
    rental_car_mcp_url: str = "http://localhost:8003/mcp"
    transit_mcp_url: str = "http://localhost:8004/mcp"

    # Flight API - Travelpayouts Data API (SerpApi·Amadeus 실패 시 캐시 참고). Aviasales 제휴 예약 링크용 marker
    travelpayouts_api_token: str = ""
    travelpayouts_marker: str = ""
    # 렌트카: Travelpayouts 대시보드 Link Generator로 만든 제휴 URL (선택, 설정 시 검색 결과 최상단)
    travelpayouts_rental_booking_url: str = ""

    # Flight API - SerpApi (Google Flights, Travelpayouts 결과 없을 때)
    serpapi_api_key: str = ""
    # 일정 명소 이미지: 위키·커먼스 등 무료 API 한계 시 Google Places API 사용 (월 $200 무료 제공)
    google_places_api_key: str = ""
    # Google Programmable Search (Custom Search JSON API) — 입장·주차 웹 검색 스니펫용 cx. 콘솔에서 Custom Search API 사용 설정
    google_cse_cx: str = ""
    # 일정 명소 이미지: 위키·커먼스 실패 후 SerpApi Google 이미지 검색 사용(선택, API 한도·저작권 유의)
    place_images_use_serpapi: bool = False
    # Flight API - Amadeus (SerpApi 한도 초과 시 fallback)
    amadeus_client_id: str = ""
    amadeus_client_secret: str = ""

    # A2A agent URLs (for Session Agent to call other agents)
    flight_agent_url: str = "http://localhost:9001"
    itinerary_agent_url: str = "http://localhost:9002"
    accommodation_agent_url: str = "http://localhost:9003"
    rental_car_agent_url: str = "http://localhost:9004"
    transit_agent_url: str = "http://localhost:9005"
    booking_agent_url: str = "http://localhost:9006"

    # Session → 다른 A2A 에이전트 HTTP 타임아웃(초). 일정(itinerary)은 Places·LLM·이미지로 수 분 걸릴 수 있음.
    a2a_timeout_seconds: float = 120.0
    a2a_itinerary_timeout_seconds: float = 600.0

    @field_validator("place_images_use_serpapi", mode="before")
    @classmethod
    def _parse_place_images_serpapi(cls, v: object) -> bool:
        if isinstance(v, bool):
            return v
        if v is None or v == "":
            return False
        return str(v).strip().lower() in ("1", "true", "yes", "on")

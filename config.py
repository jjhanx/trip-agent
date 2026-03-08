"""Configuration for trip-agent."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # OpenAI / LLM
    openai_api_key: str = ""
    openai_base_url: str | None = None  # For OpenRouter etc.
    llm_model: str = "gpt-4o-mini"

    # MCP server URLs (when running as separate processes)
    flight_mcp_url: str = "http://localhost:8001/mcp"
    hotel_mcp_url: str = "http://localhost:8002/mcp"
    rental_car_mcp_url: str = "http://localhost:8003/mcp"
    transit_mcp_url: str = "http://localhost:8004/mcp"

    # Flight API keys (Amadeus, Kiwi Tequila, RapidAPI Skyscanner) - 무료 한도 관리
    amadeus_client_id: str = ""
    amadeus_client_secret: str = ""
    kiwi_api_key: str = ""
    rapidapi_key: str = ""

    # A2A agent URLs (for Session Agent to call other agents)
    flight_agent_url: str = "http://localhost:9001"
    itinerary_agent_url: str = "http://localhost:9002"
    accommodation_agent_url: str = "http://localhost:9003"
    rental_car_agent_url: str = "http://localhost:9004"
    transit_agent_url: str = "http://localhost:9005"
    booking_agent_url: str = "http://localhost:9006"

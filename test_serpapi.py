import os
import asyncio
from dotenv import load_dotenv

load_dotenv("g:/내 드라이브/trip-agent/.env")
api_key = os.environ.get("SERPAPI_API_KEY")

if not api_key:
    print("NO API KEY")
    exit(1)

from mcp_servers.flight.api_clients import search_serpapi_flights

async def test():
    flights, warnings = await search_serpapi_flights(
        origin="ICN",
        destination="NRT",
        start_date="2026-05-10",
        end_date="2026-05-15",
        api_key=api_key
    )
    print("Flights count:", len(flights))
    print("Warnings:", warnings)

if __name__ == "__main__":
    asyncio.run(test())

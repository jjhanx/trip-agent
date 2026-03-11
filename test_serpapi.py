import asyncio
import json
from mcp_servers.flight.api_clients import GoogleSearch
import os
from dotenv import load_dotenv

async def main():
    load_dotenv()
    api_key = os.getenv("SERPAPI_API_KEY")
    # Docker passenv might not be loaded by dotenv properly if it's fed via compose
    if not api_key:
        api_key = os.environ.get("SERPAPI_API_KEY")

    if not api_key:
        print("NO API KEY")
        return
        
    params = {
      "engine": "google_flights",
      "currency": "KRW",
      "hl": "ko",
      "api_key": api_key,
      "travel_class": 1,
      "type": "1",
      "departure_id": "ICN",
      "arrival_id": "MXP",
      "outbound_date": "2026-06-25",
      "return_date": "2026-07-15"
    }

    loop = asyncio.get_running_loop()
    def _run_search():
        search = GoogleSearch(params)
        return search.get_dict()

    try:
        results = await loop.run_in_executor(None, _run_search)
        
        best = results.get("best_flights", [])
        if best:
            print("BEST FLIGHTS [0]:")
            print(json.dumps(best[0], indent=2, ensure_ascii=False))
        else:
            print("NO BEST FLIGHTS")
    except Exception as e:
        print(e)

if __name__ == "__main__":
    asyncio.run(main())

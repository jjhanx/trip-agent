import os
import json
from google_search_results import GoogleSearch

def test_round_trip():
    api_key = os.environ.get("SERPAPI_API_KEY", "")
    if not api_key:
        print("No API KEY")
        return
    
    params = {
        "engine": "google_flights",
        "hl": "ko",
        "currency": "KRW",
        "departure_id": "ICN",
        "arrival_id": "NRT",
        "outbound_date": "2026-06-25",
        "return_date": "2026-07-15",
        "type": "1", # round trip
        "api_key": api_key
    }
    
    search = GoogleSearch(params)
    results = search.get_dict()
    
    with open("serpapi_dump.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print("Dumped to serpapi_dump.json")

if __name__ == "__main__":
    test_round_trip()

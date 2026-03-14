import os
import json
import urllib.request
import urllib.parse

def test_round_trip():
    api_key = os.environ.get("SERPAPI_API_KEY", "")
    if not api_key:
        print("No API KEY")
        return
    
    params = {
        "engine": "google_flights",
        "hl": "ko",
        "gl": "kr",
        "currency": "KRW",
        "departure_id": "ICN",
        "arrival_id": "MXP",
        "outbound_date": "2026-06-24",
        "return_date": "2026-07-15",
        "type": "1", # round trip
        "api_key": api_key
    }
    
    query = urllib.parse.urlencode(params)
    url = f"https://serpapi.com/search.json?{query}"
    
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req) as response:
            results = json.loads(response.read().decode("utf-8"))
            with open("serpapi_dump_mxp.json", "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print("Dumped to serpapi_dump_mxp.json")
    except Exception as e:
        print(f"Error fetching: {e}")

if __name__ == "__main__":
    test_round_trip()

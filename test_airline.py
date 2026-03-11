from mcp_servers.flight.services import _is_preferred_airline, _get_preferred_airlines

def test():
    pref = _get_preferred_airlines("대한항공")
    print("Preferred:", pref)
    
    # Test a direct flight
    flight1 = {"airline": "Korean Air", "flight_number": "KE 901"}
    print("KE flight match:", _is_preferred_airline(flight1, pref))
    
    # Test a flight parsed with "Multiple (2 stops)" flight number
    flight2 = {"airline": "Korean Air", "flight_number": "Multiple (2 stops)"}
    print("KE multi flight match:", _is_preferred_airline(flight2, pref))
    
    # Test a flight parsed with "KoreanAir" space removed
    flight3 = {"airline": "KoreanAir", "flight_number": "Multiple (2 stops)"}
    print("KE no_space match:", _is_preferred_airline(flight3, pref))

if __name__ == "__main__":
    test()

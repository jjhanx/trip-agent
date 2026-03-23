from mcp_servers.flight.services import (
    _flight_includes_carrier,
    _get_preferred_airlines,
    _is_preferred_airline,
    _mileage_eligible_for_flight,
)


def test():
    pref = _get_preferred_airlines("대한항공")
    print("Preferred:", pref)

    flight1 = {"airline": "Korean Air", "flight_number": "KE 901"}
    print("KE flight match:", _is_preferred_airline(flight1, pref))
    assert _flight_includes_carrier(flight1, "KE")
    assert _mileage_eligible_for_flight(flight1, frozenset())

    flight2 = {"airline": "Korean Air", "flight_number": "Multiple (2 stops)"}
    print("KE multi flight match:", _is_preferred_airline(flight2, pref))

    flight3 = {"airline": "KoreanAir", "flight_number": "Multiple (2 stops)"}
    print("KE no_space match:", _is_preferred_airline(flight3, pref))

    oz = {"airline": "Asiana", "flight_number": "OZ123", "departure": "2025-06-01T10:00:00"}
    assert _flight_includes_carrier(oz, "OZ")
    assert _mileage_eligible_for_flight(oz, frozenset())

    lh = {"airline": "Lufthansa", "flight_number": "LH400", "departure": "2025-06-01T10:00:00"}
    assert not _mileage_eligible_for_flight(lh, frozenset())
    assert _mileage_eligible_for_flight(lh, _get_preferred_airlines("milesandmore"))


if __name__ == "__main__":
    test()

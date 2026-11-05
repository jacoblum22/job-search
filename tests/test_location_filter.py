from src.location_filter import classify_location, is_remote, is_vancouver_area


def test_metro_municipalities():
    assert is_vancouver_area("Burnaby, BC")
    assert is_vancouver_area("Richmond, British Columbia")
    assert classify_location("Surrey, BC") == "vancouver"


def test_victoria_is_not_vancouver():
    assert classify_location("Victoria, BC", "BCAA") == "other"


def test_remote_canada_and_bare_canada():
    assert is_remote("Remote - Canada")
    assert is_remote("Canada")
    assert classify_location("Canada") == "remote"


def test_remote_united_states_kept():
    assert is_remote("Remote (United States)")
    assert classify_location("Remote - USA") == "remote"


def test_remote_elsewhere_rejected():
    assert not is_remote("Remote - India")
    assert classify_location("Remote (United Kingdom)") == "other"


def test_company_fallback_city_of_vancouver():
    assert (
        classify_location("LOC0049 Brookside Utilities Building", "City of Vancouver")
        == "vancouver"
    )


def test_same_named_cities_elsewhere_are_not_vancouver():
    assert classify_location("Richmond, VA") == "other"
    assert classify_location("Vancouver, WA, United States") == "other"
    assert classify_location("Richmond Hill, ON") == "other"
    assert classify_location("Delta, Utah") == "other"


def test_bc_qualified_locations_stay_local():
    assert classify_location("Richmond, BC") == "vancouver"
    assert classify_location("Vancouver, British Columbia, Canada") == "vancouver"
    assert classify_location("Greater Vancouver, British Columbia") == "vancouver"


def test_multi_location_judged_per_place():
    assert classify_location("Toronto, Canada; Vancouver, Canada; Louisville, United States") == "vancouver"
    assert classify_location("Richmond, VA; Austin, TX") == "other"

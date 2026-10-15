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


def test_remote_united_states_rejected():
    assert not is_remote("Remote (United States)")
    assert classify_location("Remote (United States)") == "other"


def test_company_fallback_city_of_vancouver():
    assert (
        classify_location("LOC0049 Brookside Utilities Building", "City of Vancouver")
        == "vancouver"
    )

import sqlite3

from src.dedup import _is_match

DESC = "AlgaeCal is hiring an Associate Data Scientist to build models in BigQuery and Python. " * 10


def _row(**kw):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    base = {"company": "AlgaeCal", "title": "Associate Data Scientist", "location": "Burnaby", "description": DESC}
    base.update(kw)
    cols = ", ".join(f":{k} AS {k}" for k in base)
    return conn.execute(f"SELECT {cols}", base).fetchone()


def test_same_posting_in_different_cities_matches():
    assert _is_match(_row(location="Richmond, Greater Vancouver"), _row(location="North Vancouver, Greater Vancouver"))
    assert _is_match(_row(location="Burnaby"), _row(location="Surrey"))


def test_different_cities_with_different_descriptions_do_not_match():
    other = "Totally different role description about warehouse forecasting and logistics. " * 10
    assert not _is_match(_row(location="Burnaby"), _row(location="Toronto", description=other))


def test_short_snippets_do_not_prove_a_match():
    assert not _is_match(_row(location="Burnaby", description="Data role"), _row(location="Toronto", description="Data role"))


def test_same_location_still_matches_without_description():
    assert _is_match(_row(location="Vancouver, BC", description=""), _row(location="Vancouver, BC", description=""))


def test_same_posting_under_a_parent_company_name_matches():
    # One source lists the subsidiary, another the parent brand; the text is the same job.
    assert _is_match(_row(company="Northwind Data Services Inc"), _row(company="Contoso Group", location="Remote"))
    other = "Totally different role description about warehouse forecasting and logistics. " * 10
    assert not _is_match(_row(company="Northwind Data Services Inc"), _row(company="Contoso Group", description=other))
    assert not _is_match(_row(company="Northwind Data Services Inc", description=""),
                         _row(company="Contoso Group", description=""))


def test_different_title_never_matches():
    assert not _is_match(_row(), _row(title="Senior Marketing Manager"))

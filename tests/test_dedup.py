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


def test_company_that_differs_only_by_a_suffix_matches_when_the_text_agrees():
    # Pacific Reach (LinkedIn) vs Pacific Reach Properties (Glassdoor), Oct 2026: company 70, text 85.
    a = _row(company="Pacific Reach", location="Vancouver, BC (On-site)")
    b = _row(company="Pacific Reach Properties", location="Vancouver", description=DESC + " Apply now.")
    assert _is_match(a, b)
    assert _is_match(_row(company="WSP"), _row(company="WSP Canada"))


def test_suffix_only_company_match_needs_agreeing_text():
    # Apple posts many roles under one title; a different text is a different job.
    other = "Totally different role description about warehouse forecasting and logistics. " * 10
    assert not _is_match(_row(company="Apple"), _row(company="Apple Inc.", description=other))
    assert not _is_match(_row(company="Apple", description=""), _row(company="Apple Inc.", description=""))


def test_amazon_is_not_amazon_web_services():
    other = "Totally different role description about warehouse forecasting and logistics. " * 10
    assert not _is_match(_row(company="Amazon", location="Seattle"), _row(company="Amazon Web Services", location="Seattle", description=other))
    assert not _is_match(_row(company="Amazon"), _row(company="Amazon Development Centre", description=other))


def test_location_punctuation_does_not_hide_a_match():
    assert _is_match(_row(location="Vancouver, BC (On-site)", description=""), _row(location="Vancouver", description=""))


def _db_with(rows):
    from src import db

    conn = db.connect(":memory:")
    for i, (company, group, seen) in enumerate(rows, 1):
        conn.execute(
            "INSERT INTO jobs (dedup_group_id, source, external_id, title, company, location, description, "
            "first_seen, last_seen) VALUES (?, ?, ?, 'Data Analyst', ?, 'Vancouver', ?, ?, ?)",
            (group, f"s{i}", str(i), company, DESC, seen, seen),
        )
    conn.commit()
    return conn


def test_a_job_that_matches_two_groups_joins_them_all():
    from src.dedup import run_dedup

    import datetime as dt

    now = dt.datetime.now(dt.timezone.utc)
    iso = lambda days: (now - dt.timedelta(days=days)).isoformat(timespec="seconds")  # noqa: E731
    # Rows 1 and 2 are the same job in different groups and so is row 3 (which matches both).
    conn = _db_with([("Fortinet", "g1", iso(5)), ("Fortinet", "g2", iso(4)), ("Fortinet", "g3", iso(3))])
    run_dedup(conn)
    assert len({r[0] for r in conn.execute("SELECT dedup_group_id FROM jobs")}) == 1


def test_dedup_also_moves_rows_older_than_the_window_with_their_group():
    import datetime as dt

    from src.dedup import run_dedup

    now = dt.datetime.now(dt.timezone.utc)
    iso = lambda days: (now - dt.timedelta(days=days)).isoformat(timespec="seconds")  # noqa: E731
    conn = _db_with([("Fortinet", "old", iso(100)), ("Fortinet", "g1", iso(5)), ("Fortinet", "g2", iso(4))])
    conn.execute("UPDATE jobs SET dedup_group_id = 'g1' WHERE id = 1")  # an old row in g1
    conn.commit()
    run_dedup(conn)
    assert len({r[0] for r in conn.execute("SELECT dedup_group_id FROM jobs")}) == 1


def test_two_rows_that_match_each_other_merge_even_when_their_groups_first_rows_do_not(monkeypatch):
    import datetime as dt

    from src import dedup

    now = dt.datetime.now(dt.timezone.utc)
    iso = lambda days: (now - dt.timedelta(days=days)).isoformat(timespec="seconds")  # noqa: E731
    conn = _db_with([("A", "g1", iso(5)), ("B", "g2", iso(4)), ("C", "g3", iso(3)), ("D", "g4", iso(2))])
    ids = {r["company"]: r["id"] for r in conn.execute("SELECT id, company FROM jobs")}
    pairs = {frozenset({ids["A"], ids["C"]}), frozenset({ids["B"], ids["D"]}), frozenset({ids["C"], ids["D"]})}
    monkeypatch.setattr(dedup, "_is_match", lambda a, b: frozenset({a["id"], b["id"]}) in pairs)
    dedup.run_dedup(conn)
    assert len({r[0] for r in conn.execute("SELECT dedup_group_id FROM jobs")}) == 1

"""Public-sector, government, HN and enterprise-ATS adapters.

Fixtures in tests/fixtures/ats/ are real responses captured Oct 2026 (trimmed).
Network calls go through a fake client that serves fixtures by URL substring.
"""

import json
from pathlib import Path

import httpx
import pytest

from src.sources import (
    adp,
    bamboohr,
    bcps,
    breezy,
    dayforce,
    hn_hiring,
    icims,
    jibe,
    jobbank,
    jobvite,
    jooble,
    jsonld_board,
    oracle_hcm,
    peoplesoft,
    pinpoint,
    rippling,
    successfactors,
    taleo,
    teamtailor,
    ukg,
)
from src.sources.ats_common import localize, location_ok
from src.sources.jsonld import find_job_postings, posting_location

FIXTURES = Path(__file__).parent / "fixtures" / "ats"


def text(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def data(name):
    return json.loads(text(name))


class FakeClient:
    """Serves bodies by URL substring (first match wins); anything else is a 404."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, str(url), kwargs))
        req = httpx.Request(method, url)
        for needle, body in self.routes:
            if needle in str(url):
                if isinstance(body, (dict, list)):
                    return httpx.Response(200, json=body, request=req)
                return httpx.Response(200, text=body, request=req)
        return httpx.Response(404, text="not found", request=req)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("src.http_retry.time.sleep", lambda _s: None)


SEARCH = {"keywords": ["data analyst", "business analyst", "analyst", "software engineer"]}


def test_localize_pins_region_wide_postings():
    board = {"fallback_location": "Lower Mainland, BC", "vague_locations": ["Various", "Fraser Health"]}
    assert localize("Various Locations, BC, Canada", board).endswith("(Lower Mainland, BC)")
    assert localize("", board) == "Lower Mainland, BC"
    assert localize("Kamloops, BC", board) == "Kamloops, BC"
    assert localize("Various", {}) == "Various"


def test_jsonld_job_posting_from_icims_page():
    postings = find_job_postings(text("vch_detail.html"))
    assert len(postings) == 1
    assert posting_location(postings[0]).startswith("Vancouver")
    assert len(postings[0]["description"]) > 500


def test_jibe_fraser_health_full_text_and_region_fallback():
    board = {
        "slug": "fraserhealth",
        "name": "Fraser Health",
        "host": "jobs.fraserhealth.ca",
        "fallback_location": "Lower Mainland, BC",
        "vague_locations": ["Fraser Health"],
    }
    jobs = jibe.parse_page(data("fraserhealth_list.json"), board)
    assert len(jobs) == 5
    assert all(location_ok(j.location) for j in jobs)
    senior = jobs[0]
    assert senior.title == "Senior Business Analyst"
    assert "Lower Mainland" in senior.location
    assert "Qualifications" in senior.description and len(senior.description) > 3000
    assert senior.url.startswith("https://jobs.fraserhealth.ca/jobs/")


def test_oracle_worksafebc_list_then_detail():
    board = {
        "slug": "worksafebc",
        "name": "WorkSafeBC",
        "host": "eqzw-dev2.fa.ocs.oraclecloud.com",
        "site": "CX_3",
        "fallback_location": "Lower Mainland, BC",
        "vague_locations": ["Various"],
        "job_url": "https://careers-wcb.attainsolutions.net/en/sites/WorkSafeBC/job/{id}",
    }
    detail = data("worksafebc_detail.json")
    client = FakeClient(
        [("recruitingCEJobRequisitionDetails", detail), ("recruitingCEJobRequisitions", data("worksafebc_list.json"))]
    )
    jobs = oracle_hcm.fetch_oracle_jobs([board], search=SEARCH, client=client)
    assert jobs and jobs[0].title == "Business Analyst - Pipeline"
    assert jobs[0].url == "https://careers-wcb.attainsolutions.net/en/sites/WorkSafeBC/job/40414"
    assert "first-level" in jobs[0].description  # detail fixture's description text
    finder = next(k["params"]["finder"] for m, u, k in client.calls if u.endswith("recruitingCEJobRequisitionDetails"))
    assert finder.startswith('ById;Id="40414"')


def test_oracle_drops_far_away_postings():
    reqs = data("oracle_list.json")["items"][0]["requisitionList"]
    board = {"slug": "fortinet", "name": "Fortinet", "host": "h", "site": "CX_2001"}
    client = FakeClient([("recruitingCEJobRequisitions", data("oracle_list.json"))])
    jobs = oracle_hcm.fetch_oracle_jobs([board], client=client)
    assert all(location_ok(j.location) for j in jobs)
    assert len(jobs) <= len(reqs)


def test_successfactors_rss_keeps_lower_mainland_with_full_text():
    jobs = successfactors.parse_feed(text("successfactors_list.xml"), {"slug": "icbc", "name": "ICBC"})
    titles = {j.title for j in jobs}
    assert "SAP ABAP Developer - Senior" in titles
    assert not any("Kamloops" in j.location or "Chilliwack" in j.location for j in jobs)
    abap = next(j for j in jobs if j.title == "SAP ABAP Developer - Senior")
    assert abap.external_id == "607049717"
    assert abap.url == "https://careers.icbc.com/job/North-Vancouver-SAP-ABAP-Developer-Senior-Brit/607049717/"
    assert abap.location == "North Vancouver, British Columbia, Canada"
    assert len(abap.description) > 2000


def test_successfactors_search_page_rows_and_detail_microdata():
    page = """
      <span class="paginationLabel">Results <b>1 – 2</b> of <b>2</b></span>
      <table><tr class="data-row"><td><a class="jobTitle-link" href="/job/Burnaby-Data-Analyst/611/">Data Analyst</a></td>
      <td><span class="jobLocation">Burnaby, BC, CA</span></td><td><span class="jobDate">Oct 1, 2026</span></td></tr>
      <tr class="data-row"><td><a class="jobTitle-link" href="/job/Toronto-Analyst/612/">Analyst</a></td>
      <td><span class="jobLocation">Toronto, ON, CA</span></td></tr></table>"""
    rows, total = successfactors.parse_search(page)
    assert total == 2
    assert [(r["id"], r["location"]) for r in rows] == [("611", "Burnaby, BC, CA"), ("612", "Toronto, ON, CA")]
    real_rows, real_total = successfactors.parse_search(text("successfactors_search.html"))
    assert real_total == 9 and len(real_rows) == 9
    assert real_rows[0]["id"] == "607049717" and real_rows[0]["location"].startswith("North Vancouver")
    detail = successfactors.parse_detail(text("successfactors_detail.html"))
    assert detail["location"].startswith("North Vancouver")
    assert len(detail["description"]) > 2000


def test_successfactors_rss_requests_xml():
    client = FakeClient([("rss/job", text("successfactors_list.xml"))])
    jobs = successfactors.fetch_successfactors_jobs([{"slug": "icbc", "name": "ICBC", "host": "careers.icbc.com"}], client=client)
    assert jobs
    # The live endpoint returns 406 to the client's default Accept: application/json.
    _method, url, kwargs = client.calls[0]
    assert "rss/job" in url and "xml" in kwargs["headers"]["Accept"]


def test_icims_cards_and_detail():
    cards, pages = icims.parse_list(text("vch_list.html"))
    assert pages >= 1 and len(cards) == 5
    assert cards[0]["city"] == "Vancouver"
    assert cards[0]["url"].endswith("/job?in_iframe=1")
    phc_cards, phc_pages = icims.parse_list(text("icims_list.html"))
    assert phc_pages == 3 and phc_cards[0]["city"] == ""

    board = {"slug": "vch", "name": "Vancouver Coastal Health", "host": "careers-vch.icims.com", "fallback_location": "Vancouver, BC"}
    client = FakeClient([("/jobs/search", text("vch_list.html")), ("/job?in_iframe=1", text("vch_detail.html"))])
    jobs = icims.fetch_icims_jobs([board], search=SEARCH, client=client)
    assert jobs and all(j.description for j in jobs)
    assert "in_iframe" not in jobs[0].url


def test_jobbank_list_and_detail():
    rows = jobbank.parse_list(text("jobbank_list.html"))
    assert rows[0]["id"] == "50498935"
    assert rows[0]["location"] == "Abbotsford, BC"
    assert {r["location"] for r in rows} >= {"Delta, BC", "Maple Ridge, BC"}
    detail = jobbank.parse_detail(text("jobbank_detail.html"))
    assert detail["datePosted"] == "October 14, 2026"
    assert "Responsibilities" in detail["description"]

    client = FakeClient([("/jobsearch/jobsearch", text("jobbank_list.html")), ("/jobsearch/jobposting/", text("jobbank_detail.html"))])
    jobs = jobbank.fetch_jobbank_jobs(queries=["data analyst"], search=SEARCH, max_pages=1, client=client)
    # Abbotsford and Victoria are outside Metro Vancouver; "data administrator"
    # (Delta) doesn't pass the title gate, "database analyst" (Maple Ridge) does.
    assert {j.location for j in jobs} == {"Maple Ridge, BC"}
    assert all(j.source == "jobbank" for j in jobs)


def test_bcps_table_and_detail():
    rows = bcps.parse_list(text("bcps_list.html"))
    assert rows[0] == {
        "id": "126444",
        "ministry": "Liquor Distribution Branch",
        "title": "SPV 12R - Supervisor",
        "work_options": "",
        "location": "Burns Lake, BC, CA V0J 1E0",
        "opened": "2026-10-15",
        "closes": "2026-11-05",
    }
    assert "Workday Solutions Analyst" in bcps.parse_detail(text("bcps_detail.html"))


def test_hn_keeps_canada_open_remote_and_parses_header():
    story = data("hn_list.json")["hits"][0]["objectID"]
    jobs = hn_hiring.parse_comments(data("hn_detail.json"), story)
    assert jobs, "fixture has Canada-open remote posts"
    assert all(location_ok(j.location) for j in jobs)
    assert all(j.url.startswith("https://news.ycombinator.com/item?id=") for j in jobs)
    company, role = hn_hiring.split_header("Acme | Data Engineer | Vancouver, BC | Full-time | https://acme.com")
    assert (company, role) == ("Acme", "Data Engineer")
    assert not location_ok(hn_hiring.post_location("Acme | Engineer | REMOTE (US only)"))
    assert location_ok(hn_hiring.post_location("Acme | Engineer | Vancouver, BC | Onsite"))


def test_peoplesoft_translink():
    rows = peoplesoft.parse_list(text("translink_list.html"))
    assert len(rows) == 5 and rows[0]["location"] == "Greater Vancouver"
    assert rows[0]["opened"] == "2026-10-15"
    assert rows[0]["company"]
    board = {"base_url": "https://x/c", "site_id": 2, "company_site_ids": {"BC Rapid Transit Co. Ltd": 5}}
    # Subsidiary postings 404 under TransLink's SiteId; they open under their own.
    assert peoplesoft._url(board, "P", company="BC Rapid Transit Co. Ltd")[1]["SiteId"] == "5"
    assert peoplesoft._url(board, "P", company="TransLink")[1]["SiteId"] == "2"
    body = peoplesoft.parse_detail(text("translink_detail.html"))
    assert "TransLink" in body and len(body) > 2000


def test_taleo_rss_full_html_description():
    jobs = taleo.parse_feed(text("taleo_list.xml"), {"slug": "burnaby", "name": "City of Burnaby"})
    assert len(jobs) == 5
    assert jobs[0].external_id == "7623" and jobs[0].location == "Burnaby, BC"
    assert "rid=7623" in jobs[0].url
    assert len(jobs[0].description) > 1000


def test_adp_list_detail_and_public_url():
    board = {"slug": "general-fusion", "name": "General Fusion", "cid": "3196ba6f", "lang": "en_CA"}
    client = FakeClient([("job-requisitions/", data("adp_detail.json")), ("job-requisitions", data("adp_list.json"))])
    jobs = adp.fetch_adp_jobs([board], client=client)
    assert jobs and jobs[0].location == "Richmond, BC"
    assert "jobId=567505" in jobs[0].url
    assert jobs[0].description


def test_ukg_detail_object_and_post_search():
    detail = ukg.parse_detail(text("ukg_detail.html"))
    assert detail["Title"].startswith("Quality Engineering Lead")
    assert ukg.location_of(detail).startswith("Vancouver, BC")
    opp = {k: detail[k] for k in ("Id", "Title", "Locations", "PostedDate")}
    client = FakeClient(
        [("LoadSearchResults", {"opportunities": [opp], "totalCount": 1}), ("OpportunityDetail", text("ukg_detail.html"))]
    )
    board = {"slug": "vancity", "name": "Vancity", "host": "recruiting.ultipro.com", "tenant": "VAN5000VCSCU", "guid": "g"}
    jobs = ukg.fetch_ukg_jobs([board], client=client)
    assert len(jobs) == 1 and len(jobs[0].description) > 1000
    method, _url, kwargs = client.calls[0]
    assert method == "POST" and kwargs["json"]["opportunitySearch"]["Skip"] == 0


def test_dayforce_next_data_detail():
    posting = data("dayforce_detail.json")["job"]
    page = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(
        {"props": {"pageProps": {"dehydratedState": {"queries": [{"state": {"data": posting}}]}}}}
    ) + "</script>"
    parsed = dayforce.parse_detail(page)
    assert parsed["jobTitle"] == "Junior Survey Assistant"
    assert dayforce.location_of(parsed) == "Calgary, AB"
    assert len(dayforce.description_of(parsed)) > 500
    summary = {"jobPostingId": 8581, "jobTitle": "Junior Survey Assistant", "postingLocations": [{"cityName": "Burnaby", "stateCode": "BC"}]}
    client = FakeClient([
        ("api/auth/csrf", {"csrfToken": "tok123"}),
        ("jobposting/search", {"jobPostings": [summary], "maxCount": 1}),
        ("/jobs/8581", page),
    ])
    board = {"slug": "mcelhanney", "name": "McElhanney", "client": "mcelhanney", "board": "CANDIDATEPORTAL"}
    # Detail says Calgary, so the posting is dropped after the detail fetch.
    assert dayforce.fetch_dayforce_jobs([board], client=client) == []
    # The search POST carries the CSRF token fetched first; without it Dayforce answers 403.
    _method, _url, kwargs = next(c for c in client.calls if c[0] == "POST")
    assert kwargs["headers"] == {"X-CSRF-TOKEN": "tok123"}


def test_jooble_skips_without_key(monkeypatch):
    monkeypatch.delenv("JOOBLE_API_KEY", raising=False)
    assert jooble.fetch_jooble_jobs(queries=["data analyst"], location="Vancouver, BC") == []


def test_jooble_posts_and_filters():
    client = FakeClient(
        [("jooble.org/api/", {"totalCount": 2, "jobs": [
            {"id": 1, "title": "Data Analyst", "location": "Vancouver, BC", "snippet": "<b>SQL</b>", "link": "https://x/1"},
            {"id": 2, "title": "Data Analyst", "location": "Toronto, ON", "snippet": "", "link": "https://x/2"},
        ]})]
    )
    jobs = jooble.fetch_jooble_jobs(queries=["data analyst"], location="Vancouver, BC", api_key="k", max_pages=1, client=client)
    assert [j.external_id for j in jobs] == ["1"]
    assert client.calls[0][0] == "POST"


# --- smaller ATS platforms -------------------------------------------------



def test_bamboohr_list_detail():
    board = {"slug": "scalepad", "name": "ScalePad"}
    client = FakeClient([("/detail", data("bamboohr_detail.json")), ("/careers/list", data("bamboohr_list.json"))])
    jobs = bamboohr.fetch_bamboohr_jobs([board], client=client)
    assert jobs and all(location_ok(j.location) for j in jobs)
    assert not any("Arizona" in j.location for j in jobs)
    assert jobs[0].posted_date == "2026-09-21" and len(jobs[0].description) > 300


def test_pinpoint_joins_sections():
    jobs = pinpoint.parse_postings(data("pinpoint_list.json"), {"slug": "article", "name": "Article"})
    assert jobs and jobs[0].location == "Vancouver, British Columbia"
    assert "## What You’ll Do" in jobs[0].description and "## Perks & Benefits" in jobs[0].description


def test_breezy_drops_stale_karachi_post():
    client = FakeClient([("/json", data("breezy_list.json")), ("/p/", text("breezy_detail.html"))])
    assert breezy.fetch_breezy_jobs([{"slug": "lethub", "name": "LetHub"}], client=client) == []


def test_rippling_merges_location_rows_and_filters():
    merged = rippling.merge_rows(data("rippling_list.json")["items"])
    assert len(merged) <= len(data("rippling_list.json")["items"])
    client = FakeClient([("/jobs/", data("rippling_detail.json")), ("/jobs", data("rippling_list.json"))])
    jobs = rippling.fetch_rippling_jobs([{"slug": "d-wave-quantum", "name": "D-Wave"}], client=client)
    assert all(location_ok(j.location) for j in jobs)


def test_teamtailor_multi_location_feed():
    jobs = teamtailor.parse_feed(text("teamtailor_list.xml"), {"slug": "uptempo", "name": "Uptempo"})
    assert jobs and "Vancouver, Canada" in jobs[0].location
    assert "<p>" not in jobs[0].description and "What you’ll do" in jobs[0].description


def test_jobvite_xml_feed():
    jobs = jobvite.parse_feed(text("jobvite_list.xml"), {"slug": "absolute", "name": "Absolute", "company_id": "ql9aVfwj"})
    assert jobs and all(location_ok(j.location) for j in jobs)
    assert not any("Brazil" in j.location for j in jobs)
    assert jobs[0].url.startswith("https://jobs.jobvite.com/absolute/job/")
    assert len(jobs[0].description) > 1000


def test_jazzhr_and_humi_links_then_jsonld():
    jazz = {"slug": "iqmetrix", "name": "iQmetrix", "kind": "jazzhr"}
    client = FakeClient([("/apply/", text("jazzhr_detail.html")), ("applytojob.com/apply", text("jazzhr_list.html"))])
    jobs = jsonld_board.fetch_jsonld_board_jobs([jazz], client=client)
    assert jobs and jobs[0].location == "Vancouver, BC" and len(jobs[0].description) > 1000

    humi = {"slug": "comm100", "name": "Comm100", "kind": "humi"}
    client = FakeClient([("/rd/", text("humi_detail.html")), ("/sales/", text("humi_detail.html")), ("applytojobs.ca", text("humi_list.html"))])
    jobs = jsonld_board.fetch_jsonld_board_jobs([humi], search=SEARCH, client=client)
    assert all(j.source == "humi:comm100" for j in jobs)
    assert all("Account Executive" not in j.title for j in jobs)  # title gate skipped sales roles


def test_html_board_phsa_search_pages_with_jsonld_details():
    board = {
        "slug": "phsa",
        "name": "PHSA",
        "kind": "html",
        "list_url": "https://jobs.phsa.ca/jobs?search_api_fulltext={query}&page={page}",
        "link_pattern": r"^/job/([a-z0-9-]+)$",
        "max_pages": 4,
    }
    client = FakeClient([("jobs.phsa.ca/job/", text("phsa_job.html")), ("search_api_fulltext=analyst&page=0", text("phsa_search.html"))])
    jobs = jsonld_board.fetch_jsonld_board_jobs([board], search=SEARCH, client=client)
    assert jobs and all(j.source == "html:phsa" for j in jobs)
    assert jobs[0].location == "Burnaby, British Columbia, Canada"
    assert len(jobs[0].description) > 5000
    # page 1 of "analyst" 404s, so paging stops there
    assert any("analyst&page=1" in url for _, url, _ in client.calls)
    assert not any("analyst&page=2" in url for _, url, _ in client.calls)


def test_html_board_without_jsonld_uses_page_text():
    poly = {"slug": "polygon-homes", "name": "Polygon Homes", "kind": "html", "list_url": "https://polyhomes.com/careers/",
            "link_pattern": r"/careers/([a-z0-9-]+)/?$", "fallback_location": "Vancouver, BC"}
    client = FakeClient([("/careers/digital-ai-analyst/", text("polygon_job.html")), ("polyhomes.com/careers/", text("polygon_list.html"))])
    jobs = jsonld_board.fetch_jsonld_board_jobs([poly], search=SEARCH, client=client)
    assert [j.title for j in jobs] == ["Digital & AI Analyst (12-Month Contract)"]
    assert jobs[0].location == "Vancouver, BC"
    assert "Director of Digital & AI" in jobs[0].description
    assert "careers@polyhomes.com" in jobs[0].description


def test_html_board_title_separator_gives_location():
    glot = {"slug": "glotman-simpson", "name": "Glotman Simpson", "kind": "html", "list_url": "https://glotmansimpson.com/careers",
            "link_pattern": r"/career/([a-z0-9-]+)/?$", "title_separator": "•", "fallback_location": "Vancouver, BC"}
    client = FakeClient([("/career/", text("glotman_job.html")), ("glotmansimpson.com/careers", text("glotman_list.html"))])
    jobs = jsonld_board.fetch_jsonld_board_jobs([glot], client=client)
    assert jobs and all(j.location == "Vancouver Office" for j in jobs)
    assert not any("los-angeles" in j.url or "victoria" in j.url for j in jobs)
    assert len(jobs[0].description) > 1000

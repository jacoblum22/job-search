"""Which adapter serves each section of config/ats_boards.yaml.

BOARD_PLATFORMS: per-company boards — `fn(boards, search) -> list[Job]`.
FEEDS: whole-market sources configured once — `fn(options, search, queries) -> list[Job]`.
"""

from __future__ import annotations

from collections.abc import Callable

from src.db import Job
from src.sources.adp import fetch_adp_jobs
from src.sources.ashby import fetch_ashby_jobs
from src.sources.bamboohr import fetch_bamboohr_jobs
from src.sources.bcps import fetch_bcps_jobs
from src.sources.breezy import fetch_breezy_jobs
from src.sources.dayforce import fetch_dayforce_jobs
from src.sources.greenhouse import fetch_greenhouse_jobs
from src.sources.himalayas import fetch_himalayas_jobs
from src.sources.hn_hiring import fetch_hn_jobs
from src.sources.icims import fetch_icims_jobs
from src.sources.jibe import fetch_jibe_jobs
from src.sources.jobbank import fetch_jobbank_jobs
from src.sources.jobicy import fetch_jobicy_jobs
from src.sources.jobvite import fetch_jobvite_jobs
from src.sources.jsonld_board import fetch_jsonld_board_jobs
from src.sources.lever import fetch_lever_jobs
from src.sources.oracle_hcm import fetch_oracle_jobs
from src.sources.peoplesoft import fetch_peoplesoft_jobs
from src.sources.pinpoint import fetch_pinpoint_jobs
from src.sources.rippling import fetch_rippling_jobs
from src.sources.smartrecruiters import fetch_smartrecruiters_jobs
from src.sources.successfactors import fetch_successfactors_jobs
from src.sources.taleo import fetch_taleo_jobs
from src.sources.teamtailor import fetch_teamtailor_jobs
from src.sources.ukg import fetch_ukg_jobs
from src.sources.workable import fetch_workable_jobs

BoardFetcher = Callable[[list, dict], list[Job]]
FeedFetcher = Callable[[dict, dict, list[str]], list[Job]]

BOARD_PLATFORMS: dict[str, BoardFetcher] = {
    "greenhouse": lambda b, s: fetch_greenhouse_jobs(b),
    "lever": lambda b, s: fetch_lever_jobs(b),
    "ashby": lambda b, s: fetch_ashby_jobs(b),
    "workable": lambda b, s: fetch_workable_jobs(b),
    "smartrecruiters": lambda b, s: fetch_smartrecruiters_jobs(b, search=s),
    "oracle": lambda b, s: fetch_oracle_jobs(b, search=s),
    "jibe": lambda b, s: fetch_jibe_jobs(b),
    "icims": lambda b, s: fetch_icims_jobs(b, search=s),
    "successfactors": lambda b, s: fetch_successfactors_jobs(b, search=s),
    "taleo": lambda b, s: fetch_taleo_jobs(b),
    "adp": lambda b, s: fetch_adp_jobs(b, search=s),
    "ukg": lambda b, s: fetch_ukg_jobs(b, search=s),
    "dayforce": lambda b, s: fetch_dayforce_jobs(b, search=s),
    "peoplesoft": lambda b, s: fetch_peoplesoft_jobs(b, search=s),
    "bamboohr": lambda b, s: fetch_bamboohr_jobs(b, search=s),
    "pinpoint": lambda b, s: fetch_pinpoint_jobs(b),
    "breezy": lambda b, s: fetch_breezy_jobs(b, search=s),
    "rippling": lambda b, s: fetch_rippling_jobs(b, search=s),
    "teamtailor": lambda b, s: fetch_teamtailor_jobs(b),
    "jobvite": lambda b, s: fetch_jobvite_jobs(b),
    "jazzhr": lambda b, s: fetch_jsonld_board_jobs([{**x, "kind": "jazzhr"} for x in b], search=s),
    "humi": lambda b, s: fetch_jsonld_board_jobs([{**x, "kind": "humi"} for x in b], search=s),
    "html": lambda b, s: fetch_jsonld_board_jobs([{**x, "kind": "html"} for x in b], search=s),
}

FEEDS: dict[str, FeedFetcher] = {
    "jobbank": lambda o, s, q: fetch_jobbank_jobs(
        queries=o.get("queries") or q, search=s, max_pages=o.get("max_pages", 2)
    ),
    "bcps": lambda o, s, q: fetch_bcps_jobs(search=s),
    "hn": lambda o, s, q: fetch_hn_jobs(),
    "himalayas": lambda o, s, q: fetch_himalayas_jobs(
        o.get("queries") or q,
        country=o.get("country", "CA"),
        seniority=o.get("seniority"),
        max_pages=o.get("max_pages", 3),
    ),
    "jobicy": lambda o, s, q: fetch_jobicy_jobs(
        geo=o.get("geo", "canada"),
        industries=o.get("industries"),
        max_pages=o.get("max_pages", 5),
    ),
}

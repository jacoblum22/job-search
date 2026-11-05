"""schema.org JobPosting extraction from HTML job pages.

Many careers sites (iCIMS, Jobvite, SuccessFactors, JazzHR and plenty of
custom pages) embed the posting as `<script type="application/ld+json">` for
Google Jobs. That block carries the title, location, date and the full
description, so one parser serves them all.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

_SCRIPT_RE = re.compile(
    r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)


def _walk(node: Any):
    if isinstance(node, list):
        for item in node:
            yield from _walk(item)
    elif isinstance(node, dict):
        yield node
        for key in ("@graph", "mainEntity", "itemListElement", "item"):
            if key in node:
                yield from _walk(node[key])


def _is_job_posting(node: dict) -> bool:
    kind = node.get("@type")
    kinds = kind if isinstance(kind, list) else [kind]
    return "JobPosting" in kinds


def find_job_postings(page: str) -> list[dict]:
    """Every JobPosting object in the page's JSON-LD blocks."""
    found = []
    for raw in _SCRIPT_RE.findall(page or ""):
        raw = raw.strip()
        if raw.startswith("<!--"):
            raw = raw.removeprefix("<!--").removesuffix("-->")
        try:
            data = json.loads(raw, strict=False)
        except ValueError:
            try:
                data = json.loads(html.unescape(raw), strict=False)
            except ValueError:
                continue
        found.extend(n for n in _walk(data) if _is_job_posting(n))
    return found


def _place(loc: Any) -> str:
    if isinstance(loc, list):
        return "; ".join(p for p in (_place(x) for x in loc) if p)
    if isinstance(loc, str):
        return loc.strip()
    if not isinstance(loc, dict):
        return ""
    addr = loc.get("address", loc)
    if isinstance(addr, str):
        return addr.strip()
    if not isinstance(addr, dict):
        return ""
    country = addr.get("addressCountry")
    if isinstance(country, dict):
        country = country.get("name")
    parts = [addr.get("addressLocality"), addr.get("addressRegion"), country]
    return ", ".join(str(p).strip() for p in parts if p)


def posting_location(posting: dict) -> str:
    """'Vancouver, BC, CA', with 'Remote - ' prepended for TELECOMMUTE jobs."""
    loc = _place(posting.get("jobLocation"))
    remote = str(posting.get("jobLocationType") or "").upper() == "TELECOMMUTE"
    if remote:
        region = _place(posting.get("applicantLocationRequirements"))
        loc = loc or region
        return f"Remote - {loc}" if loc else "Remote"
    return loc


def posting_company(posting: dict) -> str:
    org = posting.get("hiringOrganization")
    if isinstance(org, dict):
        return str(org.get("name") or "").strip()
    return str(org or "").strip()


def posting_id(posting: dict) -> str:
    ident = posting.get("identifier")
    if isinstance(ident, dict):
        ident = ident.get("value")
    return str(ident or "").strip()

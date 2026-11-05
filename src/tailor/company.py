"""Company research files: slugs, staleness, page fetching and quote verification (step 1b).

The research subagent finds pages with web search, then saves each one with
``fetch_page`` (the ``company-fetch`` command), which stores the page's own
text. Agent web-fetch tools can return a model's summary of a page instead,
and a quote copied from a summary is not the company's wording, so pages are
never saved from them. ``verify_company`` then marks each fact verified only
when its quote really appears in the page it names.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from src.tailor import TailorError
from src.tailor.appdir import read_json, write_json
from src.tailor.paths import resolve

_QUOTES = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "″": '"',
    "–": "-", "—": "-", "−": "-", "‐": "-", "‑": "-",
    " ": " ",
})
_HYPHEN_BREAK = re.compile(r"(\w)-[ \t]*\r?\n\s*(\w)")
_REQUIRED = ("id", "fact", "quote", "page")


def company_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")


def company_dir(cfg: dict[str, Any], name: str) -> Path:
    return resolve(cfg, "companies") / company_slug(name)


def is_stale(directory: Path, days: float) -> bool:
    """True when facts.json is missing or older than `days` days."""
    facts = Path(directory) / "facts.json"
    if not facts.exists():
        return True
    return (time.time() - facts.stat().st_mtime) > days * 86400


def _normalize(text: str) -> str:
    text = str(text).replace("­", "").translate(_QUOTES)
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def _page_text(pages_dir: Path, page: str) -> str | None:
    name = str(page).replace("\\", "/")
    if name.startswith("pages/"):
        name = name[len("pages/"):]
    root = pages_dir.resolve()
    for cand in (name, name + ".txt"):
        path = (pages_dir / cand).resolve()
        if root not in path.parents:
            return None  # path escapes pages/
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")
    return None


def _notes(name: str, facts: list[dict[str, Any]]) -> str:
    ok = [f for f in facts if f["verified"]]
    bad = [f for f in facts if not f["verified"]]
    lines = [f"# {name}: company research", "", "## Verified facts", ""]
    if not ok:
        lines.append("None.")
    for f in ok:
        link = f" ([source]({f['url']}))" if f.get("url") else ""
        lines.append(f"- `{f['id']}` {f['fact']}{link}")
        lines.append(f"  > {f['quote']}")
    lines += ["", "## Unverified facts (do not use)", ""]
    if not bad:
        lines.append("None.")
    for f in bad:
        link = f" ([source]({f['url']}))" if f.get("url") else ""
        lines.append(f"- `{f['id']}` {f['fact']}{link}: {f['reason']}")
    return "\n".join(lines) + "\n"


# Research rules the prompt states, enforced here so a run can't drift from them
# (prompts/tailor/company-research.md). Job boards, profile/summary sites and
# social media restate other pages and can get them wrong.
_SKIP_HOSTS = (
    "indeed.", "glassdoor.", "linkedin.com", "ziprecruiter.", "monster.", "workopolis.",
    "simplyhired.", "talent.com", "jobbank.gc.ca", "careerbeacon.", "eluta.ca", "adzuna.",
    "jooble.", "careerjet.", "wellfound.com", "builtin.com", "dice.com", "jobillico.",
    "crunchbase.", "zoominfo.", "briefglance.", "rocketreach.", "owler.", "dnb.com", "craft.co",
    "pitchbook.", "cbinsights.", "comparably.", "signalhire.", "apollo.io", "lusha.", "village.ai",
    "publicsectornetwork.", "facebook.com", "instagram.com", "twitter.com", "x.com", "tiktok.com",
    "reddit.com", "youtube.com", "medium.com", "trustpilot.", "yelp.",
    # Review and listing directories (clinics, local services): star ratings and text the site wrote.
    "medimap.", "ratemds.", "healthgrades.", "zocdoc.", "trustanalytica.", "yellowpages.",
)
PAGE_BUDGET = 6  # pages one research pass may save
_BUDGET_WINDOW_S = 12 * 3600  # pages saved within this window count as the same pass
NEWS_MAX_AGE_DAYS = 365  # a dated page older than this is old news, not a current fact
_PUBLISHED_META = re.compile(
    r"""<meta[^>]+(?:property|name|itemprop)=["'](?:article:published_time|og:published_time|"""
    r"""datePublished|date|pubdate|publish[-_]date|dc\.date)["'][^>]*content=["']([^"']+)["']"""
    r'|"datePublished"\s*:\s*"([^"]+)"',
    re.IGNORECASE,
)
_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def _skipped_host(url: str) -> str | None:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    for h in _SKIP_HOSTS:
        # "indeed." is a brand on any country domain (ca.indeed.com, indeed.ca); "x.com" is one domain.
        hit = f".{h}" in f".{host}" if h.endswith(".") else (host == h or host.endswith(f".{h}"))
        if hit:
            return h
    return None


def published_date(html: str) -> str | None:
    """The page's own publication date (YYYY-MM-DD) from its meta tags or JSON-LD, if it has one."""
    for m in _PUBLISHED_META.finditer(html or ""):
        d = _ISO_DATE.search(m.group(1) or m.group(2) or "")
        if d:
            return d.group(0)
    return None


def _page_published(text: str) -> str | None:
    m = re.search(r"^Published: (\d{4}-\d{2}-\d{2})$", text[:300], re.MULTILINE)
    return m.group(1) if m else None


def _page_url(text: str) -> str | None:
    m = re.match(r"URL: (\S+)", text)
    return m.group(1) if m else None


_DROP_TAGS = ("script", "style", "noscript", "nav", "header", "footer", "form", "svg", "iframe")
_BLOCK_TAGS = ("address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt", "figcaption",
               "figure", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "li", "main", "ol", "p", "pre",
               "section", "table", "td", "th", "tr", "ul")
_BREAK = "\x00"
_PLACEHOLDER = re.compile(r"loading\b.{0,40}$", re.I)


def page_text(html: str) -> str:
    """Visible text of an HTML page, one block per line, without menus, scripts or footers.

    Lines break only at block elements: a link or span inside a sentence stays in it, so a
    quote copied from the rendered page ("one of <a>X</a>, marking") is found in the saved text.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_DROP_TAGS):
        tag.decompose()
    for tag in soup(_BLOCK_TAGS):
        tag.insert_before(_BREAK)
        tag.insert_after(_BREAK)
    root = soup.find("main") or soup.body or soup
    lines = [" ".join(ln.split()) for ln in root.get_text().split(_BREAK)]
    return "\n".join(ln for ln in lines if ln)


def fetch_page(directory: Path, url: str, timeout: float = 30.0) -> dict[str, Any]:
    """Download `url` and save its text as the next ``pages/<n>.txt`` (first line ``URL: <url>``,
    then ``Published: <date>`` when the page states one)."""
    import httpx

    directory = Path(directory)
    skipped = _skipped_host(url)
    if skipped:
        raise TailorError(f"{url} is a job board, profile or social site ({skipped.strip('.')}); "
                          "use the company's own site or a news outlet instead")
    pages = directory / "pages"
    recent = [f for f in pages.glob("*.txt") if time.time() - f.stat().st_mtime < _BUDGET_WINDOW_S] \
        if pages.is_dir() else []
    if len(recent) >= PAGE_BUDGET:
        raise TailorError(f"page budget used ({PAGE_BUDGET} pages saved); stop fetching and write "
                          "facts.json from the saved pages")
    try:
        resp = httpx.get(url, follow_redirects=True, timeout=timeout,
                         headers={"User-Agent": "Mozilla/5.0 (job-search company research)"})
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise TailorError(f"could not fetch {url}: {e}") from e
    ctype = resp.headers.get("content-type", "")
    published = None
    if "html" in ctype:
        text = page_text(resp.text)
        published = published_date(resp.text)
    elif ctype.startswith("text/"):
        text = resp.text
    else:
        raise TailorError(f"{url} is {ctype or 'an unknown type'}, not a web page; skip it")
    # A page built by JavaScript comes back as its placeholders ("Loading component..."), not as empty.
    lines = [ln for ln in text.splitlines() if ln.strip()]
    waiting = sum(bool(_PLACEHOLDER.match(ln.strip())) for ln in lines)
    if not lines or waiting >= len(lines) - waiting:
        raise TailorError(f"{url} has no readable text (it may need JavaScript); skip it")
    pages.mkdir(parents=True, exist_ok=True)
    n = 1 + max((int(f.stem) for f in pages.glob("*.txt") if f.stem.isdigit()), default=0)
    path = pages / f"{n}.txt"
    head = f"URL: {resp.url}\n" + (f"Published: {published}\n" if published else "")
    path.write_text(f"{head}\n{text}\n", encoding="utf-8")
    return {"page": n, "path": str(path), "url": str(resp.url), "chars": len(text), "published": published}


def _age_days(published: str, read: str | None) -> int:
    from datetime import date

    try:
        when = date.fromisoformat(str(read)[:10]) if read else date.today()
        return (when - date.fromisoformat(published)).days
    except ValueError:
        return 0


def verify_company(directory: Path) -> dict[str, Any]:
    """Check each fact's quote against its saved page; rewrite facts.json and write verified.md.

    ``notes.md`` belongs to the research step and is left alone.
    """
    directory = Path(directory)
    facts_path = directory / "facts.json"
    facts = read_json(facts_path)
    if not isinstance(facts, list):
        raise TailorError(f"{facts_path} must be a list of facts")
    seen: set[str] = set()
    for i, f in enumerate(facts):
        if not isinstance(f, dict):
            raise TailorError(f"{facts_path}: fact {i} is not an object")
        missing = [k for k in _REQUIRED if k not in f]
        if missing:
            raise TailorError(f"{facts_path}: fact {i} is missing {', '.join(missing)}")
        if str(f["id"]) in seen:
            raise TailorError(f"{facts_path}: duplicate fact id {f['id']!r}")
        seen.add(str(f["id"]))

    pages_dir = directory / "pages"
    cache: dict[str, str | None] = {}
    dated: dict[str, str | None] = {}
    where: dict[str, str | None] = {}
    for f in facts:
        page = str(f["page"])
        if page not in cache:
            raw = _page_text(pages_dir, page) if page.strip() else None
            cache[page] = None if raw is None else _normalize(raw)
            dated[page] = None if raw is None else _page_published(raw)
            where[page] = None if raw is None else _page_url(raw)
        text = cache[page]
        quote = _normalize(f["quote"])
        # The source rule applies here too, not only at fetch time: a page saved before a site was
        # added to the list (or a fact naming another url) would otherwise verify for 30 days.
        skipped = next((h for h in (_skipped_host(u) for u in (where.get(page), f.get("url")) if u) if h), None)
        f.pop("reason", None)
        if not quote:
            f["verified"], f["reason"] = False, "empty quote"
        elif text is None:
            f["verified"], f["reason"] = False, f"page {page!r} not found under pages/"
        elif skipped:
            f["verified"], f["reason"] = False, (f"from a job board, profile, review or social site "
                                                 f"({skipped.strip('.')}): not a company or news source")
        elif quote not in text:
            f["verified"], f["reason"] = False, "quote not found in page text"
        elif dated[page] and _age_days(dated[page], f.get("read")) > NEWS_MAX_AGE_DAYS:
            f["verified"], f["reason"] = False, (f"page published {dated[page]}, more than "
                                                 f"{NEWS_MAX_AGE_DAYS // 365} year before research: old news")
        else:
            f["verified"] = True
    write_json(facts_path, facts)
    (directory / "verified.md").write_text(_notes(directory.name, facts), encoding="utf-8")
    n_ok = sum(1 for f in facts if f["verified"])
    return {
        "company_dir": str(directory),
        "verified": n_ok,
        "unverified": len(facts) - n_ok,
        "facts": facts,
    }

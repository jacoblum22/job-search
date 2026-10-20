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


_DROP_TAGS = ("script", "style", "noscript", "nav", "header", "footer", "form", "svg", "iframe")
_PLACEHOLDER = re.compile(r"loading\b.{0,40}$", re.I)


def page_text(html: str) -> str:
    """Visible text of an HTML page, one block per line, without menus, scripts or footers."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(_DROP_TAGS):
        tag.decompose()
    root = soup.find("main") or soup.body or soup
    lines = [" ".join(ln.split()) for ln in root.get_text("\n").splitlines()]
    return "\n".join(ln for ln in lines if ln)


def fetch_page(directory: Path, url: str, timeout: float = 30.0) -> dict[str, Any]:
    """Download `url` and save its text as the next ``pages/<n>.txt`` (first line ``URL: <url>``)."""
    import httpx

    directory = Path(directory)
    try:
        resp = httpx.get(url, follow_redirects=True, timeout=timeout,
                         headers={"User-Agent": "Mozilla/5.0 (job-search company research)"})
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise TailorError(f"could not fetch {url}: {e}") from e
    ctype = resp.headers.get("content-type", "")
    if "html" in ctype:
        text = page_text(resp.text)
    elif ctype.startswith("text/"):
        text = resp.text
    else:
        raise TailorError(f"{url} is {ctype or 'an unknown type'}, not a web page; skip it")
    # A page built by JavaScript comes back as its placeholders ("Loading component..."), not as empty.
    lines = [ln for ln in text.splitlines() if ln.strip()]
    waiting = sum(bool(_PLACEHOLDER.match(ln.strip())) for ln in lines)
    if not lines or waiting >= len(lines) - waiting:
        raise TailorError(f"{url} has no readable text (it may need JavaScript); skip it")
    pages = directory / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    n = 1 + max((int(f.stem) for f in pages.glob("*.txt") if f.stem.isdigit()), default=0)
    path = pages / f"{n}.txt"
    path.write_text(f"URL: {resp.url}\n\n{text}\n", encoding="utf-8")
    return {"page": n, "path": str(path), "url": str(resp.url), "chars": len(text)}


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
    for f in facts:
        page = str(f["page"])
        if page not in cache:
            raw = _page_text(pages_dir, page) if page.strip() else None
            cache[page] = None if raw is None else _normalize(raw)
        text = cache[page]
        quote = _normalize(f["quote"])
        f.pop("reason", None)
        if not quote:
            f["verified"], f["reason"] = False, "empty quote"
        elif text is None:
            f["verified"], f["reason"] = False, f"page {page!r} not found under pages/"
        elif quote in text:
            f["verified"] = True
        else:
            f["verified"], f["reason"] = False, "quote not found in page text"
    write_json(facts_path, facts)
    (directory / "verified.md").write_text(_notes(directory.name, facts), encoding="utf-8")
    n_ok = sum(1 for f in facts if f["verified"])
    return {
        "company_dir": str(directory),
        "verified": n_ok,
        "unverified": len(facts) - n_ok,
        "facts": facts,
    }

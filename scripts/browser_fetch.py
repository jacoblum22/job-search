"""Copy queued job descriptions out of a signed-in Chrome with no model in the loop.

The Claude in Chrome task reads each page and then retypes it, ~3k tokens per
posting each way, and on 2026-11-05 it stopped after 25 of 426 listings. This
script does the same hand-off (see src/browser_queue.py) mechanically:

    scripts/browser_fetch.py login            # once: sign in to LinkedIn/Glassdoor in the script's own Chrome profile
    scripts/browser_fetch.py run              # read queue.json, write .browser-queue/<id>.md / <id>.fail
    scripts/browser_fetch.py run --per-site 5 --sources linkedin

then `scripts/browser_queue.py sync` stores the files. Needs Playwright and the
real Chrome install:  uv sync --group browser

Rules it keeps (same as the Chrome task): read only (the one click is expanding
a collapsed description), at most --per-site (15) pages per site per run, a
pause between pages, and it never tries to get past a login wall, CAPTCHA or
bot check. At the first one on a site it writes a .fail file and stops that
site for the run, so a flagged account isn't hit again.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.browser_queue import MIN_FULL_CHARS, QUEUE_DIR, QUEUE_FILE

PROFILE_DIR = PROJECT_ROOT / ".browser-profile"  # git-ignored; holds the sign-ins
DEFAULT_PER_SITE = 15
PAUSE_SECONDS = (4.0, 9.0)

# First selector that matches wins. The last entries are generic fallbacks.
DESCRIPTION_SELECTORS = {
    "linkedin": [".jobs-description__content", ".show-more-less-html__markup", ".description__text", "#job-details"],
    "glassdoor": ['[class*="JobDetails_jobDescription"]', "#JobDescriptionContainer", '[data-test="jobDescriptionContent"]'],
    "indeed": ["#jobDescriptionText"],
    "careerjet": ["article"],
    "jobright": ['[class*="description"]', "main"],
}
GENERIC_SELECTORS = ["article", "main", "body"]
EXPAND_SELECTORS = [
    "button.show-more-less-html__button--more",
    "button.jobs-description__footer-button",
    'button[aria-label*="more" i]',
    'button:has-text("Show more")',
    'button:has-text("See more")',
]
LOGIN_URL = {"linkedin": "https://www.linkedin.com/login", "glassdoor": "https://www.glassdoor.ca/profile/login_input.htm"}

WALL_PATTERNS = [
    (re.compile(r"captcha|verify you are (a )?human|are you a robot|unusual traffic|checking your browser|cloudflare", re.IGNORECASE), "bot check"),
    (re.compile(r"sign in to view|join (now )?to (see|view)|log ?in to (see|view|continue)|authwall|/uas/login|/login", re.IGNORECASE), "login wall"),
]
CLOSED_PATTERNS = re.compile(
    r"no longer (accepting applications|available)|this job (has closed|is no longer)|job (has been )?(removed|expired)|"
    r"position has been filled|page not found|404", re.IGNORECASE)


def classify_page(url: str, title: str, text: str) -> tuple[str, str]:
    """('ok', '') for a readable posting, else ('wall', why) or ('gone', why).

    Walls (login, bot check) stop the whole site for the run; 'gone' only
    fails that one listing. Looks at the URL and title plus the start of the
    text, so a posting that merely mentions "captcha" deep in its body is fine.
    """
    head = f"{url}\n{title}\n{text[:600]}"
    for pattern, why in WALL_PATTERNS:
        if pattern.search(head):
            return "wall", why
    if len(text.strip()) < MIN_FULL_CHARS:
        return ("gone", "posting closed or removed") if CLOSED_PATTERNS.search(head) else ("gone", "no description on the page")
    if CLOSED_PATTERNS.search(f"{title}\n{text[:300]}"):
        return "gone", "posting closed or removed"
    return "ok", ""


def html_to_markdown(html: str) -> str:
    """Description HTML -> Markdown with headings and bullets kept, wording untouched."""
    from markdownify import markdownify

    md = markdownify(html, heading_style="ATX", bullets="-")
    md = re.sub(r"[ \t]+\n", "\n", md)
    return re.sub(r"\n{3,}", "\n\n", md).strip()


def site_of(listing: dict) -> str:
    return listing.get("source", "")


def choose(listings: list[dict], queue_dir: Path, per_site: int, sources: set[str] | None) -> list[dict]:
    """First `per_site` listings of each site (queue order) that have no result file yet."""
    have = {int(f.stem) for f in queue_dir.glob("*") if f.suffix in (".md", ".fail") and f.stem.isdigit()}
    taken: dict[str, int] = {}
    out = []
    for r in listings:
        s = site_of(r)
        if r["id"] in have or (sources and s not in sources) or taken.get(s, 0) >= per_site:
            continue
        taken[s] = taken.get(s, 0) + 1
        out.append(r)
    return out


def _launch(playwright, headless: bool):
    PROFILE_DIR.mkdir(exist_ok=True)
    return playwright.chromium.launch_persistent_context(
        str(PROFILE_DIR), channel="chrome", headless=headless, viewport={"width": 1280, "height": 900})


def cmd_login(_args) -> int:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        ctx = _launch(p, headless=False)
        for site, url in LOGIN_URL.items():
            ctx.new_page().goto(url)
            print(f"Sign in to {site} in the window that opened.")
        input("Press Enter here when you are signed in to everything you need (this closes the window)... ")
        ctx.close()
    return 0


def _read_description(page, source: str) -> tuple[str, str]:
    for sel in EXPAND_SELECTORS:  # expanding a collapsed description is the only click
        try:
            btn = page.locator(sel).first
            if btn.count() and btn.is_visible():
                btn.click(timeout=2000)
                break
        except Exception:  # noqa: BLE001, S110  (a missing selector is routine)
            pass
    for sel in DESCRIPTION_SELECTORS.get(source, []) + GENERIC_SELECTORS:
        try:
            el = page.locator(sel).first
            if el.count():
                text = el.inner_text(timeout=3000)
                if len(text.strip()) >= MIN_FULL_CHARS or sel in GENERIC_SELECTORS:
                    return text, el.evaluate("e => e.innerHTML")
        except Exception:  # noqa: BLE001, S112  (a missing selector is routine)
            continue
    return "", ""


def cmd_run(args) -> int:
    from playwright.sync_api import sync_playwright

    queue_dir: Path = args.queue_dir
    qfile = queue_dir / QUEUE_FILE
    if not qfile.exists():
        print(f"{qfile} is missing; run scripts/browser_queue.py sync first.")
        return 1
    listings = json.loads(qfile.read_text(encoding="utf-8"))["listings"]
    todo = choose(listings, queue_dir, args.per_site, set(args.sources) if args.sources else None)
    if not todo:
        print("Nothing to fill in: every queued listing already has a file.")
        return 0
    filled = failed = 0
    blocked: set[str] = set()
    with sync_playwright() as p:
        ctx = _launch(p, headless=args.headless)
        page = ctx.new_page()
        for r in todo:
            source = site_of(r)
            if source in blocked:
                continue
            try:
                page.goto(r["url"], wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(2500)
                text, html = _read_description(page, source)
                kind, why = classify_page(page.url, page.title(), text)
            except Exception as e:  # noqa: BLE001  (timeouts, dead links)
                kind, why, html = "gone", f"page did not load ({type(e).__name__})", ""
            if kind == "ok":
                (queue_dir / f"{r['id']}.md").write_text(html_to_markdown(html) + "\n", encoding="utf-8")
                filled += 1
            else:
                (queue_dir / f"{r['id']}.fail").write_text(why + "\n", encoding="utf-8")
                failed += 1
                if kind == "wall":
                    blocked.add(source)
                    print(f"{source}: {why} at job {r['id']}; skipping the rest of {source} this run.")
            print(f"{r['id']} {source}: {kind} {why}".rstrip())
            time.sleep(random.uniform(*PAUSE_SECONDS))
        ctx.close()
    print(f"Filled {filled}, failed {failed}. Now run: scripts/browser_queue.py sync")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--queue-dir", type=Path, default=QUEUE_DIR)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login", help="open the script's Chrome profile to sign in once")
    run = sub.add_parser("run", help="fill queued listings")
    run.add_argument("--per-site", type=int, default=DEFAULT_PER_SITE)
    run.add_argument("--sources", nargs="*", help="only these sites, e.g. linkedin glassdoor")
    run.add_argument("--headless", action="store_true", help="no window (sign-ins still apply; some sites dislike this)")
    args = ap.parse_args(argv)
    return cmd_login(args) if args.cmd == "login" else cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())

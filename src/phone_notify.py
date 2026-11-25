"""LinkedIn notifications forwarded from Jake's phone: find the job, fetch it, gate it, tailor it.

A phone app (MacroDroid, docs/phone-notifications.md) POSTs each LinkedIn notification's
title and text to the dashboard server (/api/phone-notify, a secret token in a header). The
server appends it to .phone-inbox/inbox.jsonl and a background thread (PhoneWatcher) works
through the inbox:

  1. Match. The notification has no link, so the job is found by its company and title: a job
     first seen in the last `match_days` days whose company AND title both appear in the text.
     No match yet = try again for `retry_hours` (the alert emails that bring the job into
     jobs.db arrive every couple of hours); after that it is dropped.
  2. Description. A job without a full description is tried over LinkedIn's public posting
     page (one plain fetch; it gives up quietly if LinkedIn asks for anything), and if that
     fails it goes to the front of the Chrome task's queue (.browser-queue/priority.json).
     Nothing here ever clicks or solves a bot check.
  3. Gate. The normal rules: tier in `tiers` (A/B), description long enough, not closed, not
     dismissed or applied, no application folder yet.
  4. Tailor. `run_tailoring.ps1 -JobId N`, at most `daily_cap` a day and never beside another
     run; a job past the cap waits for the daily run.

State per notification lives in .phone-inbox/state.json so a restart picks up where it was.
"""

from __future__ import annotations

import json
import re
import unicodedata
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from src.posting_status import closed_reason, seen_date

ROOT = Path(__file__).resolve().parent.parent
INBOX_DIR = ROOT / ".phone-inbox"
PRIORITY_FILE = ROOT / ".browser-queue" / "priority.json"

DEFAULTS: dict[str, Any] = {
    "daily_cap": 3,          # instant tailoring runs per day (Jake: usage limit)
    "tiers": ["A", "B"],
    "match_days": 21,        # how far back a job may have been first seen
    "retry_hours": 24,       # keep looking for a job that isn't in jobs.db yet
    "min_chars": 1000,       # a full description (tailor.min_description_chars)
}

# Words in a company name that don't tell companies apart.
_COMPANY_NOISE = {"inc", "ltd", "llc", "corp", "corporation", "co", "company", "limited", "the", "canada",
                  "group", "holdings", "international", "technologies", "solutions", "services"}


def _now() -> datetime:
    return datetime.now(UTC)


def norm(text: str) -> str:
    """Lower-case words only: accents, punctuation, curly quotes and spacing don't matter."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9+#]+", " ", text.lower()).split())


def _company_key(company: str) -> str:
    words = [w for w in norm(company).split() if w not in _COMPANY_NOISE]
    return " ".join(words)


def settings(cfg: dict[str, Any]) -> dict[str, Any]:
    out = dict(DEFAULTS)
    out.update(cfg.get("phone_notify") or {})
    out["min_chars"] = int((cfg.get("phone_notify") or {}).get("min_chars") or cfg.get("min_description_chars") or out["min_chars"])
    return out


# --- receiving ---------------------------------------------------------

def record(payload: dict[str, Any], inbox: Path | None = None) -> str:
    """Append one notification to the inbox; returns its id. Only the text fields are kept."""
    title = str(payload.get("title") or "")[:300]
    text = str(payload.get("text") or payload.get("body") or "")[:2000]
    if not (title or text).strip():
        raise ValueError("send title and/or text")
    inbox = inbox or INBOX_DIR
    now = _now()
    nid = now.strftime("%Y%m%dT%H%M%S%f")
    inbox.mkdir(parents=True, exist_ok=True)
    line = {"id": nid, "received_at": now.isoformat(timespec="seconds"), "title": title, "text": text}
    with (inbox / "inbox.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
    return nid


def read_inbox(inbox: Path | None = None) -> list[dict[str, Any]]:
    inbox = inbox or INBOX_DIR
    try:
        lines = (inbox / "inbox.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def read_state(inbox: Path | None = None) -> dict[str, Any]:
    inbox = inbox or INBOX_DIR
    try:
        data = json.loads((inbox / "state.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(state: dict[str, Any], inbox: Path | None = None) -> None:
    inbox = inbox or INBOX_DIR
    inbox.mkdir(parents=True, exist_ok=True)
    tmp = inbox / "state.json.tmp"
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    tmp.replace(inbox / "state.json")


# --- matching ----------------------------------------------------------

def find_job(conn, text: str, *, days: int = 21) -> dict[str, Any] | None:
    """The job a notification is about: company and title both appear in its text. With several,
    the longest title wins (so "Senior Data Analyst" beats "Data Analyst"), then the newest."""
    hay = f" {norm(text)} "
    since = (_now() - timedelta(days=days)).isoformat(timespec="seconds")
    rows = conn.execute(
        "SELECT id, source, external_id, title, company, tier, status, first_seen, "
        "length(description) AS chars FROM jobs WHERE first_seen >= ? AND status NOT IN ('expired')",
        (since,),
    ).fetchall()
    best: tuple[int, str, dict[str, Any]] | None = None
    for r in rows:
        company, title = _company_key(r["company"] or ""), norm(r["title"] or "")
        if len(company) < 3 or len(title) < 4:
            continue
        if f" {company} " in hay and f" {title} " in hay:
            cand = (len(title), str(r["first_seen"]), dict(r))
            if best is None or cand[:2] > best[:2]:
                best = cand
    return best[2] if best else None


# --- finding a job that is not in jobs.db yet ---------------------------

_AT_RE = re.compile(r"^\s*(?P<title>.+?)\s+at\s+(?P<company>.+?)(?:\s+and\s+\d+\s+more\b|\s+is\s+hiring\b|[.!?]|$)", re.I)


def parse_notification(text: str) -> tuple[str, str] | None:
    """(title, company) from "<title> at <company> ..." wording, else None. Only the first
    sentence-like chunk is read; a notification that does not name a job returns None."""
    for chunk in re.split(r"\n+", text.strip()):
        m = _AT_RE.match(chunk)
        if m and 4 <= len(m.group("title")) <= 120 and 2 <= len(m.group("company")) <= 80:
            return m.group("title").strip(), m.group("company").strip()
    return None


def search_linkedin(title: str, company: str, *, timeout: int = 15) -> dict[str, str] | None:
    """LinkedIn's public job search, one plain request: the card whose title and company both match
    exactly. Returns {external_id, title, company, location, url} or None; never retries or works
    around a block (a login wall or error just means None)."""
    import urllib.parse

    qs = urllib.parse.urlencode({"keywords": f"{title} {company}", "start": 0})
    url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobsFetch/search?{qs}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https host)
            html = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, ValueError):
        return None
    from bs4 import BeautifulSoup

    want_t, want_c = norm(title), _company_key(company)
    for card in BeautifulSoup(html, "html.parser").select("li, div.base-card"):
        t_el = card.select_one(".base-search-card__title")
        c_el = card.select_one(".base-search-card__subtitle")
        if t_el is None or c_el is None:
            continue
        if norm(t_el.get_text(" ")) != want_t or _company_key(c_el.get_text(" ")) != want_c:
            continue
        urn = card.get("data-entity-urn") or (card.select_one("[data-entity-urn]") or {}).get("data-entity-urn", "")
        link = card.select_one("a.base-card__full-link, a[href*='/jobs/view/']")
        href = link.get("href", "") if link else ""
        m = re.search(r"jobPosting:(\d+)", urn or "") or re.search(r"/jobs/view/(?:[^?/]*-)?(\d+)", href)
        if not m:
            continue
        loc = card.select_one(".job-search-card__location")
        return {"external_id": m.group(1), "title": t_el.get_text(" ", strip=True),
                "company": c_el.get_text(" ", strip=True),
                "location": loc.get_text(" ", strip=True) if loc else "",
                "url": f"https://www.linkedin.com/jobs/view/{m.group(1)}/"}
    return None


def add_found_job(conn, found: dict[str, str], description: str = "") -> int:
    """Store a job found by search_linkedin the way any scraped job is stored."""
    from src.db import Job, upsert_job

    row_id, _ = upsert_job(conn, Job(source="linkedin", external_id=found["external_id"], title=found["title"],
                                     company=found["company"], location=found["location"],
                                     description=description, url=found["url"],
                                     raw={"via": "phone-notification"}))
    conn.commit()
    return row_id


# --- description -------------------------------------------------------

def fetch_linkedin_description(external_id: str, *, timeout: int = 15) -> str:
    """LinkedIn's public posting page, one plain request. Returns "" for anything but a clean
    description: a login wall, a bot check, an error. It never retries or works around a block."""
    if not str(external_id).isdigit():
        return ""
    url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{external_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (fixed https host)
            html = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, ValueError):
        return ""
    from bs4 import BeautifulSoup

    node = BeautifulSoup(html, "html.parser").select_one(".show-more-less-html__markup, .description__text")
    if node is None:
        return ""
    for br in node.find_all("br"):
        br.replace_with("\n")
    for li in node.find_all("li"):
        li.insert_before("- ")
        li.append("\n")
    text = re.sub(r"\n{3,}", "\n\n", node.get_text("\n")).strip()
    return text


def prioritize(job_id: int, path: Path = PRIORITY_FILE) -> None:
    """Put a job at the front of the Chrome task's queue (browser_queue.export_queue reads this)."""
    try:
        ids = json.loads(path.read_text(encoding="utf-8"))
        ids = [int(i) for i in ids] if isinstance(ids, list) else []
    except (OSError, ValueError):
        ids = []
    if job_id not in ids:
        ids.append(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ids), encoding="utf-8")


def read_priority(path: Path = PRIORITY_FILE) -> list[int]:
    try:
        ids = json.loads(path.read_text(encoding="utf-8"))
        return [int(i) for i in ids] if isinstance(ids, list) else []
    except (OSError, ValueError, TypeError):
        return []


# --- gate --------------------------------------------------------------

def gate(conn, job_id: int, opts: dict[str, Any]) -> str:
    """"" when the job may be tailored right now, else why not."""
    r = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if r is None:
        return "job is gone"
    if r["tier"] not in opts["tiers"]:
        return f"tier {r['tier']} (only {'/'.join(opts['tiers'])} are tailored at once)"
    if r["status"] in ("dismissed", "applied", "expired"):
        return f"job is marked {r['status']}"
    if len(r["description"] or "") < opts["min_chars"]:
        return "description too short"
    if closed_reason(r["description"] or "", seen=seen_date(r["first_seen"]), raw=r["raw"]):
        return "posting looks closed"
    taken = conn.execute(
        "SELECT 1 FROM applications WHERE status != 'shortlisted' AND "
        "(job_id = ? OR job_id IN (SELECT id FROM jobs WHERE dedup_group_id = ?))",
        (job_id, r["dedup_group_id"]),
    ).fetchone()
    if taken:
        return "already has an application"
    return ""


# --- the pass ----------------------------------------------------------

def process(conn, cfg: dict[str, Any], *, inbox: Path | None = None, now: datetime | None = None,
            fetch: Callable[[str], str] = fetch_linkedin_description,
            search: Callable[[str, str], dict[str, str] | None] = search_linkedin,
            save: Callable[[Any, int, str], bool] | None = None,
            start_tailoring: Callable[[int], Any] | None = None,
            busy: Callable[[], bool] = lambda: False,
            priority_file: Path = PRIORITY_FILE,
            score_cfg: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """One pass over the inbox. Returns the state of every notification it touched."""
    from src import browser_queue

    inbox = inbox or INBOX_DIR
    opts = settings(cfg)
    now = now or _now()
    save = save or browser_queue.save
    state = read_state(inbox)
    touched: dict[str, dict[str, Any]] = {}
    today = now.astimezone().strftime("%Y-%m-%d")
    used_today = sum(1 for s in state.values() if s.get("started_on") == today)

    for n in read_inbox(inbox):
        st = state.setdefault(n["id"], {"status": "new"})
        if st["status"] in ("tailoring", "dropped", "skipped"):
            continue
        before = json.dumps(st, sort_keys=True)
        received = datetime.fromisoformat(n["received_at"])
        text = f"{n.get('title', '')} {n.get('text', '')}"

        if not st.get("job_id"):
            job = find_job(conn, text, days=int(opts["match_days"]))
            if job is None and not st.get("searched"):
                st["searched"] = True  # one LinkedIn search per notification, never a retry loop
                named = parse_notification(n.get("text", "")) or parse_notification(n.get("title", ""))
                found = search(*named) if named else None
                if found:
                    add_found_job(conn, found, fetch(found["external_id"]))
                    from src.score import rescore_all
                    from src.tailor.paths import _settings
                    rescore_all(conn, score_cfg if score_cfg is not None else _settings().get("score", {}))
                    conn.commit()
                    job = find_job(conn, text, days=int(opts["match_days"]))
                    if job:
                        st["found_by"] = "linkedin search"
            if job is None:
                if now - received > timedelta(hours=float(opts["retry_hours"])):
                    st.update(status="dropped", why="no matching job showed up in jobs.db")
                else:
                    st.update(status="waiting", why="job not in jobs.db yet; checking again")
                _keep(state, touched, n["id"], st, before)
                continue
            st.update(job_id=job["id"], title=job["title"], company=job["company"], source=job["source"])

        job_id = int(st["job_id"])
        row = conn.execute("SELECT source, external_id, length(description) AS chars FROM jobs WHERE id = ?",
                           (job_id,)).fetchone()
        if row is None:
            st.update(status="dropped", why="job is gone")
            _keep(state, touched, n["id"], st, before)
            continue

        if (row["chars"] or 0) < opts["min_chars"]:
            text_found = fetch(row["external_id"]) if row["source"] == "linkedin" and not st.get("fetched") else ""
            st["fetched"] = True
            if text_found:
                try:
                    save(conn, job_id, text_found)
                except ValueError:
                    text_found = ""
            row = conn.execute("SELECT length(description) AS chars FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if (row["chars"] or 0) < opts["min_chars"]:
                prioritize(job_id, priority_file)
                st.update(status="needs_description", why="description goes to the front of the Chrome queue")
                _keep(state, touched, n["id"], st, before)
                continue
            from src.score import rescore_all
            from src.tailor.paths import _settings
            rescore_all(conn, score_cfg if score_cfg is not None else _settings().get("score", {}))  # the tier depends on the description
            conn.commit()

        why = gate(conn, job_id, opts)
        if why:
            st.update(status="skipped", why=why)
        elif used_today >= int(opts["daily_cap"]):
            st.update(status="over_cap", why=f"{opts['daily_cap']} instant runs already today; the daily run will take it")
        elif start_tailoring is None or busy():
            st.update(status="queued", why="waiting for the running tailoring run to finish")
        else:
            start_tailoring(job_id)
            used_today += 1
            st.update(status="tailoring", why="tailoring started", started_on=today,
                      started_at=now.isoformat(timespec="seconds"))
        _keep(state, touched, n["id"], st, before)

    # Forget notifications older than two weeks.
    cutoff = now - timedelta(days=14)
    keep_ids = {n["id"] for n in read_inbox(inbox) if datetime.fromisoformat(n["received_at"]) >= cutoff}
    for k in [k for k in state if k not in keep_ids]:
        del state[k]
    write_state(state, inbox)
    return touched


def _keep(state, touched, nid, st, before) -> None:
    state[nid] = st
    if json.dumps(st, sort_keys=True) != before:
        touched[nid] = st


class PhoneWatcher:
    """Background thread in the dashboard server: wakes when a notification arrives and every
    minute after that, until each one is settled (a pending one is retried as the alert emails
    bring its job into jobs.db, or as the Chrome task fills its description)."""

    def __init__(self, app, *, interval: float = 60.0, inbox: Path | None = None) -> None:
        import threading

        self.app, self.interval, self.inbox = app, interval, inbox or INBOX_DIR
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="phone-watcher")

    def start(self) -> None:
        self._thread.start()

    def wake(self) -> None:
        self._wake.set()

    def _loop(self) -> None:
        import traceback

        from src.db import connect

        while True:
            self._wake.wait(self.interval)
            self._wake.clear()
            try:
                conn = connect(self.app.db_path)
                try:
                    done = process(conn, self.app.cfg, inbox=self.inbox,
                                   start_tailoring=self.app.runner.start_job,
                                   busy=lambda: bool(self.app.runner.status()["running"]))
                finally:
                    conn.close()
                for nid, st in done.items():
                    print(f"phone-notify {nid}: {st.get('status')} - {st.get('company', '')} / "
                          f"{st.get('title', '')} ({st.get('why', '')})", flush=True)
            except Exception:  # noqa: BLE001 (the thread must outlive one bad pass)
                traceback.print_exc()

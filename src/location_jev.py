"""Where is a "Canada"-only posting really based? Asked of Jev, not matched with patterns.

Some sources (Adzuna) give only "Canada" as the location, so the text of the posting is the
only place that says whether the job is in Vancouver, remote from Canada, or on-site in
Toronto or Raleigh, NC. Regexes over that text kept missing wordings, so a model reads it
(Jake, Nov 5 2026). Verdicts are cached by description hash, so each posting is asked once.
With no AI_GATEWAY_API_KEY (the Azure scrape job) or on any error there is no verdict, and
src.location_filter's pattern reading stays in charge.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from src.concurrency import parallel_map

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE = "materials/tailor/jev-location-cache.json"
MAX_CHARS = 8000

# Jev's choice -> classify_location category. "unclear" means: leave it to the patterns.
OPTIONS = ["vancouver", "remote_canada", "elsewhere", "unclear"]
CATEGORY = {"vancouver": "vancouver", "remote_canada": "remote", "elsewhere": "other"}
QUESTION_TEXT = "Where must the person in this job work?"
CRITERIA = (
    "vancouver = the work site is Vancouver or Metro Vancouver (Burnaby, Richmond, Surrey, "
    "Coquitlam, North Vancouver, ...), BC, Canada, including hybrid there. "
    "remote_canada = the job can be done remotely from Canada (fully remote, work from home, "
    "or remote anywhere in Canada or North America, with no US-residency requirement). "
    "elsewhere = on-site or hybrid in any other city, province, state or country (Toronto, "
    "Calgary, Raleigh NC, Fairfax VA, ...), a job site or company 'located in' a place "
    "outside Vancouver, a US-only role, or remote only for another country or region. "
    "unclear = the posting really does not say where the work is done. Mentioning a "
    "company's head office or an unrelated place does not decide it."
)


def key(description: str) -> str:
    return hashlib.sha1((description or "").strip().encode("utf-8")).hexdigest()


class VerdictCache:
    """description hash -> {"v": choice, "c": confidence}, one JSON file."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        try:
            self.data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}

    def get(self, k: str) -> dict | None:
        return self.data.get(k)

    def put(self, k: str, entry: dict) -> None:
        with self._lock:
            self.data[k] = entry

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=0), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass  # a cache that can't be written only costs a re-ask


def is_bare_country(location: str) -> bool:
    from src.location_filter import _BARE_COUNTRY

    return (location or "").strip().strip(".").lower() in _BARE_COUNTRY


def ask(client, description: str) -> dict | None:
    """One Jev call. None when it didn't answer (no key, error)."""
    from src.tailor.jev import Question

    q = Question("where", "choice", QUESTION_TEXT, options=OPTIONS, criteria=CRITERIA)
    ans = client.ask("Job posting:\n" + (description or "")[:MAX_CHARS], [q])[0]
    if not ans.ok:
        return None
    return {"v": ans.value, "c": ans.confidence}


def verdicts(rows: list[tuple[str, str]], cfg: dict[str, Any], client=None) -> dict[str, str]:
    """Category ("vancouver" | "remote" | "other") by description hash for the (location,
    description) pairs that are bare-country and have a text. Pairs Jev hasn't answered, or
    answered "unclear" / under min_confidence, are left out."""
    jcfg = cfg.get("jev_location") or {}
    if not jcfg.get("enabled", False):
        return {}
    cache = VerdictCache(ROOT / jcfg.get("cache", DEFAULT_CACHE))
    todo: dict[str, str] = {}
    for location, desc in rows:
        if desc and is_bare_country(location):
            k = key(desc)
            if cache.get(k) is None:
                todo[k] = desc
    if todo:
        if client is None:
            from src.tailor.jev import JevClient

            client = JevClient.from_env({})
        if client.available:
            keys = list(todo)
            limit = jcfg.get("max_new_per_run", 400)
            answers = parallel_map(lambda k: ask(client, todo[k]), keys[:limit], 4)
            for k, entry in zip(keys, answers):
                if entry is not None:
                    cache.put(k, entry)
            cache.save()
    min_conf = jcfg.get("min_confidence", 0.6)
    out: dict[str, str] = {}
    for location, desc in rows:
        entry = cache.get(key(desc)) if desc and is_bare_country(location) else None
        if entry and entry.get("v") in CATEGORY and (entry.get("c") is None or entry["c"] >= min_conf):
            out[key(desc)] = CATEGORY[entry["v"]]
    return out

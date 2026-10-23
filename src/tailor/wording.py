"""One answer to "is this the same wording?", used by every step that compares text.

Evidence (does a vault passage use the posting's term?), the check (is a draft's
skill wording in the vault?) and the grade (is the posting's term in the draft?)
all ask this question. Each used to have its own matcher, so each new variant
(a plural, a British spelling, a hyphen) was fixed in one place and broke in the
next. They now all build their pattern here.

Two strictness levels:

- `same(words, text)`: for truth checks. Plurals, hyphen/space and US/British
  spelling don't change the wording: the vault's "data modelling" backs a
  draft's "data modeling".
  Wordings in one `EQUIVALENTS` group also count as the same: they name one thing
  ("KPIs" and "metrics"), so the vault saying one backs a draft saying the other.
- `ats(words, text)`: for the ATS score. Plurals and hyphen/space still count
  as the same word (ATSs stem and tokenize), but spelling is exact, as a real
  ATS keyword search is.
"""

from __future__ import annotations

import re
from functools import lru_cache

# British/Canadian -> US spellings, applied to both sides by `same`.
_US_SPELLING = [
    (re.compile(r"(?<=e)ll(?=ing|ed|ers?\b)", re.I), "l"),            # modelling, labelled
    (re.compile(r"(?<=[a-z]{2})our(?=s?\b|ed\b|ing\b|al\b|ite\b|able\b)", re.I), "or"),  # colour, behaviour
    (re.compile(r"(?<=[a-z]{2})tre(?=s?\b)", re.I), "ter"),            # centre, metre
    (re.compile(r"(?<=ly)s(?=e|es|ed|ing|ers?\b)", re.I), "z"),         # analyse
    (re.compile(r"(?<=[a-z]{3})is(?=e\b|es\b|ed\b|ing\b|ations?\b|ers?\b)", re.I), "iz"),  # optimise, visualisation
    (re.compile(r"(?<=program)me(?=s?\b)", re.I), ""),                 # programme
]

# A phrase's words may be joined by spaces or a hyphen ("data-driven" / "data driven").
_JOIN = r"[\s\-]+"
_EDGE_BEFORE = r"(?<![\w+#])"
_EDGE_AFTER = r"(?![\w+#])"


def us_spelling(text: str) -> str:
    """`text` with British/Canadian spellings turned into US ones."""
    for rx, repl in _US_SPELLING:
        text = rx.sub(repl, text)
    return text


def _last_word(word: str) -> str:
    """Pattern for a phrase's last word that also matches its singular/plural."""
    if len(word) >= 2 and word.isalpha() and word.isupper():
        return re.escape(word) + "s?"  # "API" / "APIs", "LLM" / "LLMs"
    if len(word) <= 3 or not word[-1:].isalpha():
        return re.escape(word)
    # Every way the word could be a plural: "pipelines" = pipeline + s, "boxes" = box + es.
    stems = [word]
    if word[-1] in "sS" and word[-2:-1].isalpha():
        stems.append(word[:-1])
        if word[-2:].lower() == "es":
            stems.append(word[:-2])
    return "(?:" + "|".join(re.escape(s) for s in stems) + ")(?:e?s)?"


@lru_cache(maxsize=4096)
def pattern(words: str, spelling_blind: bool = False) -> re.Pattern[str]:
    """Compiled whole-phrase pattern for `words` (see the module docstring)."""
    words = words.strip()
    if spelling_blind:
        words = us_spelling(words)
    parts = re.split(r"[\s\-]+", words)
    body = _JOIN.join([re.escape(p) for p in parts[:-1]] + [_last_word(parts[-1])])
    return re.compile(_EDGE_BEFORE + body + _EDGE_AFTER, re.I)


# Wordings that mean exactly the same thing (Jake, Oct 23 2026). Only true equivalents belong here:
# a word whose meaning shifts from job to job ("insights", "trends") needs a vault line instead.
EQUIVALENTS = [
    ("KPI", "key performance indicator", "metrics"),
    ("data analytics", "data analysis"),
]


def _equivalents(words: str) -> list[str]:
    key = us_spelling(words.strip()).lower()
    for group in EQUIVALENTS:
        if any(pattern(g, True).fullmatch(key) for g in group):
            return list(group)
    return []


def same(words: str, text: str) -> bool:
    """`text` uses `words` as a phrase, ignoring plural, hyphen/space and spelling; a wording in
    the same `EQUIVALENTS` group counts too."""
    if not words.strip():
        return False
    text = us_spelling(text)
    return any(pattern(w, True).search(text) for w in [words, *_equivalents(words)])


def ats(words: str, text: str) -> bool:
    """`text` contains `words` the way an ATS keyword search would find it."""
    if not words.strip():
        return False
    return bool(pattern(words).search(text))


def count(words: str, text: str) -> int:
    """How many times `text` uses `words` (ATS strictness)."""
    if not words.strip():
        return 0
    return len(pattern(words).findall(text))

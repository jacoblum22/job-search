"""One answer to "is this the same wording?", used by every step that compares text.

Evidence (does a vault passage use the posting's term?), the check (is a draft's
skill wording in the vault?) and the grade (is the posting's term in the draft?)
all ask this question. Each used to have its own matcher, so each new variant
(a plural, a British spelling, a hyphen) was fixed in one place and broke in the
next. They now all build their pattern here.

Two strictness levels:

- `same(words, text)`: for truth checks. Plurals, hyphen/space, US/British
  spelling and "MS" for "Microsoft" don't change the wording: the vault's
  "data modelling" backs a draft's "data modeling". Nor does the form of an
  -ize/-ate verb: the vault's "optimized" backs the posting's "optimizing".
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


# "MS" is short for "Microsoft" only in front of a Microsoft product ("MS Office", "MS Excel"); an
# "MS in Statistics" is a degree. Amazon ICQA, Oct 27 2026: a product spelled out in the vault didn't
# back the same product abbreviated in a draft.
_MS = re.compile(r"\bMS(?=[\s\-]+(?:Office|Excel|Word|PowerPoint|Outlook|Access|Teams|Project|Visio|SharePoint"
                 r"|SQL|Azure|Dynamics|Power\s*BI|365)\b)", re.I)


# A standalone "&" is "and" ("Algorithms & Data Structures"); "R&D" and "AT&T" are left alone.
# Quora ML platform, Oct 30 2026: the vault's course name with "and" didn't back the draft's "&".
_AMP = re.compile(r"\s+&\s+")


def _blind(text: str) -> str:
    """`text` as `same` compares it: US spelling, "MS" spelled out before a Microsoft product,
    and "&" read as "and"."""
    return _AMP.sub(" and ", _MS.sub("Microsoft", us_spelling(text)))


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


# Regular -ize and -ate verbs and their -ation/-ion nouns: "optimizing", "optimized" and
# "optimization" name one act. Nexthop new grad, Oct 27 2026: the posting's "optimizing" found
# no passage though the vault says "Optimized for 16GB VRAM" and "model size optimization".
_VERB_FAMILIES = [
    (re.compile(r"^([a-z]{4,}iz)(?:e|es|ed|ing|ations?)$", re.I), "(?:e|es|ed|ing|ations?)"),
    (re.compile(r"^([a-z]{4,}at)(?:e|es|ed|ing|ions?)$", re.I), "(?:e|es|ed|ing|ions?)"),
]


def _verb_forms(word: str) -> str | None:
    """Pattern for every form of an -ize/-ate verb `word` (see `_VERB_FAMILIES`), or None."""
    for rx, ends in _VERB_FAMILIES:
        m = rx.match(word)
        if m:
            return re.escape(m.group(1)) + ends
    return None


@lru_cache(maxsize=4096)
def pattern(words: str, spelling_blind: bool = False) -> re.Pattern[str]:
    """Compiled whole-phrase pattern for `words` (see the module docstring). Spelling-blind
    patterns also take the other forms of an -ize/-ate verb (`_verb_forms`)."""
    words = words.strip()
    if spelling_blind:
        words = _blind(words)
    parts = re.split(r"[\s\-]+", words)
    last = (spelling_blind and _verb_forms(parts[-1])) or _last_word(parts[-1])
    body = _JOIN.join([re.escape(p) for p in parts[:-1]] + [last])
    return re.compile(_EDGE_BEFORE + body + _EDGE_AFTER, re.I)


# Wordings that mean exactly the same thing (Jake, Oct 23 2026). Only true equivalents belong here:
# a word whose meaning shifts from job to job ("insights", "trends") needs a vault line instead.
EQUIVALENTS = [
    ("KPI", "key performance indicator", "metrics"),
    ("data analytics", "data analysis"),
]


def _equivalents(words: str) -> list[str]:
    key = _blind(words.strip()).lower()
    for group in EQUIVALENTS:
        if any(pattern(g, True).fullmatch(key) for g in group):
            return list(group)
    return []


def same(words: str, text: str) -> bool:
    """`text` uses `words` as a phrase, ignoring plural, hyphen/space and spelling; a wording in
    the same `EQUIVALENTS` group counts too."""
    if not words.strip():
        return False
    text = _blind(text)
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

"""Find tools a posting lists as alternatives ("Superset, Looker, Tableau, or Power BI").

A posting that asks for one of several tools should count as a gap only when the
candidate has none of them. This module reads the list itself, not just the skills
it recognises: every comma-separated item is an option, whether or not the skills
taxonomy knows it, so "Stata, R, or Python" is three options even though Stata isn't
in the taxonomy. A list counts as a choice when its last item follows an "or"
("Python, R, or Java"), or when it follows an examples cue and ends openly ("such
as TensorFlow, PyTorch, etc", "(e.g. AWS, GCP)"). A list closed by a plain "and" is
separate asks. An item that only gestures at more ("or similar tools") marks the
list as open-ended instead of being an option.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from itertools import pairwise

from src.tailor import taxonomy

# Clauses end at sentence punctuation, semicolons, colons and line breaks, and at
# inline bullets (" - ", " · ", " • ", " * ") in postings flattened onto one line.
_CLAUSE = re.compile(r"(?:[^\n.;:!?·•*-]|\.(?=\w)|(?<!\s)-|-(?!\s))+")
# Abbreviations whose dots don't end a clause; masked with same-length text before splitting.
_ABBREV = re.compile(r"\b(?:e\.g|i\.e|etc|vs|incl)\.", re.IGNORECASE)
# The conjunction before a list's last item.
_LAST_OR = re.compile(r"(?:,\s*)?\b(?:and/or|or)\s+", re.IGNORECASE)
# Lead-ins: the first item starts after the last of these in its segment.
_LEAD = re.compile(r"(?:\b(?:such as|like|including|includes|eg|for example|for instance|but not limited to|"
                   r"one of|any of|with|in|of|on|using|use|from|across|via|through|to|either|especially|particularly)\b|"
                   r"\be\.g\b\.?|\bi\.e\b\.?|[(:]|^\s*\+)"
                   r"[\s,]*", re.IGNORECASE)
# Starts of an examples list: "such as", "(e.g.,", "including".
_CUE_START = re.compile(r"(?:\b(?:such as|eg|like|including|one of|any of|at least one of|one or more of|"
                        r"for example|for instance)\b|\be\.g\.)[\s,]*", re.IGNORECASE)
# Subjects of study: lists of these after a degree word are about degrees, not tools.
_DEGREE = re.compile(r"\b(?:degree|bachelor|master|phd|ph\.d|diploma|major|studies|background in|enrolled)", re.IGNORECASE)
_FIELD = re.compile(r"^(?:computer science|(?:\w+ )?engineering|mathematics|math|statistics|physics|economics|finance|"
                    r"data science|information systems|business(?: administration)?|accounting|operations research|"
                    r"machine learning|artificial intelligence|ai|bi|actuarial science|commerce|econometrics)$",
                    re.IGNORECASE)
_FIELD_WORD = re.compile(r"\b(?:field|discipline|degree|program|major)s?\b", re.IGNORECASE)
# Words that end the last item: "Power BI is an asset", "Python for tools and testing".
_ITEM_END = re.compile(r"\s+(?:is|are|was|for|to|in|on|at|with|within|as|that|which|who|when|where|while|"
                       r"and|or|experience|skills?|knowledge|expertise|proficiency|preferred|required|"
                       r"strongly|would|will|a plus|an asset|including|before|after|such|preferred|acceptable|especially|"
                       r"programming|development|languages?|frameworks?|tools|platforms?|concepts|use cases|"
                       r"technologies|databases|software|systems?|solutions?)\b|[(),]|\s+[–—-]\s", re.IGNORECASE)
# Words a posting adds to an item that aren't part of its name ("FastAPI preferred").
_ITEM_NOISE = re.compile(r"\s+(?:preferred|acceptable|required|a plus|an asset|strongly preferred)$|^\+\s*",
                         re.IGNORECASE)
# An item that stands for "anything like the others" rather than a named option.
_OPEN_ITEM = re.compile(r"^(?:other|another|any|similar|equivalent|comparable|related|a similar|a comparable|"
                        r"an equivalent|the like|etc|others)\b", re.IGNORECASE)
_MAX_WORDS = 4
# Catch-all skills that overlap a more specific one ("AI/ML") never count as a known item.
_SKIP = {"AI (any mention)"}
# Skills that name a kind of work rather than a tool. A list needs two tool options to count:
# "reports, dashboards, or analyses" is a list of outputs, not a choice of tools.
_CONCEPT_CATEGORIES = {"ML & statistics", "Soft skills", "Credentials"}
_CONCEPTS = {"dashboards", "data visualization", "reporting", "KPIs/metrics", "A/B testing / experimentation",
             "ETL/ELT", "data pipelines", "data warehouse", "data modeling", "data quality / validation",
             "data governance", "APIs / REST", "microservices", "distributed systems", "MLOps",
             "testing (unit/automated)", "SDLC", "QA / UAT", "project management", "Agile/Scrum", "GIS"}


def _is_tool(name: str) -> bool:
    return name not in _CONCEPTS and taxonomy.category(name) not in _CONCEPT_CATEGORIES


@dataclass(frozen=True)
class Item:
    text: str  # as the posting wrote it ("Stata", "Tableau Desktop", "LLM APIs")
    skills: tuple[str, ...]  # taxonomy skills it names, if any


@dataclass(frozen=True)
class Group:
    items: tuple[Item, ...]
    reason: str  # "or" (an "or" before the last item) or "cue" (a "such as"-style lead-in)
    open_end: bool  # the list ends with "or similar", "etc" or the like
    text: str  # the clause, for review

    @property
    def options(self) -> tuple[str, ...]:
        return tuple(i.text for i in self.items)

    @property
    def skills(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(s for i in self.items for s in i.skills))


def _hits(clause: str) -> list[tuple[int, int, str]]:
    """Hard-skill mentions in the clause; matched on the whole clause because some patterns
    need context ("C" counts only in a list like "C, C++, Java")."""
    return [(m.start(), m.end(), name) for _, name, rx in taxonomy.compiled()
            if taxonomy.is_hard(name) and name not in _SKIP for m in rx.finditer(clause)]


def _item(clause: str, a: int, b: int, hits: list[tuple[int, int, str]]) -> Item | None:
    text = " ".join(clause[a:b].strip(" ,").split())
    text = re.sub(r"^(?:and|or|and/or)\s+", "", text, flags=re.IGNORECASE)
    text = _ITEM_NOISE.sub("", text).strip()
    if not text or len(text.split()) > _MAX_WORDS:
        return None
    return Item(text, tuple(sorted({n for s, e, n in hits if a <= s and e <= b})))


def _first_start(clause: str, a: int, b: int) -> tuple[int, bool]:
    """Where a list's first item starts in segment [a, b), and whether a lead-in started it."""
    seg = clause[a:b]
    leads = list(_LEAD.finditer(seg))
    if leads:
        a += leads[-1].end()
    # "SQL and Python or R": the list is Python or R; SQL is its own ask.
    ands = list(re.finditer(r"\s+(?:and|&)\s+", clause[a:b], re.IGNORECASE))
    if ands:
        a += ands[-1].end()
    return a, bool(leads)


def _list_before(clause: str, end: int) -> list[tuple[int, int]]:
    """Spans of the comma-separated items that end at `end`, walking left until a lead-in,
    a long segment or an "and"."""
    cuts = [-1] + [i for i, ch in enumerate(clause[:end]) if ch == ","] + [end]
    spans: list[tuple[int, int]] = []
    for a, b in reversed(list(pairwise(cuts))):
        a += 1
        seg = clause[a:b]
        if ")" in seg:
            break  # a closed bracket isn't part of this list
        first, led = _first_start(clause, a, b)
        if led or len(seg.split()) > _MAX_WORDS or re.search(r"\s(?:and|&)\s", seg, re.IGNORECASE):
            spans.append((first, b))
            break
        spans.append((a, b))
    spans.reverse()
    return spans


def _is_fields_of_study(items: list[Item], clause: str) -> bool:
    """ "a degree in Statistics, Computer Science, or a related field" lists subjects, not tools."""
    if any(_FIELD_WORD.search(i.text) for i in items):
        return True
    return bool(_DEGREE.search(clause)) and sum(bool(_FIELD.match(i.text)) for i in items) >= 2


def _or_lists(clause: str, hits: list[tuple[int, int, str]]) -> list[Group]:
    out = []
    for m in _LAST_OR.finditer(clause):
        if clause[:m.start()].rstrip().endswith(")"):
            continue  # "(e.g. PyTorch, TensorFlow) and/or distributed systems" joins two asks
        cut = _ITEM_END.search(clause, m.end())
        spans = [*_list_before(clause, m.start()), (m.end(), cut.start() if cut else len(clause))]
        items = [i for i in (_item(clause, a, b, hits) for a, b in spans) if i]
        if _is_fields_of_study(items, clause):
            continue
        open_end = bool(items) and bool(_OPEN_ITEM.match(items[-1].text))
        items = [i for i in items if not _OPEN_ITEM.match(i.text)]
        if len(items) >= 2 and sum(any(map(_is_tool, i.skills)) for i in items) >= 2:
            out.append(Group(tuple(items), "or", open_end, " ".join(clause.split())))
    return out


def _cue_lists(clause: str, hits: list[tuple[int, int, str]]) -> list[Group]:
    """A cue, then items joined only by commas, then an open end: "(e.g. AWS, GCP)", "like X, Y, etc"."""
    out = []
    for m in _CUE_START.finditer(clause):
        stop = re.compile(r"\)|\betc\b|\band so on\b", re.IGNORECASE).search(clause, m.end())
        if not stop or re.search(r"\b(?:and|or)\b|[&(]", clause[m.end():stop.start()], re.IGNORECASE):
            continue  # an "and" closes the list; an "or" list is read by _or_lists
        cuts = [m.end() - 1] + [i for i in range(m.end(), stop.start()) if clause[i] == ","] + [stop.start()]
        items = [i for i in (_item(clause, a + 1, b, hits) for a, b in pairwise(cuts)) if i]
        if len(items) >= 2 and sum(any(map(_is_tool, i.skills)) for i in items) >= 2 and not _is_fields_of_study(items, clause):
            out.append(Group(tuple(items), "cue", True, " ".join(clause.split())))
    return out


def alternative_groups(text: str) -> list[Group]:
    groups: list[Group] = []
    text = html.unescape(text or "")  # "Bachelor&#39;s" would split a clause at its ";"
    masked = _ABBREV.sub(lambda m: m.group(0).replace(".", "_"), text)
    for cm in _CLAUSE.finditer(masked):
        clause = text[cm.start():cm.end()]
        hits = _hits(clause)
        groups += _or_lists(clause, hits) + _cue_lists(clause, hits)
    return groups

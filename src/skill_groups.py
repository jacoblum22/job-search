"""Find tools a posting lists as alternatives ("Superset, Looker, Tableau, or Power BI").

A posting that asks for one of several tools should count as a gap only when the
candidate has none of them. This module reads the list itself, not just the skills
it recognises: every comma-separated item is an option, whether or not the skills
taxonomy knows it, so "Stata, R, or Python" is three options even though Stata isn't
in the taxonomy. A list counts as a choice when its last item follows an "or"
("Python, R, or Java"), when it follows an examples cue ("such as TensorFlow, PyTorch,
etc", "(e.g. AWS, GCP)", "such as R, SAS and Matlab"; "including X and Y" lists
parts that are all wanted unless it ends openly), or when it ends in "etc"
("Redshift, Oracle, NoSQL etc."): examples stand for a kind of tool, so one is
enough. Any other list closed by a plain "and" is separate asks. An item that only gestures at more ("or similar tools") marks the
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
_ITEM_END = re.compile(r"\s+(?:is|are|was|for|to|in|on|at|with|within|throughout|during|across|into|by|as|that|which|who|when|where|while|"
                       r"and|or|experience|skills?|knowledge|expertise|proficiency|preferred|required|"
                       r"strongly|would|will|a plus|an asset|including|before|after|such|preferred|acceptable|especially|"
                       r"programming|development|languages?|frameworks?|tools|platforms?|concepts|use cases|"
                       r"technologies|databases|software|systems?|solutions?)\b|[(),]|\s+[–—-]\s", re.IGNORECASE)
# Words a posting adds to an item that aren't part of its name ("FastAPI preferred").
_ITEM_NOISE = re.compile(r"\s+(?:preferred|acceptable|required|a plus|an asset|strongly preferred)$|^\+\s*"
                         r"|^(?:proficient|proficiency|experienced?|expertise|knowledge|familiar(?:ity)?|skilled|"
                         r"fluent|fluency|comfortable|strong|advanced|working knowledge)\s+(?:in|with|of|using)\s+",
                         re.IGNORECASE)
# The kind of thing a list names, just before its cue: "visualization tools (e.g. Excel, ...)".
_BEFORE_CUE = re.compile(r"(?:\b(?:such as|like|including|e\.g\b\.?|for example)|\()[\s,(]*"
                         r"(?:\b(?:such as|like|including|e\.g\b\.?)[\s,]*)?$", re.IGNORECASE)
_NOT_CATEGORY = {"in", "of", "with", "using", "use", "more", "the", "any", "all", "and", "or", "a", "an", "one",
                 "to", "on", "for", "experience", "proficiency", "knowledge", "familiarity", "skills"}
# An item that stands for "anything like the others" rather than a named option.
_OPEN_ITEM = re.compile(r"^(?:other|another|any|similar|equivalent|comparable|related|a similar|a comparable|"
                        r"an equivalent|the like|etc|others)\b", re.IGNORECASE)
# Where an examples list after a cue stops: a bracket, "etc", or the conjunction before its last item.
_CUE_END = re.compile(r"\)|\betc\b|\band so on\b|\band/or\b|\bor\b|\s(?:and|&)\s(?!so on\b)|\(", re.IGNORECASE)
# "Including" names the parts of something; with a closing "and" those parts are all wanted.
_PARTS_CUE = re.compile(r"includ", re.IGNORECASE)
_ETC = re.compile(r",?\s*\b(?:etc\b|and so on\b)", re.IGNORECASE)
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
    reason: str  # "or" (an "or" before the last item), "cue" (a "such as"-style lead-in) or "etc"
    open_end: bool  # the list ends with "or similar", "etc" or the like
    text: str  # the clause, for review
    category: str | None = None  # what the list is a list of, when the posting says ("visualization tools")
    category_skills: tuple[str, ...] = ()  # taxonomy skills that wording names ("data visualization")

    @property
    def options(self) -> tuple[str, ...]:
        return tuple(i.text for i in self.items)

    @property
    def skills(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(s for i in self.items for s in i.skills))

    @property
    def tool_type(self) -> str | None:
        """The type most of the named tools share (two thirds of the known ones, at least two),
        taken from the tools themselves, so the posting's wording doesn't matter."""
        known = [{t for s in i.skills for t in taxonomy.TOOL_TYPES.get(s, ())} for i in self.items]
        known = [k for k in known if k]
        counts: dict[str, int] = {}
        for k in known:
            for t in k:
                counts[t] = counts.get(t, 0) + 1
        need = max(2, -(-2 * len(known) // 3))
        best = sorted((n, t) for t, n in counts.items() if n >= need)
        return best[-1][1] if best else None


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


def _category(clause: str, start: int) -> tuple[str | None, tuple[str, ...]]:
    """The words naming a list's kind, before a cue like "such as" or "(e.g." that starts it."""
    m = _BEFORE_CUE.search(clause[:start])
    if not m:
        return None, ()
    words = clause[:m.start()].split()[-_MAX_WORDS:]
    while words and words[0].lower().strip(",") not in _NOT_CATEGORY and any(
            w.lower().strip(",") in _NOT_CATEGORY for w in words[1:]):
        words = words[1:]
    while words and words[0].lower().strip(",") in _NOT_CATEGORY:
        words = words[1:]
    text = " ".join(words).strip(" ,")
    if not text:
        return None, ()
    return text, tuple(sorted(n for n in taxonomy.find(text) if n not in _SKIP))


def _list_before(clause: str, end: int, hits: list[tuple[int, int, str]]) -> list[tuple[int, int]]:
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
        if not led and len(clause[first:b].split()) > _MAX_WORDS:
            # A long lead-in we don't recognise ("projects involving Microsoft 365"): the item
            # starts at the first skill in its last few words, if there is one.
            tail = b - len(" ".join(clause[first:b].split()[-_MAX_WORDS:]))
            first = min((h[0] for h in hits if tail - 1 <= h[0] < b), default=b)
        if led or len(seg.split()) > _MAX_WORDS or re.search(r"\s(?:and|&)\s", seg, re.IGNORECASE):
            if first < b:
                spans.append((first, b))
            break
        if a == 0:
            # The clause's first words lead into the list ("projects involving Microsoft 365"):
            # the item starts at its first skill.
            a = min((h[0] for h in hits if a <= h[0] < b), default=a)
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
        spans = [*_list_before(clause, m.start(), hits), (m.end(), cut.start() if cut else len(clause))]
        items = [i for i in (_item(clause, a, b, hits) for a, b in spans) if i]
        if _is_fields_of_study(items, clause):
            continue
        open_end = bool(items) and bool(_OPEN_ITEM.match(items[-1].text))
        items = [i for i in items if not _OPEN_ITEM.match(i.text)]
        if len(items) >= 2 and sum(any(map(_is_tool, i.skills)) for i in items) >= 2:
            out.append(Group(tuple(items), "or", open_end, " ".join(clause.split()),
                             *_category(clause, spans[0][0])))
    return out


def _cue_lists(clause: str, hits: list[tuple[int, int, str]]) -> list[Group]:
    """A cue, then examples: "(e.g. AWS, GCP)", "like X, Y, etc", "such as R, SAS and Matlab".
    Examples stand for a kind of tool, so having one of them is enough, even when the
    list closes with "and"."""
    out = []
    for m in _CUE_START.finditer(clause):
        stop = _CUE_END.search(clause, m.end())
        word = stop.group(0).strip().lower() if stop else ""
        if word in ("or", "and/or", "("):
            continue  # an "or" list is read by _or_lists
        end = stop.start() if stop else len(clause)
        cuts = [m.end() - 1] + [i for i in range(m.end(), end) if clause[i] == ","] + [end]
        spans = [(a + 1, b) for a, b in pairwise(cuts)]
        open_end = word in (")", "etc", "and so on")
        if word in ("and", "&") or not stop:
            if word:
                spans.append((stop.end(), len(clause)))
            # The last item ends where the sentence moves on: "and Matlab to build models".
            a, b = spans[-1]
            cut = _ITEM_END.search(clause, a)
            if cut and cut.start() < b:
                spans[-1] = (a, cut.start())
            open_end = bool(re.match(r"[\s,]*(?:etc\b|and so on\b|(?:and/)?or (?:other|similar|equivalent|comparable)\b)",
                                     clause[spans[-1][1]:], re.IGNORECASE))
        items = [i for i in (_item(clause, a, b, hits) for a, b in spans) if i]
        if items and _OPEN_ITEM.match(items[-1].text):
            open_end = True  # "including Copilot, Claude Code, and similar tools"
        items = [i for i in items if not _OPEN_ITEM.match(i.text)]
        if word in ("and", "&") and _PARTS_CUE.match(m.group(0)) and not open_end:
            continue  # "a stack including Docker and Kubernetes" lists the parts it uses, all of them
        if len(items) >= 2 and sum(any(map(_is_tool, i.skills)) for i in items) >= 2 and not _is_fields_of_study(items, clause):
            out.append(Group(tuple(items), "cue", open_end, " ".join(clause.split()), *_category(clause, m.end())))
    return out


def _etc_lists(clause: str, hits: list[tuple[int, int, str]]) -> list[Group]:
    """A comma list that ends in "etc" or "and so on" with no cue before it: "Redshift, Oracle,
    NoSQL etc." names examples, so having one is enough."""
    out = []
    for m in _ETC.finditer(clause):
        spans = _list_before(clause, m.start(), hits)
        items = [i for i in (_item(clause, a, b, hits) for a, b in spans) if i]
        items = [i for i in items if not _OPEN_ITEM.match(i.text)]
        if len(items) >= 2 and sum(any(map(_is_tool, i.skills)) for i in items) >= 2 and not _is_fields_of_study(items, clause):
            out.append(Group(tuple(items), "etc", True, " ".join(clause.split()), *_category(clause, spans[0][0])))
    return out


def alternative_groups(text: str) -> list[Group]:
    groups: list[Group] = []
    text = html.unescape(text or "")  # "Bachelor&#39;s" would split a clause at its ";"
    masked = _ABBREV.sub(lambda m: m.group(0).replace(".", "_"), text)
    for cm in _CLAUSE.finditer(masked):
        clause = text[cm.start():cm.end()]
        hits = _hits(clause)
        found: list[Group] = []
        for g in _or_lists(clause, hits) + _cue_lists(clause, hits) + _etc_lists(clause, hits):
            # A list read twice ("such as X, Y etc" is a cue list and an etc list) counts once.
            if not any(set(g.options) <= set(f.options) for f in found):
                found.append(g)
        groups += found
    return groups

"""Find skills a posting lists as alternatives ("QuickSight, Tableau or Power BI").

A posting that asks for one of several tools should count as a gap only when the
candidate has none of them. This module finds runs of taxonomy skills in one
clause (a sentence or bullet) joined only by separators, and keeps the runs that
read as a choice: an "or" between them ("Python, R, or Java"), or an examples cue
before them with an open end ("such as TensorFlow, PyTorch, etc"). Runs ending in
"and" are separate asks. Skills joined by only a space or a slash are one option,
not two: "LLM APIs" or "Azure Machine Learning" is a single thing to have, and
"TypeScript/JavaScript" is one choice in "TypeScript/JavaScript, Java, or Go".
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
# Text allowed between two skills in a run.
# Brackets end a run: "(PyTorch, TensorFlow) and/or distributed systems" is two asks.
_SEP = re.compile(r"^[\s,]*(?:(?:and/or|or|and|&|/)[\s,]*)?$", re.IGNORECASE)
# A comma list may hold a word the taxonomy doesn't know: "Tableau Desktop, QuickSight",
# "Excel, MicroStrategy, Power BI". Up to two words may trail a skill or sit between commas.
_WORD = r"(?!(?:and|or|with|using|in|for|to|of|on)\b)[\w+#.-]+"
_LOOSE = re.compile(rf"^(?:\s+{_WORD}){{0,2}}\s*,(?:\s*{_WORD}(?:\s+{_WORD})?\s*,)*"
                    r"\s*(?:(?:and/or|or|and|&)\s+)?$", re.IGNORECASE)
# An "or" right after the last skill keeps the list open: "Tableau, QuickSight, or similar tools".
_TAIL_OR = re.compile(r"^\s*,?\s*(?:and/)?or\b", re.IGNORECASE)
# Abbreviations whose dots don't end a clause; masked with same-length text before splitting.
_ABBREV = re.compile(r"\b(?:e\.g|i\.e|etc|vs|incl)\.", re.IGNORECASE)
_OR = re.compile(r"\bor\b", re.IGNORECASE)
_AND = re.compile(r"\band\b|&", re.IGNORECASE)
# After an examples cue, a run that ends openly is a choice of examples.
_OPEN_END = re.compile(r"^\s*,?\s*(?:\)|etc\b|and so on|or (?:similar|equivalent|other|comparable|related)\b|"
                       r"and/or similar|or the like)", re.IGNORECASE)
# Catch-all skills that overlap a more specific one ("AI/ML") never form a group.
_SKIP = {"AI (any mention)"}
_CUE = re.compile(r"\b(?:such as|e\.g\.?|eg\.|like|including|one of|any of|at least one of|"
                  r"one or more of|similar to|for example|for instance)\s*[,(]?\s*$", re.IGNORECASE)


# Skills with only this between them are one option ("LLM APIs", "Docker/Kubernetes").
_JOINED = re.compile(r"^\s*/?\s*$")


@dataclass(frozen=True)
class Group:
    options: tuple[tuple[str, ...], ...]  # each option is one skill, or a few named together
    reason: str  # "or" (an "or" joins them) or "cue" (a "such as"-style lead-in)
    text: str  # the clause, for review

    @property
    def skills(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(n for o in self.options for n in o))


def _mentions(clause: str) -> list[tuple[int, int, str]]:
    """Hard-skill mentions in a clause by position; overlapping matches keep the longest."""
    hits = []
    for _, name, rx in taxonomy.compiled():
        if not taxonomy.is_hard(name) or name in _SKIP:
            continue
        for m in rx.finditer(clause):
            hits.append((m.start(), m.end(), name))
    hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
    out: list[tuple[int, int, str]] = []
    for h in hits:
        if out and h[0] < out[-1][1]:
            continue
        if out and out[-1][2] == h[2] and _SEP.match(clause[out[-1][1]:h[0]]):
            out[-1] = (out[-1][0], h[1], h[2])  # "C/C++" matched twice is one mention
            continue
        out.append(h)
    return out


def _runs(clause: str, hits: list[tuple[int, int, str]]) -> list[list[tuple[int, int, str]]]:
    """Consecutive mentions joined only by separators, split again at a plain "and":
    "SQL and Python or R" is SQL plus a choice of Python or R."""
    runs: list[list[tuple[int, int, str]]] = []
    for h in hits:
        gap = clause[runs[-1][-1][1]:h[0]] if runs else None
        if gap is not None and (_SEP.match(gap) or _LOOSE.match(gap)) and not (_AND.search(gap) and not _OR.search(gap)
                                                        and _OR.search(clause[h[1]:h[1] + 40] or "")):
            runs[-1].append(h)
        else:
            runs.append([h])
    return runs


def alternative_groups(text: str) -> list[Group]:
    groups: list[Group] = []
    text = html.unescape(text or "")  # "Bachelor&#39;s" would split a clause at its ";"
    masked = _ABBREV.sub(lambda m: m.group(0).replace(".", "_"), text)
    for cm in _CLAUSE.finditer(masked):
        clause = text[cm.start():cm.end()]
        for run in _runs(clause, _mentions(clause)):
            # Split the run into options: a space or slash keeps skills in the same option.
            opts: list[list[tuple[int, int, str]]] = [[run[0]]]
            for a, b in pairwise(run):
                if _JOINED.match(clause[a[1]:b[0]]):
                    opts[-1].append(b)
                else:
                    opts.append([b])
            options = tuple(dict.fromkeys(tuple(dict.fromkeys(h[2] for h in o)) for o in opts))
            if len(options) < 2:
                continue
            gaps = [clause[a[-1][1]:b[0][0]] for a, b in pairwise(opts)]
            last = gaps[-1]
            end = opts[-1][-1][1]
            tail_or = _TAIL_OR.match(clause[end:]) and not _AND.search(last)
            if _OR.search(last) or tail_or or (any(_OR.search(g) for g in gaps) and not _AND.search(last)):
                groups.append(Group(options, "or", " ".join(clause.split())))
            elif _CUE.search(clause[:run[0][0]]) and not _AND.search(last) and _OPEN_END.match(clause[end:]):
                groups.append(Group(options, "cue", " ".join(clause.split())))
    return groups

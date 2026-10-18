"""Report-only text metrics for a draft resume (never a gate).

Adapted from ResumeFlow (MIT) alignment/preservation metrics, with two fixes:
the comparison text is plain text rather than JSON, and digits are kept, so
numbers count as words.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

_WORD = re.compile(r"[a-z0-9][a-z0-9+#]*(?:[.'\-][a-z0-9+#]+)*")
_STOP = set(
    "a an the and or of to in on for with from by at as is are was were be been my i we our me it its this "
    "that than into via all every each per up out you your will can have has had not but if so such "
    "who what which their they them these those about also more most other over under using use".split()
)


def words(text: str) -> set[str]:
    """Distinct lower-case content words (digits kept)."""
    return {w for w in _WORD.findall(text.lower().replace("’", "'")) if w not in _STOP}


def resume_text(data: dict[str, Any]) -> str:
    """The resume's readable content as plain text (no dates, ids or contact lines)."""
    parts: list[str] = []
    if data.get("summary"):
        parts.append(str(data["summary"].get("text", "")))
    for g in data.get("skills") or []:
        parts.append(" ".join(str(x) for x in g.get("items") or []))
    for e in data.get("experience") or []:
        parts += [str(e.get("title", "")), str(e.get("company", ""))]
        parts += [str(b.get("text", "")) for b in e.get("bullets") or []]
    for p in data.get("projects") or []:
        parts.append(str(p.get("name", "")))
        parts += [str(b.get("text", "")) for b in p.get("bullets") or []]
    for e in data.get("education") or []:
        parts += [str(e.get("school", "")), str(e.get("degree", ""))]
        parts += [str(line.get("text", "")) for line in e.get("lines") or []]
    return "\n".join(x for x in parts if x)


def overlap(a: str, b: str) -> float:
    """Overlap coefficient of the two texts' word sets: |A and B| / min(|A|, |B|)."""
    wa, wb = words(a), words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


def alignment(draft: str, posting: str) -> float:
    return overlap(draft, posting)


def preservation(draft: str, sources: str) -> float:
    """How much of the draft's wording already exists in the base and vault."""
    wd = words(draft)
    return len(wd & words(sources)) / len(wd) if wd else 0.0


def baseline(base: str, posting: str) -> float:
    return overlap(base, posting)


def borrowed_rate(draft: str, posting: str, sources: str) -> float:
    """Share of the draft's words that come from the posting but not from the base or vault."""
    wd = words(draft)
    if not wd:
        return 0.0
    borrowed = (wd & words(posting)) - words(sources)
    return len(borrowed) / len(wd)


def compute(draft: str, base: str, posting: str, vault_texts: Iterable[str]) -> dict[str, float]:
    sources = base + "\n" + "\n".join(vault_texts)
    a = alignment(draft, posting)
    b = baseline(base, posting)
    return {
        "alignment": round(a, 4),
        "preservation": round(preservation(draft, sources), 4),
        "baseline": round(b, 4),
        "lift": round(a - b, 4),
        "borrowed_rate": round(borrowed_rate(draft, posting, sources), 4),
    }

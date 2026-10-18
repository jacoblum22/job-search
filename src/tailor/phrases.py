"""Phrases that make writing sound AI-generated, and the rule for when they're allowed.

Word lists merged from AI Job Hunter (Apache-2.0, natural-voice.ts), Resume-Matcher
(Apache-2.0, prompts/refinement.py) and ATS Resume Improver (MIT), adapted.

Protection rule (shared by the writer prompts, the checks and the humanize pass):
a phrase is allowed when it is an exact term from the job posting, or when it
already appears in Jake's own writing (the vault or the base resume). ATS
keyword match beats style.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

BANNED_WORDS = [
    "delve", "leverage", "leveraged", "leveraging", "robust", "seamless", "seamlessly", "cutting-edge",
    "tapestry", "testament", "realm", "underscore", "underscores", "showcase", "showcasing", "foster",
    "fostering", "intricate", "pivotal", "vibrant", "garner", "vital", "crucial", "harness", "harnessing",
    "elevate", "streamline", "streamlined", "unlock", "empower", "empowering", "multifaceted",
    "ever-evolving", "paradigm shift", "spearheaded", "spearheading", "orchestrated", "utilize", "utilized",
    "utilizing", "synergy", "synergies", "holistic", "game-changer", "navigate the complexities",
    "in today's fast-paced", "landscape", "meticulously", "dynamic", "innovative solutions",
]
BANNED_SELF = [
    "passionate", "results-driven", "proven track record", "team player", "detail-oriented",
    "meticulous", "world-class", "go-getter", "hard-working", "hardworking", "self-starter",
    "think outside the box",
]
BANNED_OPENERS = [
    "i am writing to apply", "i am excited to apply", "i'm excited to apply", "as a passionate",
    "please accept this letter", "i am writing to express", "i am thrilled", "i would like to apply",
]
BANNED_CLOSERS = ["thank you for your consideration", "i look forward to hearing from you"]
# Simple replacements suggested to the humanize pass (never applied silently).
SUGGESTIONS = {
    "leverage": "use", "leveraged": "used", "leveraging": "using", "utilize": "use", "utilized": "used",
    "utilizing": "using", "spearheaded": "led", "orchestrated": "coordinated", "robust": "reliable",
    "streamline": "simplify", "streamlined": "simplified", "in order to": "to", "showcase": "show",
}

_DASH = re.compile(r"\s[—–]\s|—")
_NOT_JUST = re.compile(r"\bnot (?:just|only)\b[^.]{1,80}\bbut\b", re.I)
_ING_TAIL = re.compile(r",\s+(?:showcasing|highlighting|demonstrating|underscoring|reflecting|ensuring)\b", re.I)
_TRIPLE = re.compile(r"\b\w+(?:\s\w+)?,\s\w+(?:\s\w+)?,?\s(?:and|or)\s\w+", re.I)


@dataclass
class Hit:
    code: str  # banned_word | banned_self | opener | closer | dash | not_just | ing_tail | triple
    phrase: str
    start: int


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().replace("’", "'"))


def is_protected(phrase: str, posting: str = "", own_texts: Iterable[str] = ()) -> bool:
    """True when `phrase` is an exact posting term or already in Jake's own writing."""
    p = re.escape(_norm(phrase))
    rx = re.compile(rf"(?<!\w){p}(?!\w)")
    if posting and rx.search(_norm(posting)):
        return True
    return any(rx.search(_norm(t)) for t in own_texts)


def scan(text: str, posting: str = "", own_texts: Iterable[str] = (), *, letter: bool = False) -> list[Hit]:
    """Every AI-sounding phrase or pattern in `text` that isn't protected.

    `letter=True` adds opener/closer checks and the list-of-three pattern, which
    are letter problems; resume bullets legitimately list tools in threes.
    """
    own = list(own_texts)
    low = _norm(text)
    hits: list[Hit] = []
    for code, words in (("banned_word", BANNED_WORDS), ("banned_self", BANNED_SELF)):
        for w in words:
            for m in re.finditer(rf"(?<![\w-]){re.escape(w)}(?![\w-])", low):
                if not is_protected(w, posting, own):
                    hits.append(Hit(code, w, m.start()))
    if letter:
        for code, phrases in (("opener", BANNED_OPENERS), ("closer", BANNED_CLOSERS)):
            for w in phrases:
                i = low.find(w)
                if i >= 0:
                    hits.append(Hit(code, w, i))
        for m in _TRIPLE.finditer(text):
            hits.append(Hit("triple", m.group(0), m.start()))
    for code, rx in (("dash", _DASH), ("not_just", _NOT_JUST), ("ing_tail", _ING_TAIL)):
        for m in rx.finditer(text):
            hits.append(Hit(code, m.group(0).strip(), m.start()))
    return sorted(hits, key=lambda h: h.start)

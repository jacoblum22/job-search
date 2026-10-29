"""Phrases that make writing sound AI-generated, and the rule for when they're allowed.

Word lists merged from AI Job Hunter (Apache-2.0, natural-voice.ts), Resume-Matcher
(Apache-2.0, prompts/refinement.py) and ATS Resume Improver (MIT), adapted. The phrase
patterns (sayings that sound deep, staged run-ups, inflated significance, sales
language, "serves as" verbs, arguing with no one) follow the Humanizer skill (MIT,
github.com/blader/humanizer), which is built on Wikipedia's "Signs of AI writing".

Protection rule (shared by the writer prompts, the checks and the humanize pass):
a phrase is allowed when it is an exact term from the job posting, or when it
already appears in Jake's own writing (the vault or the base resume). ATS
keyword match beats style.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from src.tailor import taxonomy

BANNED_WORDS = [
    "delve", "leverage", "leveraged", "leveraging", "robust", "seamless", "seamlessly", "cutting-edge",
    "tapestry", "testament", "realm", "underscore", "underscores", "showcase", "showcasing", "foster",
    "fostering", "intricate", "pivotal", "vibrant", "garner", "vital", "crucial", "harness", "harnessing",
    "elevate", "streamline", "streamlined", "unlock", "empower", "empowering", "multifaceted",
    "ever-evolving", "paradigm shift", "spearheaded", "spearheading", "orchestrated", "utilize", "utilized",
    "utilizing", "synergy", "synergies", "holistic", "game-changer", "navigate the complexities",
    "in today's fast-paced", "landscape", "meticulously", "dynamic", "innovative solutions",
    "additionally", "bolstered", "enduring", "interplay", "deep dive",
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

# Phrase patterns: each dresses up a plain point instead of stating it (Humanizer patterns 3-5, 13, 16, 18).
PATTERNS = {
    "deep_saying": r"\b(?:the real question is|at its core|what really matters|the heart of the matter|"
                   r"the deeper issue|about as \w+ as \w+ (?:gets?|get)|fundamentally|"
                   # "an agent is only as good as the failures you find" (Quora letter, Oct 28 2026)
                   r"(?:is|are) only as (?:good|strong|useful) as)\b",
    "run_up": r"(?:^|[.!?]\s+)(?:here's the thing|the thing is|let's dive in|let's be honest|honestly\?|"
              r"here's what you need to know|real talk)\b",
    "inflated": r"\b(?:stands? as a testament|plays? a (?:key|pivotal|crucial|vital) role|setting the stage for|"
                r"marking a (?:pivotal|turning)|evolving landscape|indelible mark|reflects a broader)\b",
    "sales": r"\b(?:nestled|in the heart of|renowned|breathtaking|groundbreaking|diverse array)\b",
    "fancy_verb": r"\b(?:serves as|stands as|functions as|boasts)\b",
    "no_one": r"\b(?:i'm not saying|i am not saying|don't get me wrong|this is not to say|to be clear,)",
}
_PATTERNS = {code: re.compile(rx, re.IGNORECASE) for code, rx in PATTERNS.items()}

_DASH = re.compile(r"\s[—–]\s|—")
_NOT_JUST = re.compile(r"\bnot (?:just|only)\b[^.]{1,80}\bbut\b", re.I)
_ING_TAIL = re.compile(r",\s+(?:showcasing|highlighting|demonstrating|underscoring|reflecting|ensuring)\b", re.I)
# A list item never starts with a subject pronoun or a preposition: "After hours, I built and
# tested" is an opening clause plus two verbs, and "loads orders into Postgres, with retries and
# alerts" a clause plus a phrase with two parts; neither is three items.
_TRIPLE = re.compile(r"\b\w+(?:\s\w+)?,\s(?!(?:i|we|you|he|she|they|by|with|without|into|in|on|for|from|to|at|"
                     r"through|via)\b)\w+(?:\s\w+)?,?\s(?:and|or)\s\w+", re.I)
# "Contoso, Fabrikam and others": the names are the list; the tail only says it goes on.
_ETC = re.compile(r"(?:others?|more|similar)(?:\s\w+)?", re.I)


def _names_tools(phrase: str) -> bool:
    """True when a list names products or tools: known skills, or every item a capitalised name."""
    if len(taxonomy.find(phrase)) >= 2:
        return True
    items = re.split(r",\s|,?\s(?:and|or)\s", phrase)
    if len(items) < 3:
        return False
    if _ETC.fullmatch(items[-1]):
        items = items[:-1]
    return all(i.split()[-1][:1].isupper() for i in items[:1]) and all(i[:1].isupper() for i in items[1:])


@dataclass
class Hit:
    code: str  # banned_word | banned_self | opener | closer | dash | not_just | ing_tail | triple | PATTERNS key
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
            # Naming real tools ("Shopify, Yotpo and Braze") is content, not rhythm (Jake, Oct 20 2026),
            # and a list quoted from the posting or Jake's own writing is protected (Jake, Oct 21 2026).
            unlisted = m.group(0).replace(",", "")
            if not _names_tools(m.group(0)) and not is_protected(unlisted, posting.replace(",", ""),
                                                                   [t.replace(",", "") for t in own]):
                hits.append(Hit("triple", m.group(0), m.start()))
    for code, rx in _PATTERNS.items():
        for m in rx.finditer(low):
            phrase = m.group(0).strip(" .!?")
            if not is_protected(phrase, posting, own):
                hits.append(Hit(code, phrase, m.start()))
    for code, rx in (("dash", _DASH), ("not_just", _NOT_JUST), ("ing_tail", _ING_TAIL)):
        for m in rx.finditer(text):
            hits.append(Hit(code, m.group(0).strip(), m.start()))
    return sorted(hits, key=lambda h: h.start)

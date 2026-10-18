"""Jev client: cheap typed questions (yes/no, 0-3 score, pick-one) about a text "state".

Jev (TypeSafe AI) is reached through Vercel AI Gateway with the
``AI_GATEWAY_API_KEY`` from the git-ignored ``.env``. Jev's answers are advice:
they produce flags and evidence, never a blocking decision. With no key, or on
any error, every answer comes back ``ok=False`` and callers treat it as
"unchecked".

INTERFACE CONTRACT (other modules code against this; the HTTP part is filled in
by the Jev module owner):

    q = Question(id="seniority", type="score", text="How well does ...", scale=(0, 3))
    answers = client.ask(state_text, [q, ...])     # same order as questions
    answers[0].ok, answers[0].value, answers[0].confidence

Question types:
- ``yesno``: value is the probability of "yes" (0.0-1.0).
- ``score``: value is an int on ``scale`` (inclusive).
- ``choice``: value is one of ``options``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence


@dataclass
class Question:
    id: str
    type: str  # yesno | score | choice
    text: str
    scale: tuple[int, int] = (0, 3)
    options: list[str] = field(default_factory=list)
    criteria: str = ""  # optional rubric text shown with the question


@dataclass
class Answer:
    id: str
    ok: bool
    value: Any = None
    confidence: float | None = None
    error: str = ""


class JevClient:
    """Real client. ``from_env`` returns one that answers ``ok=False`` when no key is set."""

    def __init__(self, api_key: str | None, cfg: dict[str, Any] | None = None):
        self.api_key = api_key
        self.cfg = cfg or {}

    @classmethod
    def from_env(cls, cfg: dict[str, Any] | None = None) -> "JevClient":
        import os

        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
        return cls(os.environ.get("AI_GATEWAY_API_KEY") or None, cfg)

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def ask(self, state: str, questions: Sequence[Question]) -> list[Answer]:
        if not self.available:
            return [Answer(q.id, ok=False, error="no AI_GATEWAY_API_KEY") for q in questions]
        raise NotImplementedError("Jev HTTP call: implemented by the Jev module owner")


class FakeJev:
    """Test double. ``answers`` maps question id (or a callable(state, question)) to a value.

    Unknown ids come back ``ok=False``, like an unreachable Jev.
    """

    def __init__(self, answers: dict[str, Any] | Callable[[str, Question], Any] | None = None):
        self.answers = answers or {}
        self.calls: list[tuple[str, list[Question]]] = []
        self.available = True

    def ask(self, state: str, questions: Sequence[Question]) -> list[Answer]:
        self.calls.append((state, list(questions)))
        out = []
        for q in questions:
            if callable(self.answers):
                v = self.answers(state, q)
            else:
                v = self.answers.get(q.id, _MISSING)
            if v is _MISSING or v is None:
                out.append(Answer(q.id, ok=False, error="fake: no answer"))
            else:
                out.append(Answer(q.id, ok=True, value=v, confidence=0.9))
        return out


_MISSING = object()

_EMAIL = re.compile(r"\S+@\S+\.\S+")
_PHONE = re.compile(r"\+?\d[\d\s().-]{8,}\d")
_URL = re.compile(r"(?:https?://)?(?:www\.)?(?:linkedin\.com|github\.com)/\S+", re.I)


def strip_identity(text: str, contact: dict[str, str] | None = None) -> str:
    """Remove the candidate's name and contact details before a judge sees the text.

    Name-blinding removes a known bias in screening models. Replaces every form of
    the name in ``contact`` (full name, first and last names, each part of a
    hyphenated surname) with "the candidate", and emails, phone numbers and
    LinkedIn/GitHub URLs with a placeholder.
    """
    out = _EMAIL.sub("[email]", text)
    out = _URL.sub("[profile]", out)
    out = _PHONE.sub("[phone]", out)
    names: set[str] = set()
    for key in ("name", "full_name", "first_name", "last_name", "preferred_name"):
        v = (contact or {}).get(key)
        if v:
            names.add(v.strip())
            names.update(p for p in re.split(r"[\s-]+", v) if len(p) > 1)
    for n in sorted(names, key=len, reverse=True):
        out = re.sub(rf"\b{re.escape(n)}\b", "the candidate", out)
    out = re.sub(r"the candidate(?:[\s-]+the candidate)+", "the candidate", out)
    return out

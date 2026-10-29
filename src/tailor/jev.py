"""Jev client: cheap typed questions (yes/no, 0-3 score, pick-one) about a text "state".

Jev (TypeSafe AI) is reached through Vercel AI Gateway with the
``AI_GATEWAY_API_KEY`` from the git-ignored ``.env``. Jev's answers are advice:
they produce flags and evidence, never a blocking decision. With no key, or on
any error, every answer comes back ``ok=False`` and callers treat it as
"unchecked".

INTERFACE CONTRACT (other modules code against this):

    q = Question(id="seniority", type="score", text="How well does ...", scale=(0, 3))
    answers = client.ask(state_text, [q, ...])     # same order as questions
    answers[0].ok, answers[0].value, answers[0].confidence

Question types:
- ``yesno``: value is the probability of "yes" (0.0-1.0).
- ``score``: value is an int on ``scale`` (inclusive).
- ``choice``: value is one of ``options``.
"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Sequence

from src.concurrency import parallel_map

if TYPE_CHECKING:
    import httpx


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


@dataclass
class Usage:
    """Per-process counters for one client (estimates use ~4 chars per token)."""

    requests: int = 0
    est_input_tokens: int = 0
    reported_input_tokens: int = 0
    reported_output_tokens: int = 0

    @property
    def est_cost_usd(self) -> float:
        return self.est_input_tokens * INPUT_USD_PER_TOKEN


DEFAULTS: dict[str, Any] = {
    "model": "typesafe-ai/jev",
    "base_url": "https://ai-gateway.vercel.sh",
    "timeout_s": 30,
    "max_retries": 3,
    "parallel": 4,   # batches of one ask() sent at once; the answers are the same either way
}
INPUT_USD_PER_TOKEN = 0.042 / 1_000_000
MAX_REQUEST_TOKENS = 28_000  # Jev's state limit is ~32k tokens; leave headroom
CALL_OVERHEAD_TOKENS = 300
QUESTION_OVERHEAD_TOKENS = 50
MAX_SCORE_LEVELS = 10
MAX_CHOICE_OPTIONS = 255
TRUNCATION_MARKER = "\n[... truncated ...]"
_MAX_BACKOFF_S = 30.0


def est_tokens(text: str) -> int:
    return len(text) // 4 + 1


def _question_tokens(q: Question) -> int:
    return QUESTION_OVERHEAD_TOKENS + est_tokens(" ".join([q.text, q.criteria, *q.options]))


# --------------------------------------------------------------------------------------
# Wire format. Everything specific to Jev's HTTP API is in ENDPOINT, _build_request and
# _parse_response, so a mismatch found on the first live call is a local fix.
#
# Sources (Vercel docs "Evaluation", https://vercel.com/docs/ai-gateway/modalities/evaluation,
# updated 2026-09-22; TypeSafe API reference https://docs.typesafe.ai/api; Respan docs):
#   POST {base_url}/v1/evaluate, "Authorization: Bearer $AI_GATEWAY_API_KEY"
#   body  {"model": "typesafe-ai/jev", "state": str|object|array,
#          "questions": {name: {"type": "boolean"|"choice"|"score", "instructions": str,
#                               "criteria": ...}}}
#     boolean: criteria optional {"true": str, "false": str}
#     choice:  criteria required, {option: description-or-null}, max 255 options
#     score:   criteria required, ordered list of 2-10 level labels (index 0 = lowest)
#   reply {"model", "answers": {name: ...}, "usage": {"inputTokens", "outputTokens"}, ...}
#     boolean: {"type": "boolean", "probability": 0..1}
#     choice:  {"type": "choice", "choice": option, "probabilities": {...}, "confidence"?}
#     score:   {"type": "score", "score": float index, "probabilities": {"0": p, ...},
#               "confidence"?}
# NOT VERIFIED LIVE. TypeSafe's own dialect (also served by the Gateway at
# /typesafe/v1/systemone) calls the boolean type "noul" and returns {"noul": p}; the
# parser accepts both answer spellings. If the first live call fails, check this block.
ENDPOINT = "/v1/evaluate"


def _build_request(
    model: str, state: str, questions: Sequence[Question], keys: Sequence[str]
) -> dict[str, Any]:
    qs: dict[str, Any] = {}
    for key, q in zip(keys, questions):
        instructions = q.text + (f"\n\nCriteria: {q.criteria}" if q.criteria else "")
        if q.type == "yesno":
            spec: dict[str, Any] = {"type": "boolean"}
        elif q.type == "score":
            lo, hi = q.scale
            spec = {
                "type": "score",
                "criteria": [
                    f"{n}" + (" (lowest)" if n == lo else " (highest)" if n == hi else "")
                    for n in range(lo, hi + 1)
                ],
            }
        else:  # choice
            spec = {"type": "choice", "criteria": {o: None for o in q.options}}
        spec["instructions"] = instructions
        qs[key] = spec
    return {"model": model, "state": state, "questions": qs}


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if f == f and abs(f) != float("inf") else None


def _top_prob(probs: Any) -> float | None:
    if not isinstance(probs, dict):
        return None
    vals = [p for p in (_num(x) for x in probs.values()) if p is not None]
    return max(vals) if vals else None


def _parse_answer(q: Question, raw: Any) -> Answer:
    if not isinstance(raw, dict):
        return Answer(q.id, ok=False, error="missing or malformed answer")
    conf = _num(raw.get("confidence"))
    if conf is None:
        conf = _top_prob(raw.get("probabilities"))
    if q.type == "yesno":
        p = _num(raw.get("probability", raw.get("noul")))
        if p is None or not 0.0 <= p <= 1.0:
            return Answer(q.id, ok=False, error=f"bad yes/no probability: {raw.get('probability', raw.get('noul'))!r}")
        return Answer(q.id, ok=True, value=p, confidence=conf if conf is not None else max(p, 1 - p))
    if q.type == "score":
        lo, hi = q.scale
        s = _num(raw.get("score"))
        if s is None or s < -0.01 or s > (hi - lo) + 0.01:
            return Answer(q.id, ok=False, error=f"bad score: {raw.get('score')!r}")
        value = lo + int(round(min(max(s, 0.0), float(hi - lo))))
        return Answer(q.id, ok=True, value=value, confidence=conf)
    choice = raw.get("choice")
    if not isinstance(choice, str) or choice not in q.options:
        return Answer(q.id, ok=False, error=f"choice not among options: {choice!r}")
    return Answer(q.id, ok=True, value=choice, confidence=conf)


def _parse_response(
    body: Any, questions: Sequence[Question], keys: Sequence[str]
) -> tuple[list[Answer], tuple[int, int]]:
    """Answers in question order plus reported (input, output) token usage."""
    answers = body.get("answers") if isinstance(body, dict) else None
    if not isinstance(answers, dict):
        return [Answer(q.id, ok=False, error="response has no answers") for q in questions], (0, 0)
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    tin = _num(usage.get("inputTokens", usage.get("input_tokens"))) or 0
    tout = _num(usage.get("outputTokens", usage.get("output_tokens"))) or 0
    return [_parse_answer(q, answers.get(k)) for q, k in zip(questions, keys)], (int(tin), int(tout))


def _precheck(q: Question) -> str:
    """Why a question cannot be sent, or an empty string."""
    if q.type == "yesno":
        return ""
    if q.type == "score":
        n = q.scale[1] - q.scale[0] + 1
        return "" if 2 <= n <= MAX_SCORE_LEVELS else f"score scale must have 2-{MAX_SCORE_LEVELS} levels"
    if q.type == "choice":
        if not 1 <= len(q.options) <= MAX_CHOICE_OPTIONS or len(set(q.options)) != len(q.options):
            return f"choice needs 1-{MAX_CHOICE_OPTIONS} distinct options"
        return ""
    return f"unknown question type: {q.type!r}"


def _retry_after(v: str | None) -> float | None:
    try:
        return float(v) if v is not None else None
    except ValueError:
        return None  # HTTP-date form: fall back to exponential backoff


class JevClient:
    """Real client. ``from_env`` returns one that answers ``ok=False`` when no key is set."""

    def __init__(
        self,
        api_key: str | None,
        cfg: dict[str, Any] | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.api_key = api_key
        self.cfg = {**DEFAULTS, **(cfg or {})}
        self.usage = Usage()
        self._usage_lock = threading.Lock()   # batches (and queue candidates) are sent from threads
        self._transport = transport
        self._sleep = sleep

    @classmethod
    def from_env(cls, cfg: dict[str, Any] | None = None) -> "JevClient":
        try:
            from dotenv import load_dotenv

            load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
        except ImportError:
            pass
        return cls(os.environ.get("AI_GATEWAY_API_KEY") or None, cfg)

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def ask(self, state: str, questions: Sequence[Question]) -> list[Answer]:
        """One Answer per question, same order. Never raises."""
        questions = list(questions)
        if not self.available:
            return [Answer(q.id, ok=False, error="no AI_GATEWAY_API_KEY") for q in questions]
        try:
            return self._ask(state, questions)
        except Exception as e:  # noqa: BLE001 - ask() must never raise
            return [Answer(q.id, ok=False, error=f"jev error: {e}") for q in questions]

    def _ask(self, state: str, questions: list[Question]) -> list[Answer]:
        results: list[Answer | None] = [None] * len(questions)
        sendable: list[int] = []
        for i, q in enumerate(questions):
            why = _precheck(q)
            if why:
                results[i] = Answer(q.id, ok=False, error=why)
            else:
                sendable.append(i)
        if sendable:
            state, batches = self._plan(str(state), [questions[i] for i in sendable])
            idxs = [[sendable[j] for j in batch] for batch in batches]
            sent = parallel_map(lambda idx: self._send(state, [questions[i] for i in idx]), idxs,
                                int(self.cfg.get("parallel", 1)))
            for idx, answers in zip(idxs, sent):
                for i, a in zip(idx, answers):
                    results[i] = a
        return [
            r if r is not None else Answer(q.id, ok=False, error="not answered")
            for r, q in zip(results, questions)
        ]

    def _plan(self, state: str, qs: list[Question]) -> tuple[str, list[list[int]]]:
        """Truncate an oversized state and split questions into batches under the token cap."""
        limit = int(self.cfg.get("max_request_tokens", MAX_REQUEST_TOKENS))
        qtok = [_question_tokens(q) for q in qs]
        reserve = min(sum(qtok), 4000)  # keep room for the questions next to the state
        max_state = max(limit - CALL_OVERHEAD_TOKENS - reserve, 500)
        if est_tokens(state) > max_state:
            state = state[: max_state * 4 - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER
        budget = limit - CALL_OVERHEAD_TOKENS - est_tokens(state)
        batches: list[list[int]] = []
        cur: list[int] = []
        used = 0
        for j, t in enumerate(qtok):
            if cur and used + t > budget:
                batches.append(cur)
                cur, used = [], 0
            cur.append(j)
            used += t
        if cur:
            batches.append(cur)
        return state, batches

    def _send(self, state: str, qs: list[Question]) -> list[Answer]:
        ids = [q.id for q in qs]
        keys = [q.id if ids.count(q.id) == 1 else f"{q.id}#{i}" for i, q in enumerate(qs)]
        payload = _build_request(self.cfg["model"], state, qs, keys)
        est = CALL_OVERHEAD_TOKENS + est_tokens(state) + sum(_question_tokens(q) for q in qs)
        url = str(self.cfg["base_url"]).rstrip("/") + ENDPOINT
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        retries = int(self.cfg["max_retries"])
        error = "unknown error"
        # Imported here so code that only builds questions (the `why` re-check) runs without httpx.
        import httpx

        with httpx.Client(transport=self._transport, timeout=float(self.cfg["timeout_s"])) as http:
            for attempt in range(retries + 1):
                delay = min(2.0**attempt, _MAX_BACKOFF_S)
                with self._usage_lock:
                    self.usage.requests += 1
                    self.usage.est_input_tokens += est
                try:
                    r = http.post(url, json=payload, headers=headers)
                except httpx.HTTPError as e:
                    error = f"network error: {type(e).__name__}: {e}"
                else:
                    if r.status_code == 429 or r.status_code >= 500:
                        error = f"HTTP {r.status_code}"
                        ra = _retry_after(r.headers.get("retry-after"))
                        if ra is not None:
                            delay = min(max(ra, 0.0), 60.0)
                    elif r.status_code >= 400:
                        msg = f"HTTP {r.status_code}: {r.text[:200]}"
                        return [Answer(q.id, ok=False, error=msg) for q in qs]
                    else:
                        try:
                            body = r.json()
                        except ValueError:
                            return [Answer(q.id, ok=False, error="response is not JSON") for q in qs]
                        answers, (tin, tout) = _parse_response(body, qs, keys)
                        with self._usage_lock:
                            self.usage.reported_input_tokens += tin
                            self.usage.reported_output_tokens += tout
                        return answers
                if attempt < retries:
                    self._sleep(delay)
        return [Answer(q.id, ok=False, error=f"{error} after {retries + 1} attempts") for q in qs]


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


class RememberedJev:
    """A client that gives a question asked again about the same text the answer it got the first
    time, kept in one application folder's `jev-answers.json`.

    Every round asked Jev every checklist and support question again, even about lines that hadn't
    changed, and many answers sit near 50/50, so rounds that changed a few words (or none: Fairstone
    and J.D. Power, Oct 2026) won or lost on coin flips (pipeline audit, Oct 29 2026). With the
    answers remembered, an unchanged line scores the same in every round and only what a round
    changed can move its score. Only answered questions are kept; an unreachable Jev is asked again."""

    def __init__(self, inner: Any, path: Path):
        self.inner = inner
        self.path = Path(path)
        self.available = getattr(inner, "available", True)
        self._lock = threading.Lock()

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    @staticmethod
    def key(state: str, q: Question) -> str:
        import hashlib
        import json

        raw = json.dumps([state, q.type, q.text, list(q.scale), list(q.options), q.criteria], ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def _load(self) -> dict[str, Any]:
        import json

        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def ask(self, state: str, questions: Sequence[Question]) -> list[Answer]:
        import json

        questions = list(questions)
        with self._lock:
            memory = self._load()
        out: list[Answer | None] = [None] * len(questions)
        missing: list[int] = []
        for i, q in enumerate(questions):
            hit = memory.get(self.key(state, q))
            if isinstance(hit, dict):
                out[i] = Answer(q.id, ok=True, value=hit.get("value"), confidence=hit.get("confidence"))
            else:
                missing.append(i)
        if missing:
            answers = self.inner.ask(state, [questions[i] for i in missing])
            new = {}
            for i, a in zip(missing, answers):
                out[i] = a
                if a.ok:
                    new[self.key(state, questions[i])] = {"value": a.value, "confidence": a.confidence}
            # Re-read before writing: check asks about several lines at once from threads.
            with self._lock:
                memory = {**self._load(), **new}
                try:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    self.path.write_text(json.dumps(memory, ensure_ascii=False, indent=0), encoding="utf-8")
                except OSError:
                    pass
        return [a if a is not None else Answer(q.id, ok=False, error="no answer") for a, q in zip(out, questions)]


def remembered(jev: Any, app_dir: Path) -> Any:
    """`jev` wrapped so its answers are kept in `<app>/jev-answers.json` (None stays None)."""
    if jev is None or isinstance(jev, RememberedJev):
        return jev
    return RememberedJev(jev, Path(app_dir) / "jev-answers.json")

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

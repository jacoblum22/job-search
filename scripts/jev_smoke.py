"""Smoke test for the Jev client: three trivial questions (one per type) on an invented state.

Run: uv run python scripts/jev_smoke.py
Exits non-zero if AI_GATEWAY_API_KEY is missing (set it in the git-ignored .env) or any
answer comes back not ok.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.tailor.jev import JevClient, Question  # noqa: E402
from src.tailor.paths import load_config  # noqa: E402

STATE = (
    "Posting: Junior Data Analyst at Example Corp. Requires 1-2 years of SQL and Python. "
    "Candidate: recent graduate, one co-op using SQL dashboards, no Python."
)

QUESTIONS = [
    Question("sql", "yesno", "Does the candidate have SQL experience?"),
    Question(
        "seniority",
        "score",
        "How senior is the role?",
        scale=(0, 3),
        criteria="0 = intern, 1 = junior, 2 = mid, 3 = senior",
    ),
    Question("gap", "choice", "Which requirement is the candidate missing?", options=["SQL", "Python", "none"]),
]


def main() -> int:
    client = JevClient.from_env((load_config().get("jev") or {}))
    if not client.available:
        print("AI_GATEWAY_API_KEY is not set (put it in .env at the repo root).", file=sys.stderr)
        return 2
    answers = client.ask(STATE, QUESTIONS)
    bad = 0
    for a in answers:
        if a.ok:
            conf = "n/a" if a.confidence is None else f"{a.confidence:.2f}"
            print(f"{a.id}: value={a.value!r} confidence={conf}")
        else:
            bad += 1
            print(f"{a.id}: NOT OK - {a.error}", file=sys.stderr)
    u = client.usage
    print(
        f"requests={u.requests} est_input_tokens={u.est_input_tokens} "
        f"est_cost=${u.est_cost_usd:.6f} reported_in={u.reported_input_tokens} "
        f"reported_out={u.reported_output_tokens}"
    )
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

"""Try Jev questions that tell a good cover-letter opener from a pitch-like one, before using any in the checks.

The distinction (Jake, Nov 2 2026): describing the employer's job in paragraph 1 is fine when the paragraph then
says the candidate did that work ("That was most of my job"). It is bad when the description is an aside that
nothing picks up, e.g. "...role at Nexthop, where new grad engineers take part in everything from design and
implementation to testing and peer review." Also unwanted: glossy employer-pitch phrasing.

Run on the PC (Jev isn't reachable from the cloud): uv run python scripts/jev_opener_test.py
Reads every materials/applications/*/final/cover-letter.json, asks each question variant about the first
paragraph, prints answers next to Jake's labels, and writes logs/jev-opener-test.md. Costs well under a cent.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.tailor.jev import JevClient, Question  # noqa: E402
from src.tailor.paths import load_config, resolve  # noqa: E402

# Jake's rulings (Nov 2 2026). "ok" = fine, "bad" = bad, "mid" = borderline. Keys are folder-name fragments.
LABELS = {
    "Vancouver Coastal Health - Junior Business": ("ok", "describes, then 'That was most of my job'"),
    "RAM Consulting": ("ok", "describes, then 'That matches most of my recent work'"),
    "Amazon - ICQA": ("ok", "'The job asks for ..., which is close to my work'"),
    "Pattison": ("ok", "describes, then 'was that kind of work'"),
    "Metasys - Data Scientist Internship": ("ok", "'asks for ... At AlgaeCal my role covered both sides'"),
    "Vancouver Psychology Centre": ("ok", "describes, then 'that is the work I have been doing'"),
    "Noise Digital": ("mid", "connects to his work, but 'takes LLM agents from prototype to production' sounds like a pitch"),
    "Princeton": ("mid", "connects, but 'splits its time between ...' sounds canned"),
}

# Hand-written cases: the Nexthop paragraph as it was (bad) and as fixed (ok).
EXTRA = {
    "Nexthop BEFORE": ("bad", (
        "I'm applying for the Software Engineer - New Grad 2027 role at Nexthop, where new grad engineers take part in "
        "everything from design and implementation to testing and peer review. At AlgaeCal, a Vancouver e-commerce "
        "company, I did peer review of queries with the senior members of the data team, and we agreed on fixes "
        "together. On my own Python projects I made the design decisions and checked the results with pytest suites "
        "and an eval set built from real use.")),
    "Nexthop AFTER": ("ok", (
        "I'm applying for the Software Engineer - New Grad 2027 role at Nexthop. At AlgaeCal, a Vancouver e-commerce "
        "company, I did peer review of queries with the senior members of the data team, and we agreed on fixes "
        "together. On my own Python projects I made the design decisions and checked the results with pytest suites "
        "and an eval set built from real use.")),
}

RUBRIC = (
    "A cover-letter paragraph may describe the employer's job, team or company only to set up a statement that the "
    "writer did that work. Fine: 'Your posting describes a junior analyst who pulls data with SQL ... That was most "
    "of my job at X.' Not fine: a description attached to the role name as an aside that the rest of the paragraph "
    "never refers to, e.g. 'I'm applying for the Engineer role at Y, where engineers take part in everything from "
    "design to testing', followed by unrelated experience."
)

QUESTIONS = [
    # A: the plain version of what Jake said
    Question("A_unused", "yesno",
             "Does this paragraph describe the employer's job, team or company in a way that the writer's own "
             "experience in the rest of the paragraph never picks up or connects to?"),
    # B: same, with the rubric shown
    Question("B_unused_rubric", "yesno",
             "Does this paragraph describe the employer's job, team or company in a way that the rest of the "
             "paragraph never picks up?", criteria=RUBRIC),
    # C: pitch tone only
    Question("C_pitch", "yesno",
             "Does any sentence in this paragraph read like a job advertisement or company pitch to the employer "
             "(glossy description of their own work) rather than a candidate talking about their own work?"),
    # D: score of how much of the paragraph is about the employer without a link back
    Question("D_score", "score", "How much of this paragraph tells the employer about its own job, with no link to the "
             "writer's own work?", scale=(0, 3), criteria="0 = none; 1 = a short description that is then tied to the "
             "writer's work; 2 = a description only loosely tied; 3 = a description that is never tied to the writer's work."),
    # E: where the first sentence's description goes
    Question("E_choice", "choice", "After the opening sentence describes the role or employer, what does the next "
             "sentence do?", options=["ties it to the writer's own work", "moves to unrelated experience",
                                      "there was no description in the opening"]),
]


def first_paragraph(path: Path) -> str:
    j = json.loads(path.read_text(encoding="utf-8"))
    ps = j.get("paragraphs") or []
    if not ps:
        return ""
    return str(ps[0].get("text") if isinstance(ps[0], dict) else ps[0])


def fmt(a) -> str:
    if not a.ok:
        return "n/a"
    if isinstance(a.value, float):
        return f"{a.value:.2f}"
    return str(a.value)[:12]


def main() -> int:
    cfg = load_config()
    client = JevClient.from_env(cfg.get("jev") or {})
    if not client.available:
        print("AI_GATEWAY_API_KEY is not set (put it in .env at the repo root).", file=sys.stderr)
        return 2
    apps = resolve(cfg, "applications")
    cases: list[tuple[str, str, str, str]] = []  # name, label, why, text
    for d in sorted(Path(apps).glob("*")):
        p = d / "final" / "cover-letter.json"
        if not p.exists():
            continue
        text = first_paragraph(p)
        if not text:
            continue
        label, why = "?", ""
        for frag, (lab, w) in LABELS.items():
            if frag in d.name:
                label, why = lab, w
        cases.append((d.name[:55], label, why, text))
    for name, (lab, text) in EXTRA.items():
        cases.append((name, lab, "", text))

    rows = []
    for name, label, why, text in cases:
        answers = client.ask("Opening paragraph of a cover letter:\n\n" + text, QUESTIONS)
        rows.append((name, label, why, text, answers))

    qids = [q.id for q in QUESTIONS]
    lines = ["# Jev opener test", "", "| case | label | " + " | ".join(qids) + " |", "|---|---|" + "---|" * len(qids)]
    for name, label, _, _, answers in rows:
        lines.append(f"| {name} | {label} | " + " | ".join(fmt(a) for a in answers) + " |")
    lines += ["", "Yes/no values are P(yes). Labels: ok = fine, bad = bad, mid = borderline, ? = not labelled by Jake.", ""]
    out = Path("logs") / "jev-opener-test.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print("\n".join(lines))
    u = client.usage
    print(f"requests={u.requests} est_cost=${u.est_cost_usd:.6f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

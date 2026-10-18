"""Try out Jev questions about domain knowledge on hand-labelled jobs before using them in the score.

The tier score can't see domain gaps (healthcare, insurance, mining) because its skills
list only knows tools. This asks Jev a few candidate questions about each test job and
prints Jev's answer next to the label we expect, so we can see whether a question
separates the jobs that need domain knowledge from the ones that don't, or just says
the same thing for everything.

Run on the PC (Jev isn't reachable from the cloud): uv run python scripts/jev_domain_test.py
Costs well under a cent. Jobs missing from jobs.db (pruned) are skipped.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db import connect
from src.tailor.jev import JevClient, Question
from src.tailor.paths import load_config, resolve
from src.tailor.queue import _master_resume, _to_markdown

# job id -> (expected, why). "gap" = the posting asks for industry knowledge the resume lacks.
LABELS = {
    761: ("gap", "VCH: 'fundamental knowledge of healthcare systems, terms, and procedures'"),
    1218: ("gap", "Fraser Health quality improvement: healthcare setting"),
    683: ("gap", "Teck: 'familiarity with industrial domains such as processing and mining'"),
    1228: ("gap", "KWL: water and wastewater policy analyst"),
    1156: ("gap", "CIBC: fraud, analytics or risk management experience"),
    246: ("gap", "UBC pre-doc: economics research"),
    1013: ("none", "Allstate: 'insurance, financial services, or other data-driven' environments"),
    742: ("none", "Amazon BI engineer: general BI"),
    938: ("none", "Amazon BI engineer: general BI"),
    905: ("none", "Amazon ICQA data analyst: general analytics"),
    682: ("none", "Remarcable data scientist: general"),
    1189: ("none", "Cushman & Wakefield analytics engineer: general"),
    880: ("none", "Sun Life data scientist: AI and ML"),
    948: ("none", "CoVet BI analyst: general"),
    1067: ("none", "Databricks SWE intern: general software"),
    1197: ("none", "Unity ML intern: general ML"),
}

QUESTIONS = [
    Question("asks_domain", "yesno",
             "Does the posting ask for knowledge of a specific industry or field (for example healthcare, "
             "insurance, mining, finance, economics) beyond general data and software skills?"),
    Question("domain_gap", "yesno",
             "Does the posting ask for knowledge of a specific industry or field that the resume shows "
             "no experience in?"),
    Question("domain_gap_score", "score",
             "How much industry-specific knowledge does the posting require that the resume does not show?",
             scale=(0, 3), criteria="0 = none, the work is general data or software work; 1 = a little, "
             "nice to have; 2 = a clear requirement; 3 = central to the role"),
    # The question the queue step already asks, for comparison.
    Question("domain_fit", "score", "How well does the resume's domain and kind of work match what this role does?"),
]


def main() -> int:
    cfg = load_config()
    client = JevClient.from_env(cfg.get("jev") or {})
    if not client.available:
        print("AI_GATEWAY_API_KEY is not set (put it in .env at the repo root).", file=sys.stderr)
        return 2
    resume = _master_resume(cfg)
    conn = connect(resolve(cfg, "db"))
    print(f"{'job':>5} {'expect':6} " + " ".join(f"{q.id:>16}" for q in QUESTIONS) + "  why")
    for jid, (expect, why) in LABELS.items():
        row = conn.execute("SELECT title, company, description FROM jobs WHERE id = ?", (jid,)).fetchone()
        if row is None:
            print(f"{jid:>5} skipped (not in jobs.db)")
            continue
        state = (f"JOB POSTING\n{row['title']} at {row['company']}\n\n{_to_markdown(row['description'])}"
                 f"\n\nRESUME\n{resume}")
        answers = client.ask(state, QUESTIONS)
        cells = []
        for a in answers:
            if not a.ok:
                cells.append(f"{'error':>16}")
            elif isinstance(a.value, float) and a.value <= 1 and a.id in ("asks_domain", "domain_gap"):
                cells.append(f"{'p(yes)=' + format(a.value, '.2f'):>16}")
            else:
                cells.append(f"{a.value!s:>16}")
        print(f"{jid:>5} {expect:6} " + " ".join(cells) + f"  {why}")
    u = client.usage
    print(f"\nrequests={u.requests} est_cost=${u.est_cost_usd:.5f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

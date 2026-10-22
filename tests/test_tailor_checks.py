"""Tests for edits.py, checks.py, metrics.py and letter.py (synthetic fixtures, no Jev, no network)."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest
import yaml

from src.resume import load_resume, validate
from src.tailor import TailorError
from src.tailor.appdir import read_json, write_json
from src.tailor.checks import extract_numbers, number_keys, run_check, supported_years
from src.tailor.edits import apply_edits
from src.tailor.jev import FakeJev
from src.tailor.metrics import alignment, borrowed_rate, compute
from src.tailor.paths import load_config

FX = Path(__file__).parent / "fixtures" / "tailor"
CX = FX / "checks"

SQL_NEW = "Wrote SQL daily in PostgreSQL, using CTEs and window functions, to answer data requests from the Operations and Sales teams."
LETTER = {
    "greeting": "Dear Priya Shah,",
    "paragraphs": [
        {"text": "I write SQL daily and maintain dashboards, which matches the Contoso Retail analytics work.",
         "sources": ["northwind.sql-daily"], "company_facts": ["posting:1"]},
        {"text": "At Northwind I explained results to stakeholders in weekly reviews.",
         "sources": ["northwind.stakeholders"], "company_facts": []},
        {"text": "I would welcome a conversation about the role.", "sources": [], "company_facts": []},
    ],
    "sign_off": "Sincerely,\nAlex Rivera",
}


def make_app(tmp_path: Path, rnd: int = 1):
    cfg = load_config({"paths": {
        "bases": str(tmp_path / "bases"),
        "vault_index": str(tmp_path / "vault-index.json"),
        "companies": str(tmp_path / "companies"),
    }})
    (tmp_path / "bases").mkdir(parents=True)
    shutil.copy(FX / "base-analyst.yaml", tmp_path / "bases" / "data-analyst.yaml")
    shutil.copy(FX / "vault-index.json", tmp_path / "vault-index.json")
    facts = tmp_path / "companies" / "contoso-retail"
    facts.mkdir(parents=True)
    shutil.copy(CX / "facts.json", facts / "facts.json")
    app = tmp_path / "app"
    (app / f"drafts/r{rnd}").mkdir(parents=True)
    for name in ("requirements.json", "plan.json", "app.json"):
        shutil.copy(CX / name, app / name)
    shutil.copy(FX / "posting.md", app / "posting.md")
    return app, cfg


def write_edits(app: Path, edits: list[dict], rnd: int = 1) -> None:
    (app / f"drafts/r{rnd}/edits.json").write_text(json.dumps({"strategy": "nudge", "edits": edits}), encoding="utf-8")


def write_letter(app: Path, letter: dict, rnd: int = 1) -> None:
    (app / f"drafts/r{rnd}/cover-letter.json").write_text(json.dumps(letter), encoding="utf-8")


def read(app: Path, name: str, rnd: int = 1):
    return json.loads((app / f"drafts/r{rnd}/{name}").read_text(encoding="utf-8"))


def base_data(cfg) -> dict:
    return load_resume(Path(cfg["paths"]["bases"]) / "data-analyst.yaml")


def put_draft(app: Path, data: dict, rnd: int = 1) -> None:
    (app / f"drafts/r{rnd}/resume.yaml").write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def codes(items) -> list[str]:
    return [i["code"] for i in items]


def sql_edit(**kw):
    e = {"path": "experience/northwind/northwind.sql-daily", "action": "replace",
         "original": "wrote sql daily in postgresql (ctes, window functions) to answer data requests from the  Operations and Sales teams.",
         "value": SQL_NEW, "reason": "x", "sources": ["northwind.sql-daily"]}
    e.update(kw)
    return e


# ---------------------------------------------------------------------------
# edits.py
# ---------------------------------------------------------------------------


def test_clean_pass(tmp_path):
    app, cfg = make_app(tmp_path)
    write_edits(app, [
        sql_edit(),
        {"path": "experience/northwind", "action": "append", "value": "Created dbt models for the staging layer of the warehouse.",
         "sources": ["northwind.dbt"]},
        {"path": "skills/skills.tools", "action": "add_skill", "value": "dbt", "sources": ["northwind.dbt"]},
        {"path": "experience/northwind", "action": "reorder",
         "value": ["northwind.dashboards", "northwind.sql-daily", "northwind.forecast", "northwind.new-1"]},
    ])
    res = apply_edits(app, 1, cfg)
    assert res["rejected"] == [] and len(res["applied"]) == 4
    draft = load_resume(app / "drafts/r1/resume.yaml")
    assert validate(draft, require_sources=True) == []
    b = {x["id"]: x for x in draft["experience"][0]["bullets"]}
    assert b["northwind.sql-daily"]["text"] == SQL_NEW
    assert b["northwind.new-1"]["sources"] == ["northwind.dbt"]
    assert "dbt" in draft["skills"][1]["items"]
    assert read(app, "applied.json")["letter_errors"] == []

    check = run_check(app, 1, cfg, None)
    assert check["criticals"] == [], check["criticals"]
    assert check["reverted"] == []
    assert set(check["metrics"]) == {"alignment", "preservation", "baseline", "lift", "borrowed_rate"}
    assert (app / "drafts/r1/check.json").exists()


@pytest.mark.parametrize("edit,reason", [
    ({"path": "experience/northwind/title", "action": "replace", "value": "Senior Analyst", "original": "x", "sources": ["northwind.org"]}, "locked"),
    ({"path": "education/exu/exu.coursework", "action": "replace", "value": "Regression, Databases", "original": "Regression, Databases, Machine Learning", "sources": []}, "cite"),
    ({"path": "education/exu", "action": "replace", "value": "x", "original": "x", "sources": ["course.degree"]}, "education is locked"),
    ({"path": "contact/email", "action": "replace", "value": "x", "original": "x", "sources": []}, "unknown section"),
    ({"path": "experience/northwind/nope", "action": "replace", "value": "x", "original": "x", "sources": ["northwind.org"]}, "does not resolve"),
    (sql_edit(original="something else entirely"), "original does not match"),
    (sql_edit(sources=[]), "at least one source"),
    (sql_edit(sources=["ghost.id"]), "unknown source"),
    (sql_edit(sources=["northwind.departure"]), "not a resume claim"),
    (sql_edit(sources=["guide.no-metrics"]), "not a resume claim"),
    ({"path": "experience/northwind", "action": "append", "value": "x y z", "sources": []}, "at least one source"),
    ({"path": "experience/northwind", "action": "reorder", "value": ["northwind.sql-daily", "northwind.dashboards"]}, "same items"),
    ({"path": "experience/northwind/northwind.forecast", "action": "remove"}, "protected"),
    ({"path": "experience/lab/lab.stats", "action": "remove"}, "without bullets"),
    ({"path": "experience/northwind", "action": "wipe"}, "malformed"),
    (sql_edit(value="Wrote SQL daily " + "for the operations team " * 9), "limit 200"),
    ({"path": "experience/northwind", "action": "append", "value": "Created dbt models " * 12,
      "sources": ["northwind.dbt"]}, "limit 200"),
])
def test_gate_rejections(tmp_path, edit, reason):
    app, cfg = make_app(tmp_path)
    write_edits(app, [edit])
    res = apply_edits(app, 1, cfg)
    assert res["applied"] == []
    assert reason in res["rejected"][0]["reason"], res["rejected"]


def test_coursework_replace_allowed(tmp_path):
    app, cfg = make_app(tmp_path)
    write_edits(app, [{"path": "education/exu/exu.coursework", "action": "replace",
                       "original": "Regression, Databases, Machine Learning", "value": "Regression, Databases",
                       "sources": ["course.degree"]}])
    assert len(apply_edits(app, 1, cfg)["applied"]) == 1


def test_letter_shape_errors_recorded(tmp_path):
    app, cfg = make_app(tmp_path)
    write_edits(app, [])
    write_letter(app, {"greeting": "Hi", "paragraphs": [{"text": "x", "sources": "oops"}]})
    res = apply_edits(app, 1, cfg)
    assert any("sign_off" in e for e in res["letter_errors"]) and any("sources" in e for e in res["letter_errors"])
    assert "letter_shape" in codes(run_check(app, 1, cfg, None)["criticals"])


def test_repair_round_sections_and_letter_copy(tmp_path):
    app, cfg = make_app(tmp_path)
    write_edits(app, [sql_edit()])
    write_letter(app, LETTER)
    apply_edits(app, 1, cfg)
    (app / "drafts/r2").mkdir()
    (app / "drafts/r1/feedback.json").write_text(json.dumps({"round": 2, "criticals": [], "failed_items": [],
                                                              "sections": ["experience/northwind/northwind.dashboards"]}))
    other = {"path": "experience/northwind/northwind.forecast", "action": "replace",
             "original": "Built a demand forecasting model in Python (pandas, scikit-learn) on 250k shipment records.",
             "value": "Built a demand forecast in Python on 250k shipment records.", "sources": ["northwind.forecast"]}
    inside = {"path": "experience/northwind/northwind.dashboards", "action": "replace",
              "original": "Maintained Tableau dashboards for the operations team and traced each metric to its source tables.",
              "value": "Maintained Tableau dashboards used by the operations team.", "sources": ["northwind.dashboards"]}
    write_edits(app, [other, inside], rnd=2)
    res = apply_edits(app, 2, cfg)
    assert [a["edit"]["path"] for a in res["applied"]] == [inside["path"]]
    assert "outside the sections" in res["rejected"][0]["reason"]
    # Round 2 started from round 1's draft, and the letter was carried forward.
    b = {x["id"]: x for x in load_resume(app / "drafts/r2/resume.yaml")["experience"][0]["bullets"]}
    assert b["northwind.sql-daily"]["text"] == SQL_NEW
    assert res["letter_copied"] and (app / "drafts/r2/cover-letter.json").exists()


def test_repair_round_needs_feedback(tmp_path):
    app, cfg = make_app(tmp_path)
    write_edits(app, [])
    apply_edits(app, 1, cfg)
    (app / "drafts/r2").mkdir()
    write_edits(app, [], rnd=2)
    with pytest.raises(TailorError):
        apply_edits(app, 2, cfg)


# ---------------------------------------------------------------------------
# checks.py: criticals
# ---------------------------------------------------------------------------


def checked(tmp_path, mutate, letter=None):
    app, cfg = make_app(tmp_path)
    data = base_data(cfg)
    mutate(data)
    put_draft(app, data)
    if letter:
        write_letter(app, letter)
    return run_check(app, 1, cfg, None), app, cfg


def bullet(data, bid):
    return next(b for b in data["experience"][0]["bullets"] if b["id"] == bid)


def test_invented_number_and_variants(tmp_path):
    def m(d):
        bullet(d, "northwind.sql-daily")["text"] = SQL_NEW + " That cut turnaround by 35% and saved $1.2M."
    res, *_ = checked(tmp_path, m)
    nums = [c["message"] for c in res["criticals"] if c["code"] == "invented_number"]
    assert len(nums) == 2


def test_number_normalization():
    allowed = number_keys("Loaded 250k rows, 1,200 users, $1.2M budget, 0.94 F1, up to 3x, 20 percent")
    assert extract_numbers("250,000 rows, 1200 users, 1200000 dollars, 0.94, 3x, 20%", allowed) == []
    assert len(extract_numbers("Reached 98%, 2x faster, 0.81 F1, 5000 rows, $4k", allowed)) == 5
    assert extract_numbers("worked 3 days in 2025 with 12 people", set()) == []


def test_years_of_experience_helper():
    base = {"experience": [{"dates": "Jan 2026 – Sep 2026"}, {"dates": "Sep 2024 – Dec 2025"}]}
    assert 1.5 < supported_years(base) < 2.5


def test_invented_skill(tmp_path):
    def m(d):
        bullet(d, "northwind.dashboards")["text"] += " Also built Looker explores."
    res, *_ = checked(tmp_path, m)
    assert [c["message"] for c in res["criticals"] if c["code"] == "invented_skill"] == [
        c["message"] for c in res["criticals"] if "Looker" in c["message"]]
    assert any("Looker" in c["message"] for c in res["criticals"])


def test_plan_add_backs_a_skill_on_the_line_that_cites_it(tmp_path):
    def m(d):
        bullet(d, "northwind.dashboards")["text"] += " Also built Looker explores."
    app, cfg = make_app(tmp_path)
    cfg["paths"]["skill_record"] = str(tmp_path / "skill-record.json")
    plan = read_json(app / "plan.json")
    plan["evidence_adds"] = [{"term": "Looker", "passage": "northwind.dashboards", "reason": "test"}]
    write_json(app / "plan.json", plan)
    data = base_data(cfg)
    m(data)
    put_draft(app, data)
    assert not any("Looker" in c["message"] for c in run_check(app, 1, cfg, None)["criticals"])
    # the same wording on a line that doesn't cite the confirmed passage is still invented
    data = base_data(cfg)
    bullet(data, "northwind.sql-daily")["text"] += " Also built Looker explores."
    put_draft(app, data)
    assert any(c["code"] == "invented_skill" and "Looker" in c["message"]
               for c in run_check(app, 1, cfg, None)["criticals"])


def test_skill_in_other_vault_passage_is_fine(tmp_path):
    def m(d):
        d["skills"][1]["items"].append("Docker")  # in vault proj.spam.api, not in base
    res, *_ = checked(tmp_path, m)
    assert res["criticals"] == []


def test_dropped_invented_employer_and_locked(tmp_path):
    def m(d):
        d["experience"].pop()  # drop the lab
        d["experience"].append({"id": "acme", "title": "Analyst", "company": "Acme Corp", "dates": "Jan 2020 - Dec 2020",
                                "bullets": [{"id": "acme.a", "text": "Did things.", "sources": ["northwind.org"]}]})
        d["experience"][0]["dates"] = "Jan 2025 – Sep 2026"
        d["projects"][0]["name"] = "Other Project"
    res, *_ = checked(tmp_path, m)
    cs = codes(res["criticals"])
    for code in ("dropped_employer", "invented_employer", "locked_changed"):
        assert code in cs


def test_invented_project(tmp_path):
    def m(d):
        d["projects"].append({"id": "extra", "name": "Extra", "bullets": [{"id": "extra.a", "text": "Built it.", "sources": ["northwind.org"]}]})
    res, *_ = checked(tmp_path, m)
    assert "invented_project" in codes(res["criticals"])


def test_source_criticals(tmp_path):
    def m(d):
        bullet(d, "northwind.sql-daily")["sources"] = ["ghost.id", "northwind.sql-daily"]
        bullet(d, "northwind.dashboards")["sources"] = ["northwind.departure", "northwind.dashboards"]
        bullet(d, "northwind.forecast")["sources"] = []
    res, *_ = checked(tmp_path, m)
    cs = codes(res["criticals"])
    assert {"unknown_source", "non_claim_source", "missing_source"} <= set(cs)


def test_unsupported_date(tmp_path):
    def m(d):
        bullet(d, "northwind.dashboards")["text"] += " Active since 2019."
    res, *_ = checked(tmp_path, m)
    assert "unsupported_date" in codes(res["criticals"])


def test_low_similarity_is_reverted_not_critical(tmp_path):
    app, cfg = make_app(tmp_path)
    write_edits(app, [{"path": "experience/northwind/northwind.dashboards", "action": "replace",
                       "original": "Maintained Tableau dashboards for the operations team and traced each metric to its source tables.",
                       "value": "Organized weekend volunteer pizza events across the whole neighbourhood.",
                       "sources": ["northwind.dashboards"]}])
    apply_edits(app, 1, cfg)
    res = run_check(app, 1, cfg, None)
    assert res["reverted"] == ["experience/northwind/northwind.dashboards"]
    assert res["criticals"] == []
    d = load_resume(app / "drafts/r1/resume.yaml")
    assert bullet(d, "northwind.dashboards")["text"] == bullet(base_data(cfg), "northwind.dashboards")["text"]


def test_low_similarity_appended_bullet_removed(tmp_path):
    app, cfg = make_app(tmp_path)
    write_edits(app, [{"path": "experience/northwind", "action": "append",
                       "value": "Organized weekend volunteer pizza events across the whole neighbourhood.",
                       "sources": ["northwind.dbt"]}])
    apply_edits(app, 1, cfg)
    res = run_check(app, 1, cfg, None)
    assert res["reverted"] == ["experience/northwind/northwind.new-1"]
    ids = [b["id"] for b in load_resume(app / "drafts/r1/resume.yaml")["experience"][0]["bullets"]]
    assert "northwind.new-1" not in ids


# ---------------------------------------------------------------------------
# checks.py: warnings, Jev, metrics
# ---------------------------------------------------------------------------


def test_warnings(tmp_path):
    def m(d):
        d["summary"]["text"] = ("Senior analyst with 9 years of experience in SQL. " + "SQL " * 8 + " Write SQL to answer questions from the marketing team. Leveraged data.").strip()
        bl = d["experience"][0]["bullets"]
        bl.append({"id": "northwind.dup", "text": bl[0]["text"] + " Again.", "sources": ["northwind.sql-daily"]})
        bl.append({"id": "northwind.long", "text": bl[0]["text"] + " " + bl[0]["text"], "sources": ["northwind.sql-daily"]})
        bl.append({"id": "northwind.copy", "text": "Partner with stakeholders to define KPIs and answer questions", "sources": ["northwind.stakeholders"]})
        bl.append({"id": "northwind.ai", "text": "Leveraged SQL daily for ops.", "sources": ["northwind.sql-daily"]})
        d["skills"][0]["items"] += [f"Item{i}" for i in range(30)]
        d["experience"][1]["bullets"] = []
        d["skills"][1]["items"] = ["Excel", "Git"]
        for b in bl:
            b["text"] = b["text"].replace("Tableau", "reports")  # drop a requirement term from the draft
    res, *_ = checked(tmp_path, m)
    ws = set(codes(res["warnings"]))
    assert "bullet_long" in codes(res["criticals"]) and "bullet_long" not in ws
    for code in ("years_inflation", "title_drift", "keyword_coverage_dropped", "term_stuffing", "duplicate_bullets",
                 "verbatim_posting_copy", "ai_phrase", "too_many_skills", "bullet_count"):
        assert code in ws, (code, ws)


def test_coverage_dropped_ignores_words_in_source_ids(tmp_path):
    # The base cites "course.degree" but never says "degree", so the draft has lost nothing.
    app, cfg = make_app(tmp_path)
    req = read_json(app / "requirements.json")
    req["keywords"].append({"term": "degree", "weight": "role", "quote": "degree"})
    write_json(app / "requirements.json", req)
    write_edits(app, [sql_edit()])
    apply_edits(app, 1, cfg)
    res = run_check(app, 1, cfg, None)
    assert not any(w["code"] == "keyword_coverage_dropped" and "degree" in w["message"] for w in res["warnings"])


def test_skill_only_in_list_warning(tmp_path):
    app, cfg = make_app(tmp_path)
    write_edits(app, [{"path": "skills/skills.tools", "action": "add_skill", "value": "dbt", "sources": ["northwind.dbt"]}])
    apply_edits(app, 1, cfg)
    res = run_check(app, 1, cfg, None)
    assert res["criticals"] == []
    assert any(w["code"] == "skill_only_in_list" and "dbt" in w["message"] for w in res["warnings"])


def test_skill_only_in_list_once_per_skill_named_as_listed(tmp_path):
    # "dbt Cloud" in the posting is the same skill as the listed "dbt": one warning, naming what the list says.
    app, cfg = make_app(tmp_path)
    req = read_json(app / "requirements.json")
    req["keywords"].append({"term": "dbt Cloud", "weight": "role", "quote": "dbt Cloud"})
    write_json(app / "requirements.json", req)
    write_edits(app, [{"path": "skills/skills.tools", "action": "add_skill", "value": "dbt", "sources": ["northwind.dbt"]}])
    apply_edits(app, 1, cfg)
    res = run_check(app, 1, cfg, None)
    assert [w["data"]["term"] for w in res["warnings"] if w["code"] == "skill_only_in_list"] == ["dbt"]


def test_jev_flag_and_unavailable(tmp_path):
    app, cfg = make_app(tmp_path)
    write_edits(app, [sql_edit()])
    apply_edits(app, 1, cfg)
    fake = FakeJev(lambda state, q: 0.2)
    res = run_check(app, 1, cfg, fake)
    assert [f["path"] for f in res["flags"]] == ["experience/northwind/northwind.sql-daily"]
    assert res["flags"][0]["source"] == "jev" and res["criticals"] == []
    assert "Wrote SQL daily in PostgreSQL (CTEs" in fake.calls[0][0]
    assert run_check(app, 1, cfg, FakeJev({}))["flags"] == []
    assert run_check(app, 1, cfg, FakeJev(lambda s, q: 0.9))["flags"] == []


def test_jev_no_from_a_missed_citation_adds_the_passage(tmp_path):
    # The line claims dashboard work but cites only the SQL passage: a citation gap, not an overclaim.
    app, cfg = make_app(tmp_path)
    value = SQL_NEW[:-1] + ", and maintained Tableau dashboards used by the operations team."
    write_edits(app, [sql_edit(value=value)])
    apply_edits(app, 1, cfg)
    fake = FakeJev(lambda state, q: 0.9 if "Maintained Tableau" in state else 0.2)
    res = run_check(app, 1, cfg, fake)
    assert [f["code"] for f in res["flags"]] == ["jev_citation_gap"]
    assert "northwind.dashboards" in res["flags"][0]["message"]
    assert "northwind.dbt" not in res["flags"][0]["message"]  # not needed, so trimmed
    assert "northwind.forecast" not in res["flags"][0]["message"]
    draft = yaml.safe_load((app / "drafts" / "r1" / "resume.yaml").read_text())
    srcs = next(b["sources"] for e in draft["experience"] for b in e["bullets"] if b["id"] == "northwind.sql-daily")
    assert srcs == ["northwind.sql-daily", "northwind.dashboards"]
    # Re-checking the same draft keeps the flag, though Jev now says yes with the added source.
    again = run_check(app, 1, cfg, FakeJev(lambda s, q: 0.9))
    assert [f["code"] for f in again["flags"]] == ["jev_citation_gap"]
    # Still "no" with the related passages: a real doubt, and nothing is added.
    write_edits(app, [sql_edit(value=value)])
    apply_edits(app, 1, cfg)
    res = run_check(app, 1, cfg, FakeJev(lambda s, q: 0.2))
    assert [f["code"] for f in res["flags"]] == ["jev_unsupported"]
    assert "even with northwind.dashboards" in res["flags"][0]["message"]


def test_metrics():
    posting = "Write SQL dashboards Tableau Looker"
    assert alignment("SQL dashboards", posting) == 1.0
    assert alignment("", posting) == 0.0
    m = compute("SQL dashboards Looker", "SQL reports", posting, ["Tableau"])
    assert m["lift"] == pytest.approx(m["alignment"] - m["baseline"], abs=1e-3)
    assert borrowed_rate("SQL Looker", posting, "SQL") == 0.5


# ---------------------------------------------------------------------------
# letter.py
# ---------------------------------------------------------------------------


def letter_check(tmp_path, letter):
    app, cfg = make_app(tmp_path)
    put_draft(app, base_data(cfg))
    write_letter(app, letter)
    return run_check(app, 1, cfg, None), app


def with_(**kw):
    out = copy.deepcopy(LETTER)
    out.update(kw)
    return out


def test_letter_clean(tmp_path):
    res, app = letter_check(tmp_path, LETTER)
    assert [c for c in res["criticals"] if c["doc"] == "letter"] == []
    # The fixture letter is short; length is tested on its own below.
    assert [w for w in res["warnings"] if w["doc"] == "letter" and w["code"] != "letter_length"] == []
    assert read(app, "cover-letter.json")["greeting"] == "Dear Priya Shah,"


def test_letter_greeting_reset(tmp_path):
    res, app = letter_check(tmp_path, with_(greeting="Dear Dr. Jordan Lee,"))
    assert "greeting_unverified" in codes(res["criticals"])
    assert read(app, "cover-letter.json")["greeting"] == "Dear Hiring Manager,"
    (tmp_path / "b").mkdir()
    res, _ = letter_check(tmp_path / "b", with_(greeting="Dear Hiring Team,"))
    assert "greeting_unverified" not in codes(res["criticals"])


def test_letter_company_facts(tmp_path):
    paras = copy.deepcopy(LETTER["paragraphs"])
    paras[0]["company_facts"] = ["f1", "f2", "posting:7", "zzz"]
    res, _ = letter_check(tmp_path, with_(paragraphs=paras))
    bad = [c["message"] for c in res["criticals"] if c["code"] == "unverified_company_fact"]
    assert len(bad) == 3  # f2 (unverified), posting:7, zzz


def test_letter_numbers_skills_sources(tmp_path):
    paras = copy.deepcopy(LETTER["paragraphs"])
    paras[0]["text"] = "I grew revenue by 45% at Northwind and use Looker. Contoso opened 140 stores."
    paras[0]["company_facts"] = ["f1"]
    paras[1]["sources"] = ["ghost.id", "northwind.departure"]
    res, _ = letter_check(tmp_path, with_(paragraphs=paras))
    cs = res["criticals"]
    invented = [c["message"] for c in cs if c["code"] == "invented_number"]
    assert len(invented) == 1 and "45%" in invented[0]  # 140 comes from the verified fact
    assert any(c["code"] == "invented_skill" and "Looker" in c["message"] for c in cs)
    assert {"unknown_source", "non_claim_source"} <= set(codes(cs))


def test_letter_numbers_come_from_the_verified_quote_not_the_fact_paraphrase(tmp_path):
    # Only a fact's quote was checked against the page; the "fact" sentence is the researcher's paraphrase.
    paras = copy.deepcopy(LETTER["paragraphs"])
    paras[0]["text"] = "Contoso opened 140 stores and now works with 900 suppliers."
    paras[0]["company_facts"] = ["f1"]
    app, cfg = make_app(tmp_path)
    facts_path = tmp_path / "companies" / "contoso-retail" / "facts.json"
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    facts[0]["fact"] += " and works with 900 suppliers"
    facts_path.write_text(json.dumps(facts), encoding="utf-8")
    put_draft(app, base_data(cfg))
    write_letter(app, with_(paragraphs=paras))
    res = run_check(app, 1, cfg)
    invented = [c["message"] for c in res["criticals"] if c["code"] == "invented_number"]
    assert len(invented) == 1 and "900" in invented[0]


def test_letter_keen_only_for_a_missing_must_and_no_grades(tmp_path):
    paras = [dict(p) for p in LETTER["paragraphs"]]
    paras[1] = {**paras[1], "text": paras[1]["text"] + " I earned 88% in STAT 301 and am keen to grow into dbt."}
    app, cfg = make_app(tmp_path)
    put_draft(app, base_data(cfg))
    write_letter(app, with_(paragraphs=paras))
    req = read_json(app / "requirements.json")
    must = next(r["id"] for r in req["requirements"] if r["kind"] == "must")
    write_json(app / "evidence.json", {"requirements": [{"id": must, "status": "covered"}]})
    ws = codes(run_check(app, 1, cfg, None)["warnings"])
    assert "keen_not_must" in ws and "course_grade" in ws
    write_json(app / "evidence.json", {"requirements": [{"id": must, "status": "missing"}]})
    assert "keen_not_must" not in codes(run_check(app, 1, cfg, None)["warnings"])


def test_letter_keen_fits_a_partial_must_with_an_absent_term(tmp_path):
    # "Power BI or Tableau" is partial when Tableau is backed, but Power BI is still missing.
    paras = [dict(p) for p in LETTER["paragraphs"]]
    paras[1] = {**paras[1], "text": paras[1]["text"] + " I would be keen to grow into Power BI."}
    app, cfg = make_app(tmp_path)
    put_draft(app, base_data(cfg))
    write_letter(app, with_(paragraphs=paras))
    write_json(app / "evidence.json", {"requirements": [{"id": "r1", "status": "covered"}, {"id": "r3", "status": "partial"}],
                                       "absent": ["Power BI"]})
    assert "keen_not_must" not in codes(run_check(app, 1, cfg, None)["warnings"])
    write_json(app / "evidence.json", {"requirements": [{"id": "r1", "status": "covered"}, {"id": "r3", "status": "covered"}],
                                       "absent": ["dbt"]})  # only a nice-to-have is absent
    assert "keen_not_must" in codes(run_check(app, 1, cfg, None)["warnings"])


def test_letter_skill_backed_by_a_plan_add_where_its_passage_is_cited(tmp_path):
    # Same rule as the resume: a plan's evidence_adds pair backs the skill on lines citing that passage.
    paras = copy.deepcopy(LETTER["paragraphs"])
    paras[1] = {"text": "At Northwind I built Looker dashboards for the operations team.",
                "sources": ["northwind.dashboards"], "company_facts": []}
    paras[2] = {"text": "I would bring the same Looker work to Contoso.", "sources": [], "company_facts": []}
    app, cfg = make_app(tmp_path)
    plan = read_json(app / "plan.json")
    plan["evidence_adds"] = [{"term": "Looker", "passage": "northwind.dashboards", "reason": "x"}]
    write_json(app / "plan.json", plan)
    put_draft(app, base_data(cfg))
    write_letter(app, with_(paragraphs=paras))
    invented = [c["path"] for c in run_check(app, 1, cfg, None)["criticals"] if c["code"] == "invented_skill"]
    assert invented == ["paragraphs[2]"]


def test_letter_keen_sentence_may_name_a_missing_must(tmp_path):
    paras = [dict(p) for p in LETTER["paragraphs"]]
    paras[1] = {**paras[1], "text": paras[1]["text"] + " I have not used Power BI yet and would be keen to grow into it."}
    res, _ = letter_check(tmp_path / "a", with_(paragraphs=paras))
    assert not any(c["code"] == "invented_skill" for c in res["criticals"])
    # a missing must named outside the keen sentence is still invented
    paras[1] = {**paras[1], "text": "I would be keen to grow into Looker. I also use Power BI."}
    res, _ = letter_check(tmp_path / "b", with_(paragraphs=paras))
    msgs = [c["message"] for c in res["criticals"] if c["code"] == "invented_skill"]
    assert any("Looker" in m for m in msgs) and any("Power BI" in m for m in msgs)


def test_letter_keen_sentence_may_name_any_skill_in_a_must_term(tmp_path):
    # "Snowflake SQL" names SQL and Snowflake; canonical() gives only SQL, so Snowflake was "invented".
    app, cfg = make_app(tmp_path)
    req = read_json(app / "requirements.json")
    req["requirements"][0]["terms"] = ["SQL", "Snowflake SQL"]
    write_json(app / "requirements.json", req)
    put_draft(app, base_data(cfg))
    paras = [dict(p) for p in LETTER["paragraphs"]]
    paras[1] = {**paras[1], "text": paras[1]["text"] + " I have not used Snowflake SQL yet and would be keen to grow into it."}
    write_letter(app, with_(paragraphs=paras))
    res = run_check(app, 1, cfg, None)
    assert not any(c["code"] == "invented_skill" for c in res["criticals"]), res["criticals"]


def test_letter_warnings(tmp_path):
    paras = [
        {"text": "I am passionate about data. I am keen to grow and eager to learn. Familiar with Looker.", "sources": [], "company_facts": []},
        {"text": "I leveraged SQL daily.", "sources": ["northwind.sql-daily"], "company_facts": []},
    ]
    res, _ = letter_check(tmp_path, with_(paragraphs=paras))
    ws = set(codes(res["warnings"]))
    assert {"no_company_fact", "paragraph_count", "ai_phrase", "keen_to_grow", "familiar_absent_term"} <= ws


def test_skill_pattern_ending_mid_word_still_finds_vault_wording():
    # "data warehous" and "visualiz" are patterns that stop inside a word; the wording
    # must be the whole word, or "data warehouse" in a vault passage never backs it.
    from src.tailor import taxonomy
    from src.tailor.checks import _wording_in

    found = taxonomy.find_wordings("BigQuery, the company data warehouse, and data visualizations")
    assert found["data warehouse"] == {"data warehouse"}
    assert found["data visualization"] == {"visualizations"}
    vault = "Skill: Google BigQuery; Concrete Evidence: Company data warehouse; dashboards and visualization"
    assert all(_wording_in(w, vault) for w in found["data warehouse"] | found["data visualization"])


def test_skill_listed_in_the_vault_is_a_wording_problem_not_invented():
    # The vault lists the skill ("knowledge of economics, accounting, ..."); a draft's "basic
    # accounting" is the vault's skill in other words, so the check asks for the vault's wording
    # (a repair keeps the claim) instead of calling it invented (a repair drops a true must-have).
    from src.tailor.checks import check_resume, flatten

    passage = "Some knowledge of economics, accounting, and statistics from classes."
    base = {"summary": {"id": "summary", "text": "Analyst.", "sources": []}}
    draft = {"summary": {"id": "summary", "text": "Analyst with basic accounting from classes.",
                         "sources": ["extra.knowledge"]}}
    ctx = {"index": {"extra.knowledge": {"text": passage, "use": "claim"}}, "req": {}, "posting": "",
           "base_text": flatten(base), "claim_texts": [passage], "own_texts": [passage], "confirmed": set()}
    crit, _, _ = check_resume(draft, base, ctx)
    [c] = [c for c in crit if c["code"] == "invented_skill"]
    assert "use the vault's wording" in c["message"] and c["data"]["wording"] == "basic accounting"


def test_plural_wording_finds_the_singular_in_the_vault():
    # "pipelines" is "pipeline" + s: stripping "es" left "pipelin", which never matched "Pipeline Design".
    from src.tailor.checks import _wording_in

    assert _wording_in("data pipelines", "Skill: Data Pipeline Design; built ingest jobs")
    assert _wording_in("dashboards", "Fixed a dashboard filter")
    assert _wording_in("boxes", "Shipped one box a day")
    assert not _wording_in("data pipelines", "a pipeline of customer data")


def test_skills_item_backed_by_singular_vault_wording_is_not_invented(tmp_path):
    def m(d):
        d["skills"][1]["items"].append("data pipelines")
    app, cfg = make_app(tmp_path)
    idx = json.loads(Path(cfg["paths"]["vault_index"]).read_text(encoding="utf-8"))
    idx["passages"].append({**idx["passages"][0], "id": "skills.pipelines",
                            "text": "Skill: Data Pipeline Design; Where Used: a side project"})
    Path(cfg["paths"]["vault_index"]).write_text(json.dumps(idx), encoding="utf-8")
    data = base_data(cfg)
    m(data)
    put_draft(app, data)
    assert not any(c["code"] == "invented_skill" for c in run_check(app, 1, cfg, None)["criticals"])


def test_skill_the_vault_words_differently_names_the_wording_not_a_missing_skill(tmp_path):
    # The vault says "requirements gathering"; the draft says "data requirements". The wording is
    # still flagged, but the message must not claim the skill is in no vault passage.
    from src.tailor.explain import issue

    app, cfg = make_app(tmp_path)
    idx = json.loads(Path(cfg["paths"]["vault_index"]).read_text(encoding="utf-8"))
    idx["passages"].append({**idx["passages"][0], "id": "skills.requirements",
                            "text": "Stakeholder requirements gathering for the operations team"})
    Path(cfg["paths"]["vault_index"]).write_text(json.dumps(idx), encoding="utf-8")
    data = base_data(cfg)
    bullet(data, "northwind.dashboards")["text"] += " Mapped each team's data requirements."
    put_draft(app, data)
    [c] = [c for c in run_check(app, 1, cfg, None)["criticals"] if c["code"] == "invented_skill"]
    assert c["data"] == {"term": "requirements gathering", "wording": "data requirements"}
    assert "'data requirements'" in c["message"] and "appears in no vault passage" not in c["message"]
    assert "Your vault backs requirements gathering" in issue(c, None)[0]


def test_us_and_canadian_spellings_are_the_same_wording():
    # The posting says "modeling", the vault "modelling": matching the posting's spelling
    # must not make a backed skill look invented, or the reverse.
    from src.tailor.checks import _wording_in
    from src.tailor.evidence import term_exact

    assert _wording_in("data modeling", "Drafted data modelling diagrams for each unit")
    assert _wording_in("data visualisation", "Built data visualization dashboards")
    assert not _wording_in("data modeling", "Drafted ER diagrams for each unit")
    assert term_exact({"term": "data modeling", "raw": ["data modeling"]}, "data modelling in BigQuery")
    # The ATS score still counts exact wording, as a real ATS does.
    from src.tailor.taxonomy import exact
    assert not exact("data modeling", "data modelling in BigQuery")


def test_letter_length_outside_200_to_300_words_warns(tmp_path):
    res, _ = letter_check(tmp_path, LETTER)
    short = [w for w in res["warnings"] if w["code"] == "letter_length"]
    assert len(short) == 1 and "add" in short[0]["message"]
    paras = copy.deepcopy(LETTER["paragraphs"])
    paras[0]["text"] = paras[0]["text"] + " The team kept the reports running." * 60
    res, _ = letter_check(tmp_path / "long", with_(paragraphs=paras))
    long = [w for w in res["warnings"] if w["code"] == "letter_length"]
    assert len(long) == 1 and "cut" in long[0]["message"]


def test_recheck_applies_todays_rules_without_writing_or_asking_jev(tmp_path):
    from src.tailor.checks import recheck

    app, cfg = make_app(tmp_path)
    write_edits(app, [{"path": "skills/skills.tools", "action": "add_skill", "value": "dbt", "sources": ["northwind.dbt"]}])
    apply_edits(app, 1, cfg)
    run_check(app, 1, cfg, None)
    chk = app / "drafts" / "r1" / "check.json"
    # An older check.json: a warning a later rule no longer raises, and a Jev flag.
    old = read_json(chk)
    old["warnings"] = [{"code": "ai_phrase", "message": "stale", "path": "summary", "doc": "resume"}]
    old["flags"] = [{"code": "jev_unsupported", "message": "jev", "path": "summary", "doc": "resume"}]
    write_json(chk, old)
    files = {p: p.read_bytes() for p in (app / "drafts" / "r1").iterdir()}
    res = recheck(app, 1, cfg)
    assert not any(w["message"] == "stale" for w in res["warnings"])
    assert any(w["code"] == "skill_only_in_list" and w["data"]["added"] for w in res["warnings"])
    assert res["flags"] == old["flags"]
    assert {p: p.read_bytes() for p in (app / "drafts" / "r1").iterdir()} == files

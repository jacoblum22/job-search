"""Tests for steps 1-3: requirements.normalize, evidence.run_evidence, base.run_base, sources."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest
import yaml

from src.tailor import TailorError, appdir
from src.tailor.base import run_base
from src.tailor.evidence import run_evidence
from src.tailor.jev import FakeJev
from src.tailor.paths import load_config
from src.tailor.requirements import norm_text, normalize
from src.tailor.sources import base_text, bullet_paths, claim_passages, load_bases, load_index

FX = Path(__file__).parent / "fixtures" / "tailor"


@pytest.fixture
def env(tmp_path):
    bases = tmp_path / "bases"
    bases.mkdir()
    shutil.copy(FX / "base-analyst.yaml", bases / "data-analyst.yaml")
    # A second base that says little about the posting.
    other = yaml.safe_load((FX / "base-analyst.yaml").read_text(encoding="utf-8"))
    other.update(id="researcher", label="Researcher")
    other["summary"] = {"id": "summary", "text": "Research assistant."}
    other["skills"] = [{"id": "skills.languages", "label": "Languages", "items": ["R"]}]
    other["experience"] = other["experience"][1:]
    other["projects"] = []
    (bases / "researcher.yaml").write_text(yaml.safe_dump(other), encoding="utf-8")
    shutil.copy(FX / "vault-index.json", tmp_path / "vault-index.json")
    cfg = load_config({"paths": {
        "bases": str(bases), "vault_index": str(tmp_path / "vault-index.json"),
        "unknown_terms": str(tmp_path / "tailor" / "unknown-terms.csv"),
    }})
    app = tmp_path / "app"
    app.mkdir()
    shutil.copy(FX / "posting.md", app / "posting.md")
    shutil.copy(FX / "steps123" / "requirements.json", app / "requirements.json")
    appdir.write_json(app / "app.json", {"job_id": 7, "company": "Contoso Retail", "history": []})
    return cfg, app


# --- sources -----------------------------------------------------------------

def test_sources(env):
    cfg, _ = env
    index = load_index(cfg)
    assert "northwind.sql-daily" in index
    claims = claim_passages(index)
    assert "northwind.departure" not in claims and "guide.no-metrics" not in claims
    bases = load_bases(cfg)
    assert set(bases) == {"data-analyst", "researcher"}
    paths = bullet_paths(bases["data-analyst"])
    assert "summary" in paths and "skills/skills.tools" in paths
    assert paths["experience/northwind/northwind.sql-daily"].startswith("Wrote SQL")
    assert "Tableau" in paths["skills/skills.tools"]
    assert "Example University" in base_text(bases["data-analyst"])


def test_load_bases_missing(tmp_path):
    cfg = load_config({"paths": {"bases": str(tmp_path / "none")}})
    with pytest.raises(TailorError):
        load_bases(cfg)


# --- requirements --------------------------------------------------------------

def test_norm_text_tolerates_punctuation_and_bullets():
    assert norm_text("- “Strong  SQL”, required.") == norm_text("strong sql required")


def test_normalize(env):
    cfg, app = env
    out = normalize(app, cfg)
    ids = [r["id"] for r in out["requirements"]]
    assert ids == ["r1", "r2", "r3", "r4", "r5"]  # r6's quote is not in the posting
    assert out["requirements"][0]["canonical"] == ["SQL"]
    assert out["requirements"][2]["canonical"] == ["Power BI", "Tableau"]
    assert out["requirements"][4]["canonical"] == [None]
    kw = {k["term"]: k for k in out["keywords"]}
    assert "Kubernetes" not in kw and kw["Looker"]["canonical"] == "Looker / Looker Studio"
    assert [f["fact"] for f in out["company_facts"]] == ["Vancouver-based online retailer"]
    assert out["hiring_contact"]["name"] == "Priya Shah"
    dropped = out["_normalized"]["dropped"]
    assert {(d["type"], d.get("id") or d.get("term") or d.get("fact")) for d in dropped} == {
        ("requirement", "r6"), ("keyword", "Kubernetes"), ("company_fact", "Carbon neutral")}
    assert "translating insights" in out["_normalized"]["unknown_terms"]
    assert json.loads((app / "requirements.json").read_text(encoding="utf-8")) == out
    assert appdir.load_app(app)["history"][-1]["step"] == "requirements"


def test_normalize_unknown_terms_csv_no_duplicates(env):
    cfg, app = env
    normalize(app, cfg)
    normalize(app, cfg)  # re-run for the same job
    path = Path(cfg["paths"]["unknown_terms"])
    rows = list(csv.reader(path.open(encoding="utf-8")))
    assert rows[0] == ["term", "job_id", "date"]
    terms = [r[0] for r in rows[1:]]
    assert len(terms) == len(set(terms)) and "translating insights" in terms
    assert all(r[1] == "7" for r in rows[1:])


@pytest.mark.parametrize("name,quote", [
    ("Dana Quill", "report to Priya Shah"),   # invented name
    ("Priya Shah", "Analytics Lead"),         # quote verbatim but no name
    ("Priya Shah", "reports to Priya Shah"),  # quote not in the posting
])
def test_hiring_contact_nulled(env, name, quote):
    cfg, app = env
    data = json.loads((app / "requirements.json").read_text(encoding="utf-8"))
    data["hiring_contact"] = {"name": name, "role": "recruiter", "quote": quote}
    (app / "requirements.json").write_text(json.dumps(data), encoding="utf-8")
    out = normalize(app, cfg)
    assert out["hiring_contact"] is None
    assert any(d["type"] == "hiring_contact" for d in out["_normalized"]["dropped"])


@pytest.mark.parametrize("mutate,msg", [
    (lambda d: d.update(requirements="x"), "'requirements'"),
    (lambda d: d["requirements"][0].update(kind="maybe"), "requirements[0]"),
    (lambda d: d["requirements"][0].update(terms="SQL"), "'terms'"),
    (lambda d: d["requirements"][1].update(id="r1"), "duplicate id"),
    (lambda d: d["keywords"][0].pop("weight"), "keywords[0]"),
    (lambda d: d["hiring_contact"].update(role="ceo"), "hiring_contact"),
])
def test_normalize_rejects_bad_shape(env, mutate, msg):
    cfg, app = env
    data = json.loads((app / "requirements.json").read_text(encoding="utf-8"))
    mutate(data)
    (app / "requirements.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(TailorError, match="requirements.json") as e:
        normalize(app, cfg)
    assert msg in str(e.value)


# --- evidence --------------------------------------------------------------------

def test_evidence_without_jev(env):
    cfg, app = env
    normalize(app, cfg)
    ev = run_evidence(app, cfg, FakeJev())  # FakeJev with no answers == unreachable Jev
    reqs = {r["id"]: r for r in ev["requirements"]}
    assert reqs["r1"]["status"] == "covered" and reqs["r1"]["method"] == "taxonomy"
    assert "northwind.sql-daily" in reqs["r1"]["passages"]
    assert reqs["r1"]["strength"] == 3  # SQL bullet naming a tool with a team scope
    assert reqs["r2"]["passages"] == ["northwind.dbt"]
    assert reqs["r3"]["status"] == "partial"  # Tableau yes, Power BI no
    assert reqs["r4"]["status"] == "missing" and reqs["r4"]["method"] == "none"
    assert reqs["r5"]["status"] == "missing" and reqs["r5"]["method"] == "none"
    terms = {t["term"]: t for t in ev["terms"]}
    assert terms["SQL"]["kind"] == "must" and terms["dbt"]["kind"] == "nice"
    assert terms["Looker / Looker Studio"]["kind"] == "keyword"
    assert terms["AI (any mention)"]["weight"] == "boilerplate"
    assert terms["SQL"]["in_base"] == {"data-analyst": True, "researcher": False}
    # dbt appears in the nice requirement and as a keyword: one term, nice wins.
    assert sum(t["term"] == "dbt" for t in ev["terms"]) == 1
    b = ev["buckets"]["data-analyst"]
    assert "SQL" in b["matched"] and "Tableau" in b["matched"]
    assert "dbt" in b["injectable"]
    assert "Power BI" in b["non_injectable"] and "Snowflake" in b["non_injectable"]
    assert 0 < b["current_pct"] < b["potential_pct"] <= 100
    assert ev["buckets"]["researcher"]["current_pct"] < b["current_pct"]
    assert "SQL" in ev["present"] and "dbt" in ev["present"]
    assert "Power BI" in ev["absent"] and "Snowflake" in ev["absent"]
    assert json.loads((app / "evidence.json").read_text(encoding="utf-8")) == ev


def test_evidence_strength(env):
    cfg, app = env
    data = json.loads((app / "requirements.json").read_text(encoding="utf-8"))
    data["requirements"] = [
        {"id": "a", "text": "Excel", "kind": "must", "terms": ["Excel"], "weight": "role", "quote": "SQL"},
        {"id": "b", "text": "Python forecasting", "kind": "must", "terms": ["Python"], "weight": "role", "quote": "SQL"},
    ]
    data["keywords"] = []
    (app / "requirements.json").write_text(json.dumps(data), encoding="utf-8")
    ev = run_evidence(app, cfg, None)
    reqs = {r["id"]: r for r in ev["requirements"]}
    assert reqs["a"]["strength"] == 1  # skills-map only
    assert reqs["b"]["strength"] == 3  # bullet naming Python with 250k records


def test_evidence_jev_second_look(env):
    cfg, app = env
    normalize(app, cfg)

    def answer(state, q):
        if q.id.startswith("r5|") and "stakeholders" in state:
            return 0.9
        return 0.1

    jev = FakeJev(answer)
    ev = run_evidence(app, cfg, jev)
    r5 = next(r for r in ev["requirements"] if r["id"] == "r5")
    assert r5["status"] == "covered" and r5["method"] == "jev" and r5["strength"] == 2
    assert r5["passages"] == ["northwind.stakeholders"]
    # Only requirements still missing after the taxonomy are asked, one call per passage.
    asked = {q.id.split("|")[0] for _, qs in jev.calls for q in qs}
    assert asked <= {"r4", "r5"}
    assert all(q.text.startswith("Does this passage show the candidate has:") for _, qs in jev.calls for q in qs)
    assert len(jev.calls) == len({s for s, _ in jev.calls})


def test_evidence_jev_candidate_cap(env):
    cfg, app = env
    cfg["evidence"] = {"jev_candidates": 1, "jev_yes": 0.6}
    normalize(app, cfg)
    jev = FakeJev(lambda s, q: 0.1)
    run_evidence(app, cfg, jev)
    per_req: dict[str, int] = {}
    for _, qs in jev.calls:
        for q in qs:
            per_req[q.id.split("|")[0]] = per_req.get(q.id.split("|")[0], 0) + 1
    assert per_req and max(per_req.values()) <= 1


# --- base --------------------------------------------------------------------------

def _prepare(env, jev=None):
    cfg, app = env
    normalize(app, cfg)
    run_evidence(app, cfg, jev)
    return cfg, app


def test_base_without_jev(env):
    cfg, app = _prepare(env)
    plan = run_base(app, cfg, FakeJev())
    assert plan["base_id"] == "data-analyst" and plan["jev_pick"] is None
    # Potential is vault-backed so the bases tie; the tie goes to the base that already says more.
    assert plan["base_scores"]["data-analyst"] == plan["base_scores"]["researcher"]
    rel = plan["bullet_relevance"]
    assert rel["experience/northwind/northwind.sql-daily"] >= 1
    assert all(0 <= v <= 3 for v in rel.values())
    assert "northwind.dbt" in plan["candidate_passages"] and "northwind.dbt" in rel
    assert appdir.load_app(app)["base_id"] == "data-analyst"
    # Each matched must-have (SQL, Tableau) appears in exactly one bullet; skills groups don't count.
    assert plan["protected_paths"] == [
        "experience/northwind/northwind.sql-daily", "experience/northwind/northwind.dashboards"]


def test_base_keeps_claude_fields(env):
    cfg, app = _prepare(env)
    appdir.write_json(app / "plan.json", {"headline": "Data Analyst", "swap_in": ["northwind.dbt"]})
    plan = run_base(app, cfg, None)
    assert plan["headline"] == "Data Analyst" and plan["swap_in"] == ["northwind.dbt"]
    assert json.loads((app / "plan.json").read_text(encoding="utf-8")) == plan


def test_base_jev_pick_within_tolerance(env):
    cfg, app = _prepare(env)
    ev = json.loads((app / "evidence.json").read_text(encoding="utf-8"))
    best = ev["buckets"]["data-analyst"]["potential_pct"]
    ev["buckets"]["researcher"]["potential_pct"] = best - 4  # within 5 points
    appdir.write_json(app / "evidence.json", ev)
    jev = FakeJev({"base_pick": "researcher"})
    plan = run_base(app, cfg, jev)
    assert plan["jev_pick"] == "researcher" and plan["base_id"] == "researcher"
    state = jev.calls[0][0]
    assert "Junior Data Analyst" in state and "researcher: Researcher" in state


def test_base_jev_pick_too_far(env):
    cfg, app = _prepare(env)
    ev = json.loads((app / "evidence.json").read_text(encoding="utf-8"))
    ev["buckets"]["researcher"]["potential_pct"] = ev["buckets"]["data-analyst"]["potential_pct"] - 10
    appdir.write_json(app / "evidence.json", ev)
    plan = run_base(app, cfg, FakeJev({"base_pick": "researcher"}))
    assert plan["jev_pick"] == "researcher" and plan["base_id"] == "data-analyst"


def test_base_jev_relevance_scores(env):
    cfg, app = _prepare(env)
    plan = run_base(app, cfg, FakeJev(lambda s, q: 3 if q.type == "score" and "Tableau" in q.text else (
        "data-analyst" if q.type == "choice" else 0)))
    assert plan["bullet_relevance"]["experience/northwind/northwind.dashboards"] == 3
    assert plan["bullet_relevance"]["experience/lab/lab.stats"] == 0


def test_base_needs_evidence(env):
    cfg, app = env
    with pytest.raises(TailorError, match="evidence.json"):
        run_base(app, cfg, None)


def test_evidence_synonym_only_is_related_and_boilerplate_not_absent(env, tmp_path):
    cfg, app = env
    idx = json.loads((tmp_path / "vault-index.json").read_text())
    idx["passages"].append({**idx["passages"][0], "id": "northwind.churn-status",
                            "text": "The churn model was still in the experimentation phase."})
    (tmp_path / "vault-index.json").write_text(json.dumps(idx))
    req = appdir.read_json(app / "requirements.json")
    req["keywords"] += [{"term": "A/B testing", "weight": "role", "quote": "A/B testing"},
                        {"term": "extended health", "weight": "boilerplate", "quote": "extended health"}]
    appdir.write_json(app / "requirements.json", req)
    ev = run_evidence(app, cfg, None)
    ab = next(t for t in ev["terms"] if t["canonical"] and t["canonical"].startswith("A/B"))
    assert ab["passages"] == [] and ab["related"] == ["northwind.churn-status"]
    b = ev["buckets"]["data-analyst"]
    assert ab["term"] in b["related"] and ab["term"] not in b["injectable"]
    assert ab["term"] not in ev["present"]
    assert "extended health" not in ev["absent"] and "extended health" not in b["non_injectable"]

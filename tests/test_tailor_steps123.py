"""Tests for steps 1-3: requirements.normalize, evidence.run_evidence, base.run_base, sources."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest
import yaml

from src.tailor import TailorError, appdir, rejects
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
    assert "Kubernetes" not in kw and kw["Looker"]["canonical"] == "Looker"
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
    assert terms["Looker"]["kind"] == "keyword"
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


# --- soft-skill evidence (VCH run, Oct 19 2026) ------------------------------------------

def _soft_env(env, tmp_path, requirements):
    cfg, app = env
    idx = json.loads((tmp_path / "vault-index.json").read_text())
    base = {"kind": "bullet", "use": "claim", "source": "primary", "numbers": [], "links": [], "section": []}
    idx["passages"] += [
        {**base, "id": "extra.strong-collaboration", "file": "extra-skills.md",
         "section": ["Interpersonal and Teamwork Skills"],
         "text": "Strong collaboration across departments, cooperation, and teamwork abilities.",
         "markdown": "Strong collaboration across departments, cooperation, and teamwork abilities."},
        {**base, "id": "soft.data-team", "file": "soft-skills.md", "kind": "table", "source": "crossref",
         "section": ["Teamwork & Collaboration"], "numbers": ["5", "80"],
         "text": "Evidence: Worked on a 5-person data team with regular contact with teams across an "
                 "80-person office; Source: northwind",
         "markdown": "Evidence: Worked on a 5-person data team with regular contact with teams across an "
                     "80-person office; Source: [[northwind]]"},
    ]
    (tmp_path / "vault-index.json").write_text(json.dumps(idx))
    req = appdir.read_json(app / "requirements.json")
    req["requirements"], req["keywords"] = requirements, []
    appdir.write_json(app / "requirements.json", req)
    return cfg, app


def test_self_description_ranks_after_a_story(env, tmp_path):
    from src.tailor.evidence import _folders, _origin_rank, passage_strength
    cfg, app = _soft_env(env, tmp_path, [
        {"id": "s1", "text": "Collaborate across departments", "kind": "nice", "terms": ["collaborate"],
         "weight": "role", "quote": "collaborate across departments"}])
    claims = claim_passages(load_index(cfg))
    assert passage_strength(claims["extra.strong-collaboration"]) == 1  # a self-description, no story
    assert passage_strength(claims["soft.data-team"]) == 2  # a row naming where it happened
    assert _origin_rank(claims["soft.data-team"], _folders(claims)) == 0  # cites a work note
    # The taxonomy only finds the self-description (it says "collaboration"); Jev is asked about the
    # story too, says yes, and the story leads.
    jev = FakeJev(lambda s, q: 0.9 if "5-person" in s or "Strong collaboration" in s else 0.1)
    s1 = run_evidence(app, cfg, jev)["requirements"][0]
    assert s1["passages"][0] == "soft.data-team" and "extra.strong-collaboration" in s1["passages"]
    assert s1["status"] == "covered" and s1["method"] == "jev" and s1["strength"] == 2


def test_jev_ranks_the_story_that_shows_a_soft_skill(env, tmp_path):
    cfg, app = _soft_env(env, tmp_path, [
        {"id": "s1", "text": "Explain results to stakeholders", "kind": "nice", "terms": ["stakeholders"],
         "weight": "role", "quote": "explain results to stakeholders"}])
    # The taxonomy finds the stakeholders line; Jev is still asked, and its "no" on another line that
    # happens to share the words keeps that line out.
    jev = FakeJev(lambda s, q: 0.9 if "Explained results" in s else 0.2)
    s1 = run_evidence(app, cfg, jev)["requirements"][0]
    assert s1["passages"] == ["northwind.stakeholders"] and s1["method"] == "taxonomy+jev"
    assert [q for _, qs in jev.calls for q in qs if q.id.startswith("s1|")]


def test_jev_candidates_are_mostly_real_bullets(env, tmp_path):
    cfg, app = _soft_env(env, tmp_path, [
        {"id": "s1", "text": "Work well across departments", "kind": "nice", "terms": [],
         "weight": "role", "quote": "work well across departments"}])
    cfg["evidence"] = {"jev_candidates": 1, "jev_generic_candidates": 0, "jev_yes": 0.6}
    jev = FakeJev(lambda s, q: 0.1)
    run_evidence(app, cfg, jev)
    asked = [s for s, qs in jev.calls for q in qs if q.id.startswith("s1|")]
    # The self-description shares more words, but the one slot goes to the real row.
    assert len(asked) == 1 and "5-person" in asked[0]


# --- confirmed matches (skill-record.json has) -------------------------------------


def _team_player(env, tmp_path):
    return _soft_env(env, tmp_path, [
        {"id": "s1", "text": "Strong team player", "kind": "nice", "terms": [], "weight": "role",
         "quote": "a strong team player"}])


def _confirm(cfg, **entry):
    path = Path(cfg["paths"]["skill_record"])
    data = appdir.read_json(path) if path.exists() else {"has": []}
    data.setdefault("has", []).append({"term": "collaboration/teamwork", "passage": "soft.data-team", **entry})
    appdir.write_json(path, data)


def test_confirmed_pair_counts_first_without_asking_jev(env, tmp_path):
    cfg, app = _team_player(env, tmp_path)
    # Confirmed for "collaboration" on another posting; this one words it "team player".
    _confirm(cfg, source="jake")
    jev = FakeJev(lambda s, q: 0.1)
    s1 = run_evidence(app, cfg, jev)["requirements"][0]
    assert s1["passages"][0] == "soft.data-team" and s1["status"] == "covered" and s1["method"] == "confirmed"
    assert not [q for s, qs in jev.calls for q in qs if "5-person" in s]


def test_candidate_confirm_beats_a_reject_but_plan_and_jev_confirms_dont(env, tmp_path):
    cfg, app = _team_player(env, tmp_path)
    _write_rejects(cfg, ("collaboration/teamwork", "soft.data-team"))
    _confirm(cfg, source="plan")
    assert not rejects.confirmed(cfg)
    assert run_evidence(app, cfg, FakeJev(lambda s, q: 0.1))["requirements"][0]["status"] == "missing"
    rejects.add_confirms(cfg, [{"term": "Collaboration/teamwork", "passage": "soft.data-team", "source": "jake"}])
    assert [c["source"] for c in rejects.load_confirms(cfg)] == ["jake"]  # upgraded, not duplicated
    assert ("collaboration/teamwork", "soft.data-team") not in rejects.pairs(cfg)
    assert run_evidence(app, cfg, FakeJev(lambda s, q: 0.1))["requirements"][0]["status"] == "covered"


def test_jev_yes_on_a_soft_skill_is_remembered_by_skill(env, tmp_path):
    cfg, app = _soft_env(env, tmp_path, [
        {"id": "s1", "text": "Collaborate across departments", "kind": "nice", "terms": [], "weight": "role",
         "quote": "collaborate across departments"}])
    run_evidence(app, cfg, FakeJev(lambda s, q: 0.9 if "5-person" in s or "Strong collab" in s else 0.1))
    saved = rejects.load_confirms(cfg)
    # The story is remembered; the self-description isn't (it would then always count).
    assert [(c["passage"], c["source"], c["value"]) for c in saved] == [("soft.data-team", "jev", 0.9)]
    cfg, app = _team_player(env, tmp_path)
    jev = FakeJev(lambda s, q: 0.0)
    s1 = run_evidence(app, cfg, jev)["requirements"][0]
    assert s1["passages"] == ["soft.data-team"] and s1["status"] == "covered"
    assert not [q for s, qs in jev.calls for q in qs if "5-person" in s]


def test_weak_requirement_offers_this_shows_it(env, tmp_path):
    from src.tailor import packet, review
    from src.tailor.sources import load_index as _idx

    cfg, app = _team_player(env, tmp_path)
    s1 = run_evidence(app, cfg, FakeJev(lambda s, q: 0.35 if "5-person" in s else 0.05))["requirements"][0]
    assert s1["status"] == "missing"
    assert s1["confirm_key"] == "collaboration/teamwork"
    assert s1["candidates"] == [{"passage": "soft.data-team", "value": 0.35}]
    reqs = {r["id"]: r for r in appdir.read_json(app / "requirements.json")["requirements"]}
    md = "\n".join(packet._suggestions(app, reqs, _idx(cfg), cfg)) + "\n"
    line = next(ln for ln in md.splitlines() if "<!-- confirm:" in ln)
    assert line.startswith("- [ ] Doesn't show it  - [ ] This shows it  Collaboration/teamwork:")
    assert line.endswith("<!-- confirm: collaboration/teamwork | soft.data-team -->")
    item = next(b for b in review.parse(md) if b["type"] == "item")
    assert item["kind"] == "confirm" and review.undecided(md) == [line]
    picked = review.set_box(md, item["line"], line, "This shows it", True)
    with pytest.raises(TailorError):  # a pick can be swapped, not cleared
        review.set_box(picked, item["line"], picked.splitlines()[item["line"]], "This shows it", False)
    assert rejects.apply_confirms(picked, cfg, 7)["confirmed"] == [("collaboration/teamwork", "soft.data-team")]
    s1 = run_evidence(app, cfg, FakeJev(lambda s, q: 0.05))["requirements"][0]
    assert s1["status"] == "covered" and "candidates" not in s1
    assert "<!-- confirm:" not in "\n".join(packet._suggestions(app, reqs, _idx(cfg), cfg))  # decided


def test_doesnt_show_it_records_a_reject(env, tmp_path):
    cfg, app = _team_player(env, tmp_path)
    _confirm(cfg, source="jev", value=0.9)
    md = ("- [x] Doesn't show it  - [ ] This shows it  Collaboration/teamwork: does it show it? "
          "<!-- confirm: collaboration/teamwork | soft.data-team -->\n")
    assert rejects.apply_confirms(md, cfg, 7)["rejected"] == [("collaboration/teamwork", "soft.data-team")]
    assert rejects.load_confirms(cfg)[0]["undone"] is True
    assert ("collaboration/teamwork", "soft.data-team") in rejects.pairs(cfg)
    s1 = run_evidence(app, cfg, FakeJev(lambda s, q: 0.35 if "5-person" in s else 0.05))["requirements"][0]
    assert "soft.data-team" not in s1["passages"] and "candidates" not in s1  # never suggested again


def test_plan_adds_join_the_shared_list_and_count_in_grade(env):
    cfg, app = env
    appdir.write_json(app / "plan.json", {"evidence_adds": [
        {"term": "Tableau", "passage": "northwind.stakeholders", "reason": "built the dashboards they used"}]})
    assert ("tableau", "northwind.stakeholders") in rejects.confirmed(cfg, app)  # this job, before syncing
    new = rejects.sync_plan_adds(app, cfg)
    assert [(c["source"], c["job_id"]) for c in new] == [("plan", 7)]
    assert rejects.sync_plan_adds(app, cfg) == []  # idempotent
    ev = {"terms": [{"term": "Tableau", "canonical": "Tableau", "passages": []}], "present": [],
          "absent": ["Tableau"], "requirements": []}
    out = rejects.add_evidence(ev, {"requirements": []}, rejects.confirmed(cfg, app))
    assert out["present"] == ["Tableau"] and not out["absent"]
    assert out["terms"][0]["passages"] == ["northwind.stakeholders"]


# --- false-match guards (VCH run, Oct 18 2026) ----------------------------------------


@pytest.mark.parametrize("term,canon", [
    ("Oracle", "SQL"), ("MS SQL", "SQL"), ("Access", "Microsoft Access"),
    ("Word", "Microsoft Word"), ("SPSS", "SPSS"), ("Oracle Fusion", "ERP (SAP/Oracle/Workday)"),
])
def test_taxonomy_posting_terms(term, canon):
    from src.tailor import taxonomy

    assert taxonomy.canonical(term) == canon


@pytest.mark.parametrize("text,absent", [
    ("Placed first at the WiDS × SAP datathon", "ERP (SAP/Oracle/Workday)"),
    ("Scrapes Workday career sites for postings", "ERP (SAP/Oracle/Workday)"),
    ("Exchanged OAuth codes for access tokens", "Microsoft Access"),
    ("Generates Word documents with python-docx", "Microsoft Word"),
])
def test_taxonomy_no_false_match(text, absent):
    from src.tailor import taxonomy

    assert absent not in taxonomy.find(text)


def test_taxonomy_data_qa_is_data_quality():
    from src.tailor import taxonomy

    text = "Validated and combined Shopify, BigCommerce, Yotpo and Google Sheets data landing in BigQuery"
    assert "data quality / validation" in taxonomy.find(text)
    assert "data quality / validation" in taxonomy.find("Data QA and integration of third-party sources")


def _with_reqs(app, reqs, keywords=()):
    data = appdir.read_json(app / "requirements.json")
    data["requirements"] = reqs
    data["keywords"] = list(keywords)
    appdir.write_json(app / "requirements.json", data)


def test_unknown_term_needs_jev(env):
    cfg, app = env
    # "transformer" isn't in the taxonomy; the spam-classifier passage mentions it.
    _with_reqs(app, [{"id": "a", "text": "Transformers", "kind": "nice", "terms": ["transformer"],
                      "weight": "role", "quote": "SQL"}])
    ev = run_evidence(app, cfg, None)
    assert ev["requirements"][0]["status"] == "missing"
    assert "transformer" in ev["absent"]
    jev = FakeJev(lambda s, q: 0.9 if q.id == "shows" and "PyTorch" in s else 0.1)
    ev = run_evidence(app, cfg, jev)
    assert ev["requirements"][0]["status"] == "covered"
    assert ev["terms"][0]["passages"] == ["proj.spam.model"]


def test_unknown_term_rejected_by_jev(env):
    cfg, app = env
    _with_reqs(app, [{"id": "a", "text": "Transformers", "kind": "nice", "terms": ["transformer"],
                      "weight": "role", "quote": "SQL"}])
    ev = run_evidence(app, cfg, FakeJev(lambda s, q: 0.1))
    assert ev["terms"][0]["passages"] == [] and "transformer" in ev["absent"]


@pytest.mark.parametrize("quote,status", [
    ("Bachelor's degree in Statistics or a related field", "covered"),
    ("Bachelor's or Master's degree in a quantitative field", "covered"),
    ("Master's degree in Statistics required", "missing"),
])
def test_degree_requirement(env, quote, status):
    cfg, app = env
    _with_reqs(app, [{"id": "a", "text": quote, "kind": "must", "terms": [], "weight": "role", "quote": quote}])
    r = run_evidence(app, cfg, FakeJev(lambda s, q: 0.9))["requirements"][0]
    assert r["status"] == status and r["method"] == "degree"
    assert r["passages"] == (["course.degree"] if status == "covered" else [])


def test_synonym_only_requirement_is_partial(env):
    cfg, app = env
    # "Data QA" is a synonym of data quality, not the posting's wording.
    idx = json.loads((Path(cfg["paths"]["vault_index"])).read_text())
    idx["passages"].append({**idx["passages"][0], "id": "northwind.qa",
                            "text": "Data QA of third-party sources landing in BigQuery."})
    Path(cfg["paths"]["vault_index"]).write_text(json.dumps(idx))
    _with_reqs(app, [{"id": "a", "text": "Maintain data quality", "kind": "nice", "terms": ["data quality"],
                      "weight": "role", "quote": "SQL"}])
    r = run_evidence(app, cfg, None)["requirements"][0]
    assert r["status"] == "partial" and r["method"] == "related" and "northwind.qa" in r["passages"]


# --- reject list and Jev cache ----------------------------------------------------

def _write_rejects(cfg, *pairs_):
    appdir.write_json(Path(cfg["paths"]["skill_record"]), {"not_shown": [
        {"term": t, "passage": p, "reason": "test", "job_id": 1, "added": "2026-10-18"} for t, p in pairs_]})


def test_evidence_skips_rejected_pairs(env):
    cfg, app = env
    normalize(app, cfg)
    _write_rejects(cfg, ("DBT", "northwind.dbt"), ("SQL", "base"))
    ev = run_evidence(app, cfg, FakeJev())
    reqs = {r["id"]: r for r in ev["requirements"]}
    assert "northwind.dbt" not in reqs["r2"]["passages"]
    terms = {t["term"]: t for t in ev["terms"]}
    assert "northwind.dbt" not in terms["dbt"]["passages"]
    assert terms["SQL"]["in_base"] == {"data-analyst": False, "researcher": False}  # base match rejected
    assert "northwind.sql-daily" in reqs["r1"]["passages"]  # the passage itself still counts


def test_undone_reject_is_ignored(env):
    cfg, app = env
    normalize(app, cfg)
    appdir.write_json(Path(cfg["paths"]["skill_record"]), {"not_shown": [
        {"term": "dbt", "passage": "northwind.dbt", "undone": True}]})
    ev = run_evidence(app, cfg, FakeJev())
    assert {r["id"]: r for r in ev["requirements"]}["r2"]["passages"] == ["northwind.dbt"]


def test_sync_plan_drops_and_undo(env):
    cfg, app = env
    appdir.write_json(app / "plan.json", {"evidence_drops": [
        {"term": "Excel", "passage": "proj.x", "reason": "an export, not the skill"},
        {"term": "excel", "passage": "proj.x", "reason": "duplicate"},
        {"term": "reporting", "passage": "base"}]})
    new = rejects.sync_plan_drops(app, cfg)
    assert [(r["term"], r["passage"], r["job_id"]) for r in new] == [("Excel", "proj.x", 7), ("reporting", "base", 7)]
    assert rejects.sync_plan_drops(app, cfg) == []  # idempotent
    assert ("excel", "proj.x") in rejects.pairs(cfg)
    md = "- [x] Undo  Excel (proj.x): an export, not the skill (new)\n- [ ] Undo  reporting (base): x\n"
    assert rejects.apply_undos(md, cfg) == [("excel", "proj.x")]
    assert ("excel", "proj.x") not in rejects.pairs(cfg)
    assert rejects.sync_plan_drops(app, cfg) == []  # an undone pair is never re-added
    assert ("excel", "proj.x") not in rejects.pairs(cfg, app)  # Undo = it shows the skill, which beats this plan too
    assert ("excel", "proj.x") in rejects.confirmed(cfg)


def test_scrub_evidence_for_repair_notes():
    ev = {"requirements": [{"id": "r2", "passages": ["resess.six-skills", "course.x"]}],
          "terms": [{"term": "problem solving", "canonical": "problem solving",
                     "passages": ["resess.six-skills"], "related": []}]}
    req = {"requirements": [{"id": "r2", "text": "Analytical skills", "terms": ["problem-solving"]}]}
    out = rejects.scrub_evidence(ev, req, {("problem solving", "resess.six-skills")})
    assert out["requirements"][0]["passages"] == ["course.x"]
    assert out["terms"][0]["passages"] == []
    assert ev["requirements"][0]["passages"][0] == "resess.six-skills"  # input untouched


def test_unknown_term_answers_are_cached(env):
    cfg, app = env
    _with_reqs(app, [{"id": "a", "text": "Transformers", "kind": "nice", "terms": ["transformer"],
                      "weight": "role", "quote": "SQL"}])
    calls = []

    def answer(s, q):
        calls.append(q.id)
        return 0.9 if "PyTorch" in s else 0.1

    run_evidence(app, cfg, FakeJev(answer))
    assert calls
    n = len(calls)
    ev = run_evidence(app, cfg, FakeJev(answer))  # same questions: all from the cache
    assert len(calls) == n
    assert ev["terms"][0]["passages"] == ["proj.spam.model"]
    ev = run_evidence(app, cfg, None)  # cached answers count even with no Jev
    assert ev["terms"][0]["passages"] == ["proj.spam.model"]


def test_jev_yes_on_an_or_list_backs_no_single_tool(env):
    cfg, app = env
    # Nothing in the vault names either tool; Jev says some bullets fit the requirement.
    _with_reqs(app, [{"id": "a", "text": "Power BI or Power Automate dashboards", "kind": "nice",
                      "terms": ["Power BI", "Power Automate"], "weight": "role", "quote": "SQL"}])
    ev = run_evidence(app, cfg, FakeJev(lambda s, q: 0.9))
    r = ev["requirements"][0]
    assert r["status"] == "covered" and r["method"] == "jev" and r["passages"]
    assert {"Power BI", "Power Automate"} <= set(ev["absent"])


def test_jev_yes_without_the_wording_does_not_make_a_hard_skill_present(env):
    cfg, app = env
    # No passage says "quantitative"; Jev says the analysis bullets fit. The requirement is covered,
    # but the check would call "quantitative analysis" invented, so the term isn't present.
    _with_reqs(app, [{"id": "a", "text": "Quantitative analysis of sales data", "kind": "nice",
                      "terms": ["quantitative analysis"], "weight": "role", "quote": "SQL"}])
    ev = run_evidence(app, cfg, FakeJev(lambda s, q: 0.9 if "SQL" in s else 0.1))
    r = ev["requirements"][0]
    assert r["status"] == "covered" and r["method"] == "jev" and r["passages"]
    t = ev["terms"][0]
    assert t["passages"] == [] and t["related"]
    assert "quantitative analysis" in ev["absent"]


def test_evidence_command_prints_a_short_summary(env, monkeypatch):
    from click.testing import CliRunner

    from src.tailor import cli

    cfg, app = env
    normalize(app, cfg)
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    monkeypatch.setattr(cli, "_jev", lambda: None)
    res = CliRunner().invoke(cli.main, ["evidence", str(app)])
    assert res.exit_code == 0, res.output
    out = json.loads(res.output)
    full = json.loads((app / "evidence.json").read_text(encoding="utf-8"))
    assert out["present"] == full["present"] and out["absent"] == full["absent"]
    assert out["requirements"][0] == {"id": "r1", "status": "covered", "strength": 3, "method": "taxonomy"}
    assert "terms" not in out and "buckets" not in out  # those stay in evidence.json


def test_positional_embeddings_are_not_embeddings():
    from src.tailor import taxonomy as tx

    assert "embeddings" not in tx.find("Rotary Position Embeddings (RoPE) and RoPE positional embeddings")
    assert "embeddings" in tx.find("document loading, chunking, embeddings and search")
    assert tx.canonical("RAG") == "RAG (retrieval-augmented generation)"
    assert "RAG (retrieval-augmented generation)" not in tx.find("dragging the rag doll")


def test_years_requirement_gets_no_this_shows_it(env, tmp_path):
    cfg, app = _soft_env(env, tmp_path, [
        {"id": "s1", "text": "About 2+ years of software development", "kind": "must", "terms": [], "weight": "role",
         "quote": "2+ years of professional software development experience"}])
    s1 = run_evidence(app, cfg, FakeJev(lambda s, q: 0.35))["requirements"][0]
    assert "candidates" not in s1


def test_known_gap_matches_nothing_and_asks_jev_nothing(env):
    cfg, app = env
    _with_reqs(app, [{"id": "a", "text": "Tableau", "kind": "must", "terms": ["Tableau"],
                      "weight": "role", "quote": "Tableau"}])
    assert run_evidence(app, cfg, FakeJev(lambda s, q: 0.1))["requirements"][0]["status"] == "covered"
    appdir.write_json(Path(cfg["paths"]["skill_record"]), {"lacks": [{"skill": "tableau", "added": "2026-10-20"}]})
    jev = FakeJev(lambda s, q: 0.35)
    ev = run_evidence(app, cfg, jev)
    r = ev["requirements"][0]
    assert r["status"] == "missing" and r["passages"] == [] and "candidates" not in r
    assert ev["terms"][0]["passages"] == [] and "Tableau" in ev["absent"]
    assert not jev.calls
    # The candidate's own "This shows it" for the skill wins over the gap list.
    rejects.add_confirms(cfg, [{"term": "Tableau", "passage": "northwind.dashboards", "source": "jake"}])
    assert rejects.gap_keys(cfg) == set()


def test_skill_record_reads_the_older_separate_files_until_it_exists(env):
    cfg, _ = env
    folder = Path(cfg["paths"]["skill_record"]).parent
    folder.mkdir(parents=True, exist_ok=True)
    appdir.write_json(folder / "evidence-confirms.json", {"confirms": [
        {"term": "SQL", "passage": "northwind.sql-daily", "source": "jake"}]})
    appdir.write_json(folder / "known-gaps.json", {"gaps": [{"skill": "Node.js"}]})
    appdir.write_json(folder / "evidence-rejects.json", {"rejects": [
        {"term": "dbt", "passage": "northwind.dbt", "reason": "x"}]})
    assert ("sql", "northwind.sql-daily") in rejects.confirmed(cfg)
    assert rejects.gap_keys(cfg) == {"node.js"} and ("dbt", "northwind.dbt") in rejects.pairs(cfg)
    # The first save writes all three sections into the one record.
    rejects.add_confirms(cfg, [{"term": "Tableau", "passage": "northwind.dashboards", "source": "jake"}])
    data = appdir.read_json(Path(cfg["paths"]["skill_record"]))
    assert [len(data[k]) for k in ("has", "lacks", "not_shown")] == [2, 1, 1]

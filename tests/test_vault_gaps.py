"""Gaps read from the experience vault, and which part of a posting a tool sits in."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from src.posting_sections import Sections
from src.score import score_job
from src.vault_gaps import find_gaps, load_vault

CFG = yaml.safe_load(
    (Path(__file__).resolve().parent.parent / "config" / "settings.yaml").read_text(encoding="utf-8")
)["score"]


@pytest.fixture
def vault(tmp_path):
    passages = [
        {"id": "a", "text": "Wrote SQL in BigQuery daily and built Looker Studio dashboards"},
        {"id": "b", "text": "Python with pandas and scikit-learn; AWS S3 for storage"},
        {"id": "c", "text": "Java OOP coursework (CPSC 210)"},
        {"id": "d", "text": "Used Tableau once", "use": "interview"},  # not a claim: doesn't count
    ]
    path = tmp_path / "vault-index.json"
    path.write_text(json.dumps({"passages": passages}), encoding="utf-8")
    return load_vault(path)


def labels(text, vault, **cfg):
    return [(g.label, g.preferred) for g in find_gaps(text, vault, {**CFG["vault_gaps"], **cfg})]


def test_vault_tools_come_from_claim_passages(vault):
    assert {"SQL", "BigQuery", "Looker Studio", "Python", "pandas", "AWS S3", "Java"} <= vault.tools
    assert "Tableau" not in vault.tools
    assert load_vault("no/such/index.json") is None


def test_one_option_is_enough(vault):
    assert labels("Experience with Python, R, or Julia", vault) == []
    assert labels("Experience with Scala, Rust, or Julia", vault) == [("Julia or Rust or Scala", False)]
    # An open list takes any tool of its type: Looker Studio covers "BI tools such as Tableau, Power BI".
    assert labels("Experience with BI tools such as Tableau, Power BI and Qlik", vault) == []


def test_a_tool_asked_alone_still_counts_after_a_met_list(vault):
    text = "Build services in Python, Go, or Rust.\nThe backend is written in Python and Golang."
    assert labels(text, vault) == [("Go", False)]


def test_nice_to_haves_cost_less_and_about_text_costs_nothing(vault):
    text = ("## About us\nOur portfolio includes Azure Cosmos DB and Power BI.\n\n"
            "## Requirements\n- SQL and dbt\n\n## Nice to have\n- Airflow\n")
    gaps = find_gaps(text, vault, CFG["vault_gaps"])
    assert [(g.label, g.preferred, g.points) for g in gaps] == [("dbt", False, -2), ("Airflow", True, -1)]


def test_light_evidence_halves_a_gap(vault):
    gaps = find_gaps("Strong Java and Spring experience required.", vault,
                     {**CFG["vault_gaps"], "heavier": {}, "points": -4})
    assert [(g.label, g.points) for g in gaps] == [("Java", -2), ("Spring", -4)]
    (gap,) = find_gaps("Professional Java development", vault, CFG["vault_gaps"])
    assert gap.label == "Java" and gap.points == -2.5  # Java is -5, halved: a course isn't a job


def test_each_gap_counts_once(vault):
    text = "Use Airflow and Cloud Composer on GCP. Airflow DAGs. GCP experience."
    assert len(labels(text, vault)) == 2  # Airflow, and Cloud Composer with its platform GCP


def test_score_uses_the_vault_and_skips_the_old_gap_list(vault):
    text = "Data Analyst. SQL, Python and dashboards daily. Experience with C++, Java, or Python. " * 5
    old = score_job(title="Data Analyst", description=text, location_category="vancouver",
                    years_experience=None, cfg=CFG)
    new = score_job(title="Data Analyst", description=text, location_category="vancouver",
                    years_experience=None, cfg=CFG, vault=vault)
    assert any("gaps (c++" in r for r in old.reasons)
    assert not any("not in your vault" in r for r in new.reasons) and new.score > old.score


@pytest.mark.parametrize("text, word, kind", [
    ("## Basic Qualifications\n- SQL\n\n## Preferred Qualifications\n- dbt", "dbt", "preferred"),
    ("## Basic Qualifications\n- SQL\n\n## Preferred Qualifications\n- dbt", "SQL", "required"),
    ("## What you'll bring\n- Python is a plus\n- SQL", "Python", "preferred"),
    ("## What you'll bring\n- Strong SQL (Redshift experience a plus)", "SQL", "required"),
    ("**About Velixo**\nVelixo makes Excel-based reporting.\n\n## Requirements\n- SQL", "Excel", "about"),
    ("## About the team\nWe build tools.\n\n- Experience with Python", "Python", "other"),
    ("We connect suppliers through 180+ ERP integrations.", "ERP", "about"),
    ("We are seeking an analyst with strong SQL.", "SQL", "other"),
    ("* Experience with **CRM platforms; HubSpot preferred**.\n* Strong Excel skills.", "Excel", "other"),
])
def test_sections(text, word, kind):
    assert Sections(text).kind(text.index(word)) == kind


def test_skill_record_corrects_the_vault(tmp_path):
    passages = [
        {"id": "a", "text": "Wrote SQL in BigQuery daily"},
        {"id": "b", "text": "Raw tables collected by the Dev team via Dataform"},
        {"id": "c", "text": "Skills: Node.js, Python"},
    ]
    index = tmp_path / "vault-index.json"
    index.write_text(json.dumps({"passages": passages}), encoding="utf-8")
    assert {"Dataform", "Node.js"} <= load_vault(index).tools
    record = tmp_path / "skill-record.json"
    record.write_text(json.dumps({
        "has": [{"term": "tableau", "passage": "a", "source": "jake"},
                {"term": "Power BI", "passage": "a", "source": "jev"},  # Jev answers don't add tools
                {"term": "Looker", "passage": "a", "source": "jake", "undone": True}],
        "lacks": [{"skill": "Node.js"}],
        "not_shown": [{"term": "Dataform", "passage": "b"}],
    }), encoding="utf-8")
    v = load_vault(index, record)
    assert "Tableau" in v.tools and "BI / visualization tool" in v.types
    assert not {"Power BI", "Looker", "Node.js", "Dataform"} & v.tools
    assert {"SQL", "BigQuery", "Python"} <= v.tools
    assert labels("Experience with Tableau and Node.js", v) == [("Node.js", False)]


def haves(text, vault, skip=frozenset(), **cfg):
    from src.vault_gaps import find_haves
    return {h.skill: (h.preferred, h.points) for h in find_haves(text, vault, {**CFG["vault_gaps"], **cfg}, skip)}


def test_tools_the_vault_shows_earn_points_like_gaps_cost_them(vault):
    got = haves("## Requirements\n- Python, AWS S3 and Tableau\n\n## Preferred\n- Looker Studio", vault)
    assert "Tableau" not in got  # the vault has no Tableau: that is a gap, not points
    assert got.get("AWS") == (False, 2) or got.get("AWS S3") == (False, 2)
    assert got["Looker Studio"] == (True, 1.0)  # a nice-to-have counts half


def test_hand_weighted_tools_and_employer_text_earn_nothing_here(vault):
    text = "## About us\nWe use Looker Studio everywhere.\n\n## Requirements\n- Python and pandas"
    got = haves(text, vault, skip={"pandas"})
    assert "Looker Studio" not in got and "pandas" not in got and "Python" in got


def test_score_gives_points_for_vault_tools_not_in_the_hand_list(vault):
    text = "Builder. Hands-on with AWS S3, scikit-learn and Looker Studio every day. " * 5
    kw = dict(title="Builder", description=text, location_category="vancouver", years_experience=None, cfg=CFG)
    assert score_job(**kw, vault=vault).score > score_job(**kw).score

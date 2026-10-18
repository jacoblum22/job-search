"""Tests for src/tailor/humanize.py: flags, patch guards and the revert."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from src.tailor.appdir import write_json
from src.tailor.humanize import humanize_apply, humanize_flags

CFG = {"paths": {"bases": "no-such-dir", "vault_index": "no-such-dir/vault.json"}}

RESUME = {
    "id": "data-analyst",
    "summary": {"id": "summary", "text": "Data analyst who built dynamic dashboards."},
    "experience": [
        {
            "id": "acme",
            "title": "Analyst",
            "company": "Acme",
            "dates": "Jan 2026 – Present",
            "bullets": [
                {"id": "acme.a", "text": "Leveraged SQL to cut report time by 40% across 3 teams."},
                {"id": "acme.b", "text": "Maintained dashboards for the operations team."},
            ],
        }
    ],
}
LETTER = {
    "greeting": "Dear Hiring Manager,",
    "paragraphs": [
        {"text": "I am excited to apply for the analyst role."},
        {"text": "I wrote SQL daily for 2 years."},
    ],
    "sign_off": "Sincerely,\nAlex Rivera",
}


def make_app(tmp_path: Path, posting="Write SQL daily.") -> Path:
    app = tmp_path / "app"
    d = app / "drafts" / "r2"
    d.mkdir(parents=True)
    write_json(app / "app.json", {"history": [], "best_round": 2, "base_id": None})
    (app / "posting.md").write_text(posting, encoding="utf-8")
    (d / "resume.yaml").write_text(yaml.safe_dump(RESUME, sort_keys=False), encoding="utf-8")
    write_json(d / "cover-letter.json", LETTER)
    # a worse round that must not be used
    other = app / "drafts" / "r1"
    other.mkdir(parents=True)
    (other / "resume.yaml").write_text("id: x\n", encoding="utf-8")
    return app


def patches(app, items):
    write_json(app / "humanize" / "patches.json", items)


def test_flags_cover_bullets_summary_and_letter_paragraphs(tmp_path):
    app = make_app(tmp_path)
    flags = humanize_flags(app, CFG)
    by_path = {f["path"]: f for f in flags}
    assert set(by_path) == {"summary", "experience/acme/acme.a", "letter/0"}
    assert "banned:leverage" not in by_path["experience/acme/acme.a"]["reasons"]
    assert "banned:leveraged" in by_path["experience/acme/acme.a"]["reasons"]
    assert any(r.startswith("opener:") for r in by_path["letter/0"]["reasons"])
    assert json.loads((app / "humanize" / "flags.json").read_text()) == flags


def test_posting_terms_are_protected(tmp_path):
    app = make_app(tmp_path, posting="We want someone with dynamic dashboards and who leveraged SQL.")
    paths = {f["path"] for f in humanize_flags(app, CFG)}
    assert "summary" not in paths and "experience/acme/acme.a" not in paths


def test_own_texts_are_protected(tmp_path):
    app = make_app(tmp_path)
    vault = app.parent / "vault.json"
    vault.write_text(json.dumps({"passages": [{"id": "p", "text": "I leveraged SQL at school."}]}), encoding="utf-8")
    flags = humanize_flags(app, {"paths": {"bases": "none", "vault_index": str(vault)}})
    assert "experience/acme/acme.a" not in {f["path"] for f in flags}


def test_apply_good_patch_and_guards(tmp_path):
    app = make_app(tmp_path)
    humanize_flags(app, CFG)
    patches(
        app,
        [
            {"path": "experience/acme/acme.a", "replacement": "Used SQL to cut report time by 40% across 3 teams."},
            {"path": "summary", "replacement": "Data analyst who built dashboards for 5 teams."},  # adds a number
            {"path": "experience/acme/acme.b", "replacement": "Ran dashboards."},  # not flagged
            {"path": "letter/0", "replacement": "I am thrilled to apply for the analyst role."},  # new banned opener
            {"path": "letter/1", "replacement": "x"},  # not flagged
        ],
    )
    out = humanize_apply(app, CFG)
    assert [a["path"] for a in out["applied"]] == ["experience/acme/acme.a"]
    reasons = {r["path"]: r["reason"] for r in out["rejected"]}
    assert "number" in reasons["summary"]
    assert "not flagged" in reasons["experience/acme/acme.b"]
    assert "banned" in reasons["letter/0"]
    assert out["reverted"] is False
    resume = yaml.safe_load((app / "humanize" / "resume.yaml").read_text())
    assert resume["experience"][0]["bullets"][0]["text"].startswith("Used SQL")
    assert resume["summary"]["text"] == RESUME["summary"]["text"]
    letter = json.loads((app / "humanize" / "cover-letter.json").read_text())
    assert letter["paragraphs"][0]["text"] == LETTER["paragraphs"][0]["text"]


def test_number_guard_catches_removed_and_changed_numbers(tmp_path):
    app = make_app(tmp_path)
    humanize_flags(app, CFG)
    patches(
        app,
        [
            {"path": "experience/acme/acme.a", "replacement": "Used SQL to cut report time across 3 teams."},
        ],
    )
    out = humanize_apply(app, CFG)
    assert out["applied"] == [] and "number" in out["rejected"][0]["reason"]
    patches(app, [{"path": "experience/acme/acme.a", "replacement": "Used SQL to cut report time by 14% across 3 teams."}])
    out = humanize_apply(app, CFG)
    assert out["applied"] == [] and "number" in out["rejected"][0]["reason"]


def test_whole_pass_reverts_when_style_hits_go_up(tmp_path):
    app = make_app(tmp_path)
    humanize_flags(app, CFG)
    # keeps the same banned word (so the per-patch check passes) but says it twice
    patches(
        app,
        [
            {
                "path": "experience/acme/acme.a",
                "replacement": "Leveraged SQL and leveraged reports to cut report time by 40% across 3 teams.",
            },
        ],
    )
    out = humanize_apply(app, CFG)
    assert out["reverted"] is True and out["applied"] == []
    assert "reverted" in out["note"]
    resume = yaml.safe_load((app / "humanize" / "resume.yaml").read_text())
    assert resume["experience"][0]["bullets"][0]["text"] == RESUME["experience"][0]["bullets"][0]["text"]
    assert resume["summary"]["text"] == RESUME["summary"]["text"]


def test_apply_without_flags_or_patches_writes_final_copies(tmp_path):
    app = make_app(tmp_path)
    write_json(app / "humanize" / "flags.json", [])
    res = humanize_apply(app, CFG)
    assert res["applied"] == [] and res["rejected"] == []
    assert (app / "humanize" / "resume.yaml").exists()

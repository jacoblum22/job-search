"""Step 4: apply Claude's edits.json to the base resume through the gates.

Every edit either lands in drafts/r<N>/resume.yaml or is rejected with a reason
in applied.json. Round 1 edits the chosen base; repair rounds edit the previous
round's resume.yaml and only inside feedback.json `sections`.
"""

from __future__ import annotations

import copy
import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from src.resume import iter_bullets, load_resume, validate
from src.tailor import TailorError
from src.tailor.appdir import log, read_json, round_dir, write_json
from src.tailor.paths import resolve

LOCKED_FIELDS = {
    "title", "company", "location", "dates", "school", "degree", "name", "url", "contact", "id",
}
ACTIONS = {"replace", "append", "remove", "reorder", "add_skill"}
SECTIONS = {"summary", "skills", "experience", "projects", "education"}


# ---------------------------------------------------------------------------
# Shared loaders (also used by checks.py and letter.py)
# ---------------------------------------------------------------------------


def norm(s: str) -> str:
    """Case- and whitespace-insensitive form used to compare texts."""
    return re.sub(r"\s+", " ", str(s).replace("’", "'")).strip().lower()


def load_index(cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Vault index passages by id."""
    data = read_json(resolve(cfg, "vault_index"))
    return {p["id"]: p for p in data.get("passages", [])}


def load_base(app_dir: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    """The base resume named by plan.json.base_id (found by file stem or by its `id`)."""
    plan = read_json(app_dir / "plan.json")
    base_id = plan.get("base_id")
    if not base_id:
        raise TailorError(f"plan.json in {app_dir} has no base_id")
    folder = resolve(cfg, "bases")
    for ext in (".yaml", ".yml"):
        p = folder / f"{base_id}{ext}"
        if p.exists():
            return load_resume(p)
    for p in sorted(folder.glob("*.y*ml")):
        try:
            data = load_resume(p)
        except Exception:  # noqa: BLE001 - an unreadable sibling base is not this app's problem
            continue
        if data.get("id") == base_id:
            return data
    raise TailorError(f"base {base_id!r} not found in {folder}")


def load_plan(app_dir: Path) -> dict[str, Any]:
    return read_json(app_dir / "plan.json")


# ---------------------------------------------------------------------------
# Letter shape
# ---------------------------------------------------------------------------


def letter_shape_errors(letter: Any) -> list[str]:
    if not isinstance(letter, dict):
        return ["cover-letter.json must be an object"]
    errs: list[str] = []
    if not isinstance(letter.get("greeting"), str) or not letter["greeting"].strip():
        errs.append("greeting: missing or not text")
    if not isinstance(letter.get("sign_off"), str) or not letter["sign_off"].strip():
        errs.append("sign_off: missing or not text")
    paras = letter.get("paragraphs")
    if not isinstance(paras, list) or not paras:
        errs.append("paragraphs: must be a non-empty list")
        return errs
    for i, p in enumerate(paras):
        where = f"paragraphs[{i}]"
        if not isinstance(p, dict):
            errs.append(f"{where}: must be an object")
            continue
        if not isinstance(p.get("text"), str) or not p["text"].strip():
            errs.append(f"{where}: text missing")
        for key in ("sources", "company_facts"):
            v = p.get(key, [])
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                errs.append(f"{where}: {key} must be a list of ids")
    return errs


# ---------------------------------------------------------------------------
# Edit application
# ---------------------------------------------------------------------------


class _Reject(Exception):
    pass


def _entry(data: dict[str, Any], section: str, eid: str) -> dict[str, Any] | None:
    for e in data.get(section) or []:
        if e.get("id") == eid:
            return e
    return None


def _in_sections(path: str, sections: list[str]) -> bool:
    return any(path == s or path.startswith(s.rstrip("/") + "/") for s in sections)


def _check_sources(edit: dict[str, Any], index: dict[str, dict[str, Any]], required: bool) -> list[str]:
    sources = edit.get("sources")
    if sources is None:
        sources = []
    if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources):
        raise _Reject("sources must be a list of passage ids")
    if required and not sources:
        raise _Reject(f"{edit['action']} must cite at least one source")
    for s in sources:
        if s not in index:
            raise _Reject(f"unknown source id {s!r}")
        if index[s].get("use", "claim") != "claim":
            raise _Reject(f"source {s!r} is {index[s].get('use')}, not a resume claim")
    return list(dict.fromkeys(sources))


def _value_text(edit: dict[str, Any]) -> str:
    v = edit.get("value")
    if not isinstance(v, str) or not v.strip():
        raise _Reject("value must be non-empty text")
    return re.sub(r"\s+", " ", v).strip()


def _apply_one(
    data: dict[str, Any], edit: dict[str, Any], index: dict[str, dict[str, Any]],
    protected: set[str], sections: list[str] | None,
) -> tuple[Any, Any]:
    """Apply one edit to `data` in place; return (before, after) or raise _Reject."""
    path, action = edit.get("path"), edit.get("action")
    if not isinstance(path, str) or not path or action not in ACTIONS:
        raise _Reject("malformed edit: needs a path and an action of " + "|".join(sorted(ACTIONS)))
    parts = path.strip("/").split("/")
    head = parts[0]

    # Gate 1: path allowed.
    if head not in SECTIONS:
        raise _Reject(f"path not allowed: unknown section {head!r}")
    if any(p in LOCKED_FIELDS for p in parts[1:]):
        raise _Reject("locked field: " + path)
    if head == "education":
        if action != "replace" or len(parts) != 3:
            raise _Reject("education is locked except replacing a coursework line")
    if sections is not None and not _in_sections(path, sections):
        raise _Reject("outside the sections allowed in this repair round")

    # Gate 2 and onward, by action.
    if action == "replace":
        value = _value_text(edit)
        if head == "summary":
            if len(parts) != 1:
                raise _Reject("path not allowed for replace")
            node = data.get("summary")
            if not node:
                raise _Reject("path does not resolve: no summary in this resume")
        elif head in ("experience", "projects"):
            if len(parts) != 3:
                raise _Reject("path not allowed for replace: expected <section>/<entry>/<bullet>")
            e = _entry(data, head, parts[1])
            node = next((b for b in (e or {}).get("bullets") or [] if b.get("id") == parts[2]), None)
            if node is None:
                raise _Reject("path does not resolve: " + path)
        elif head == "education":
            e = _entry(data, "education", parts[1])
            node = next((x for x in (e or {}).get("lines") or [] if x.get("id") == parts[2]), None)
            if node is None:
                raise _Reject("path does not resolve: " + path)
            if str(node.get("label", "")).lower() != "coursework":
                raise _Reject("locked field: only coursework lines in education may change")
        else:
            raise _Reject("path not allowed for replace")
        original = edit.get("original")
        if not isinstance(original, str) or norm(original) != norm(node["text"]):
            raise _Reject("original does not match the current text")
        sources = _check_sources(edit, index, required=True)
        if norm(value) == norm(node["text"]):
            raise _Reject("value is the same as the current text")
        before = node["text"]
        node["text"] = value
        node["sources"] = sources
        return before, value

    if action == "append":
        if head not in ("experience", "projects") or len(parts) != 2:
            raise _Reject("path not allowed for append: expected <section>/<entry>")
        e = _entry(data, head, parts[1])
        if e is None:
            raise _Reject("path does not resolve: " + path)
        value = _value_text(edit)
        sources = _check_sources(edit, index, required=True)
        taken = {b.get("id") for _, b in iter_bullets(data)}
        n = 1
        while f"{parts[1]}.new-{n}" in taken:
            n += 1
        bid = f"{parts[1]}.new-{n}"
        e.setdefault("bullets", []).append({"id": bid, "text": value, "sources": sources})
        return None, value

    if action == "remove":
        if head not in ("experience", "projects") or len(parts) != 3:
            raise _Reject("path not allowed for remove: expected <section>/<entry>/<bullet>")
        e = _entry(data, head, parts[1])
        bullets = (e or {}).get("bullets") or []
        node = next((b for b in bullets if b.get("id") == parts[2]), None)
        if node is None:
            raise _Reject("path does not resolve: " + path)
        if path in protected:
            raise _Reject("protected: the only cover for a matched must-have")
        if len(bullets) <= 1:
            raise _Reject("would leave the entry without bullets")
        bullets.remove(node)
        return node["text"], None

    if action == "reorder":
        value = edit.get("value")
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise _Reject("reorder value must be a list of ids")
        if head in ("experience", "projects") and len(parts) == 2:
            e = _entry(data, head, parts[1])
            if e is None:
                raise _Reject("path does not resolve: " + path)
            holder, key, getid = e, "bullets", lambda b: b.get("id")
        elif head == "skills" and len(parts) == 2:
            g = _entry(data, "skills", parts[1])
            if g is None:
                raise _Reject("path does not resolve: " + path)
            holder, key, getid = g, "items", lambda x: norm(x)
        elif head == "skills" and len(parts) == 1:
            holder, key, getid = data, "skills", lambda g: g.get("id")
        else:
            raise _Reject("path not allowed for reorder")
        current = holder.get(key) or []
        by_id = {getid(x): x for x in current}
        wanted = [norm(v) if head == "skills" and len(parts) == 2 else v for v in value]
        if len(wanted) != len(current) or set(wanted) != set(by_id) or len(set(wanted)) != len(wanted):
            raise _Reject("reorder must keep exactly the same items")
        before = [getid(x) if key != "items" else x for x in current]
        holder[key] = [by_id[w] for w in wanted]
        return before, [getid(x) if key != "items" else x for x in holder[key]]

    # add_skill
    if head != "skills" or len(parts) != 2:
        raise _Reject("path not allowed for add_skill: expected skills/<group>")
    g = _entry(data, "skills", parts[1])
    if g is None:
        raise _Reject("path does not resolve: " + path)
    value = edit.get("value")
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list) or not items or not all(isinstance(v, str) and v.strip() for v in items):
        raise _Reject("add_skill value must be a skill name or a list of them")
    _check_sources(edit, index, required=False)
    have = {norm(x) for x in g["items"]}
    new = [v.strip() for v in items if norm(v) not in have]
    if not new:
        raise _Reject("skill already in the group")
    before = list(g["items"])
    g["items"] = before + list(dict.fromkeys(new))
    return before, list(g["items"])


def _previous_resume(app_dir: Path, rnd: int) -> dict[str, Any]:
    p = round_dir(app_dir, rnd - 1) / "resume.yaml"
    if not p.exists():
        raise TailorError(f"{p} is missing: repair round {rnd} edits the previous draft")
    return load_resume(p)


def _feedback_sections(app_dir: Path, rnd: int) -> list[str]:
    for r in (rnd, rnd - 1):
        p = round_dir(app_dir, r) / "feedback.json"
        if p.exists():
            sections = read_json(p).get("sections")
            if not isinstance(sections, list):
                raise TailorError(f"{p} has no sections list")
            return [str(s) for s in sections]
    raise TailorError(f"feedback.json is missing for repair round {rnd} (looked in r{rnd} and r{rnd - 1})")


def apply_edits(app_dir: Path, rnd: int, cfg: dict[str, Any]) -> dict[str, Any]:
    app_dir = Path(app_dir)
    rdir = round_dir(app_dir, rnd)
    edits_doc = read_json(rdir / "edits.json")
    edits = edits_doc.get("edits")
    if not isinstance(edits, list):
        raise TailorError(f"{rdir / 'edits.json'} needs an 'edits' list")
    index = load_index(cfg)
    plan = load_plan(app_dir)
    protected = set(plan.get("protected_paths") or [])

    if rnd > 1:
        data = _previous_resume(app_dir, rnd)
        sections: list[str] | None = _feedback_sections(app_dir, rnd)
    else:
        data = copy.deepcopy(load_base(app_dir, cfg))
        sections = None

    applied: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for edit in edits:
        if not isinstance(edit, dict):
            rejected.append({"edit": edit, "reason": "malformed edit: not an object"})
            continue
        work = copy.deepcopy(data)
        try:
            before, after = _apply_one(work, edit, index, protected, sections)
        except _Reject as e:
            rejected.append({"edit": edit, "reason": str(e)})
            continue
        data = work
        applied.append({"edit": edit, "before": before, "after": after})

    problems = validate(data, require_sources=True)
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "resume.yaml").write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8"
    )

    # Letter: carry the previous round's letter forward if Claude didn't rewrite it, then check its shape.
    letter_errors: list[str] = []
    letter_path = rdir / "cover-letter.json"
    copied = False
    if not letter_path.exists() and rnd > 1:
        prev = round_dir(app_dir, rnd - 1) / "cover-letter.json"
        if prev.exists():
            shutil.copyfile(prev, letter_path)
            copied = True
    if letter_path.exists():
        try:
            letter_errors = letter_shape_errors(read_json(letter_path))
        except TailorError as e:
            letter_errors = [str(e)]

    result = {
        "round": rnd,
        "strategy": edits_doc.get("strategy"),
        "applied": applied,
        "rejected": rejected,
        "validation": problems,
        "letter_errors": letter_errors,
        "letter_copied": copied,
    }
    write_json(rdir / "applied.json", result)
    if (app_dir / "app.json").exists():
        log(app_dir, "apply-edits", f"r{rnd}: {len(applied)} applied, {len(rejected)} rejected")
    return result

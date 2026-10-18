"""Step 8: find AI-sounding lines in the best draft, then apply Claude's line patches safely.

`humanize_flags` lists the lines (resume bullets, summary, letter paragraphs)
that hit `phrases.scan`. Claude writes `humanize/patches.json`; `humanize_apply`
accepts a patch only if its path was flagged, it keeps every number exactly,
and it adds no new unprotected style hit. If the pass raises the total number of
style hits, everything is reverted.
"""

from __future__ import annotations

import copy
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from src.resume import iter_bullets, load_resume
from src.tailor import TailorError, phrases
from src.tailor.appdir import load_app, log, read_json, round_dir, write_json
from src.tailor.paths import resolve

_NUMBER = re.compile(r"[$£€]?\d[\d,]*(?:\.\d+)?(?:[kKmMbB]\b|%|\+)?")


def _numbers(text: str) -> Counter:
    return Counter(m.group(0).lower().rstrip(",") for m in _NUMBER.finditer(text))


def _best_round(app_dir: Path) -> int:
    app = load_app(app_dir)
    if app.get("best_round"):
        return int(app["best_round"])
    nums = []
    drafts = app_dir / "drafts"
    if drafts.is_dir():
        for p in drafts.iterdir():
            m = re.fullmatch(r"r(\d+)", p.name)
            if m and (p / "resume.yaml").exists():
                nums.append(int(m.group(1)))
    if not nums:
        raise TailorError(f"no draft with a resume.yaml in {drafts}")
    return max(nums)


def _own_texts(app_dir: Path, cfg: dict[str, Any]) -> list[str]:
    """The candidate's own writing: the base resume and the vault passages, when available."""
    texts: list[str] = []
    try:
        base_id = load_app(app_dir).get("base_id")
        if base_id:
            bp = resolve(cfg, "bases") / f"{base_id}.yaml"
            if bp.exists():
                base = load_resume(bp)
                texts.append(str((base.get("summary") or {}).get("text") or ""))
                texts += [str(b.get("text") or "") for _, b in iter_bullets(base)]
        vp = resolve(cfg, "vault_index")
        if vp.exists():
            texts += [str(p.get("text") or "") for p in json.loads(vp.read_text(encoding="utf-8")).get("passages") or []]
    except (OSError, ValueError, KeyError, TailorError):
        pass
    return [t for t in texts if t]


def _lines(resume: dict[str, Any], letter: dict[str, Any] | None) -> list[tuple[str, str, bool]]:
    """(path, text, is_letter) for every line the pass may touch."""
    out: list[tuple[str, str, bool]] = []
    s = resume.get("summary")
    if isinstance(s, dict) and s.get("text"):
        out.append(("summary", str(s["text"]), False))
    out += [(p, str(b.get("text") or ""), False) for p, b in iter_bullets(resume)]
    for i, para in enumerate((letter or {}).get("paragraphs") or []):
        out.append((f"letter/{i}", str(para.get("text") if isinstance(para, dict) else para), True))
    return out


def _reasons(hits: list[phrases.Hit]) -> list[str]:
    out = []
    for h in hits:
        if h.code in ("banned_word", "banned_self"):
            r = f"banned:{h.phrase}"
        elif h.code in ("opener", "closer"):
            r = f"{h.code}:{h.phrase}"
        else:
            r = h.code
        if r not in out:
            out.append(r)
    return out


def _load_best(app_dir: Path) -> tuple[int, dict[str, Any], dict[str, Any] | None]:
    n = _best_round(app_dir)
    d = round_dir(app_dir, n)
    resume = load_resume(d / "resume.yaml")
    letter = read_json(d / "cover-letter.json") if (d / "cover-letter.json").exists() else None
    return n, resume, letter


def _posting(app_dir: Path) -> str:
    p = app_dir / "posting.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def humanize_flags(app_dir: Path, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    app_dir = Path(app_dir)
    n, resume, letter = _load_best(app_dir)
    posting, own = _posting(app_dir), _own_texts(app_dir, cfg)
    flags = []
    for path, text, is_letter in _lines(resume, letter):
        hits = phrases.scan(text, posting, own, letter=is_letter)
        if hits:
            flags.append({"path": path, "text": text, "reasons": _reasons(hits)})
    write_json(app_dir / "humanize" / "flags.json", flags)
    log(app_dir, "humanize-flags", f"round {n}: {len(flags)} flagged lines")
    return flags


def _hit_keys(text: str, posting: str, own: list[str], letter: bool) -> set[tuple[str, str]]:
    return {(h.code, h.phrase.lower()) for h in phrases.scan(text, posting, own, letter=letter)}


def _set_text(resume: dict[str, Any], letter: dict[str, Any] | None, path: str, value: str) -> bool:
    if path == "summary":
        if isinstance(resume.get("summary"), dict):
            resume["summary"]["text"] = value
            return True
        return False
    if path.startswith("letter/"):
        try:
            i = int(path.split("/", 1)[1])
            para = (letter or {})["paragraphs"][i]
        except (ValueError, KeyError, IndexError, TypeError):
            return False
        if isinstance(para, dict):
            para["text"] = value
        else:
            letter["paragraphs"][i] = value
        return True
    for p, b in iter_bullets(resume):
        if p == path:
            b["text"] = value
            return True
    return False


def _total_hits(resume, letter, posting, own) -> int:
    return sum(len(phrases.scan(t, posting, own, letter=lt)) for _, t, lt in _lines(resume, letter))


def _write_outputs(app_dir: Path, resume: dict[str, Any], letter: dict[str, Any] | None) -> None:
    out = app_dir / "humanize"
    out.mkdir(parents=True, exist_ok=True)
    (out / "resume.yaml").write_text(
        yaml.safe_dump(resume, sort_keys=False, allow_unicode=True, width=10_000), encoding="utf-8"
    )
    if letter is not None:
        write_json(out / "cover-letter.json", letter)


def humanize_apply(app_dir: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    app_dir = Path(app_dir)
    n, resume, letter = _load_best(app_dir)
    flagged = {f["path"] for f in read_json(app_dir / "humanize" / "flags.json")}
    pfile = app_dir / "humanize" / "patches.json"
    # No flags means nothing to patch; the step still writes the final copies.
    patches = read_json(pfile) if pfile.exists() or flagged else []
    if not isinstance(patches, list):
        raise TailorError("humanize/patches.json must be a list of {path, replacement}")
    posting, own = _posting(app_dir), _own_texts(app_dir, cfg)

    patched, patched_letter = copy.deepcopy(resume), copy.deepcopy(letter)
    current = {p: (t, lt) for p, t, lt in _lines(resume, letter)}
    applied: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    done: set[str] = set()

    for patch in patches:
        path = str(patch.get("path", ""))
        new = str(patch.get("replacement") or "").strip()

        def reject(why: str) -> None:
            rejected.append({"path": path, "reason": why})

        if path not in flagged or path not in current:
            reject("path was not flagged")
        elif path in done:
            reject("path already patched")
        elif not new:
            reject("empty replacement")
        else:
            old, is_letter = current[path]
            if _numbers(old) != _numbers(new):
                reject("changes, adds or removes a number")
            elif _hit_keys(new, posting, own, is_letter) - _hit_keys(old, posting, own, is_letter):
                reject("introduces a new banned phrase or style pattern")
            elif _set_text(patched, patched_letter, path, new):
                applied.append({"path": path, "replacement": new})
                done.add(path)
            else:
                reject("path not found")

    reverted = False
    note = ""
    before = _total_hits(resume, letter, posting, own)
    after = _total_hits(patched, patched_letter, posting, own)
    if after > before:
        reverted = True
        note = f"style hits rose from {before} to {after}; all patches reverted"
        for a in applied:
            rejected.append({"path": a["path"], "reason": "pass reverted: style hits went up"})
        applied = []
        patched, patched_letter = resume, letter
    _write_outputs(app_dir, patched, patched_letter)
    result = {"applied": applied, "rejected": rejected, "reverted": reverted, "note": note}
    log(app_dir, "humanize-apply", f"round {n}: {len(applied)} applied, {len(rejected)} rejected" + (", reverted" if reverted else ""))
    return result

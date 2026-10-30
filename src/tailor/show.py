"""Read-only views a chat needs before it can work on an application, in one command each.

Threads that revise a packet (REW, Remarcable, Amazon, Oct 27 2026) all started the same way:
find the folder, work out which copy ships (final/, humanize/ or a round), read the resume YAML,
the letter JSON and the posting, then look up the vault passages each line cites. `show` prints
all of that as plain text. `vault` finds passages by words instead of reading vault files, and
`sent` searches what earlier applications already said ("did I give a number for sources?").
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from src.resume import iter_bullets
from src.tailor import appdir, explain
from src.tailor.paths import resolve

SECTIONS = ["summary", "skills", "experience", "projects", "education"]


def shipped(app_dir: Path) -> dict[str, Path | None]:
    """The resume and letter that go out: final/ (what was rendered, after page fit), else the
    current humanize copy, else the best round's draft."""
    app = appdir.load_app(app_dir)
    rnd = app.get("best_round")
    rd = appdir.round_dir(app_dir, int(rnd)) if rnd else None
    out: dict[str, Path | None] = {}
    for key, name in (("resume", "resume.yaml"), ("letter", "cover-letter.json")):
        options = [app_dir / "final" / name, appdir.humanized(app_dir, name), rd / name if rd else None]
        out[key] = next((p for p in options if p and p.exists()), None)
    return out


def resume_text(data: dict[str, Any], index: dict[str, dict] | None = None, *, ids: bool = True,
                passages: bool = False) -> str:
    """The resume as a reader sees it. `ids` tags each bullet with its id and cited passages, so an
    edit can name the line; `passages` also prints each cited passage under its bullet."""
    out: list[str] = []
    for key in data.get("order") or SECTIONS:
        part = data.get(key)
        if not part:
            continue
        out += ["", key.upper()]
        if key == "summary":
            out.append(str(part.get("text", "") if isinstance(part, dict) else part).strip())
        elif key == "skills":
            out += [f"{g.get('label', '')}: {', '.join(map(str, g.get('items') or []))}" for g in part]
        else:
            for e in part:
                head = [e.get(k) for k in ("title", "company", "name", "context", "school", "degree", "location")]
                line = ", ".join(str(h) for h in head if h)
                out.append(f"{line} ({e['dates']})" if e.get("dates") else line)
                for b in e.get("bullets") or []:
                    tag = f"  [{b.get('id')}; {', '.join(b.get('sources') or []) or 'no sources'}]" if ids else ""
                    out.append(f"- {str(b.get('text', '')).strip()}{tag}")
                    if passages:
                        for pid in b.get("sources") or []:
                            out.append(f"    > {pid}: {explain.passage_text(pid, index, limit=600) or '(not in the index)'}")
                for ln in e.get("lines") or []:
                    label = f"{ln['label']}: " if ln.get("label") else ""
                    out.append(f"  {label}{str(ln.get('text', '')).strip()}")
    return "\n".join(out).strip()


def letter_text(letter: dict[str, Any]) -> str:
    paras = [str(p.get("text", "") if isinstance(p, dict) else p).strip() for p in letter.get("paragraphs") or []]
    return "\n\n".join(t for t in [str(letter.get("greeting", "")).strip(), *paras,
                                   str(letter.get("sign_off", "")).strip()] if t)


def _final_files(app_dir: Path) -> list[str]:
    final = app_dir / "final"
    parse = appdir.read_json(final / "parse.json") if (final / "parse.json").exists() else {}
    out = []
    for kind in ("resume", "letter"):
        r = parse.get(kind) or {}
        if r.get("pdf"):
            out.append(f"{r['pdf']} ({r.get('pages')} page(s), parse {'ok' if r.get('ok') else 'FAILED'})")
    if (parse.get("combined") or {}).get("pdf"):
        out.append(f"{parse['combined']['pdf']} ({parse['combined'].get('pages')} page(s), resume then letter)")
    stems = {Path(s.split(" (")[0]).stem for s in out}
    # A pdf the last render didn't write is a leftover that could get uploaded by mistake.
    out += [f"{p.name} (not from the last render: delete it?)" for p in sorted(final.glob("*.pdf"))
            if parse and p.stem not in stems]
    return out


def show(app_dir: Path, cfg: dict[str, Any], *, passages: bool = False, posting: bool = False) -> str:
    app = appdir.load_app(app_dir)
    files = shipped(app_dir)
    index = None
    try:
        from src.tailor.sources import load_index

        index = load_index(cfg)
    except Exception:  # noqa: BLE001 - the text is still useful without passage lookups
        index = None
    head = [
        f"# {app.get('company')} - {app.get('title')} (job {app.get('job_id')})",
        f"folder: {app_dir}",
        f"status: {app.get('status')}; best round {app.get('best_round')}; base {app.get('base_id')}",
        (f"resume from: {files['resume'].relative_to(app_dir).as_posix() if files['resume'] else 'none'}; "
         f"letter from: {files['letter'].relative_to(app_dir).as_posix() if files['letter'] else 'none'}"),
        "edit for a revision: humanize/resume.yaml and humanize/cover-letter.json (run `revise-start` first)",
    ]
    final = _final_files(app_dir)
    if final:
        head.append("final/: " + "; ".join(final))
    olds = sorted(p.name for p in app_dir.glob("previous-version-*"))
    if olds:
        head.append("earlier versions: " + ", ".join(olds))
    parts = ["\n".join(head)]
    if files["resume"]:
        data = yaml.safe_load(files["resume"].read_text(encoding="utf-8")) or {}
        parts.append("## Resume\n" + resume_text(data, index, passages=passages))
    if files["letter"]:
        parts.append("## Cover letter\n" + letter_text(appdir.read_json(files["letter"])))
    post = app_dir / "posting.md"
    if posting and post.exists():
        parts.append("## Posting\n" + post.read_text(encoding="utf-8").strip())
    elif post.exists():
        parts.append(f"## Posting\n{post} (add --posting to print it)")
    return "\n\n".join(parts) + "\n"


def vault(cfg: dict[str, Any], terms: list[str], *, claims_only: bool = False) -> list[dict[str, Any]]:
    """Passages whose text has every term (case-blind, whole word at the start, so 'Docker' finds
    'Dockerfile' but 'R' doesn't find every word with an r)."""
    from src.tailor.sources import load_index

    rx = [re.compile(rf"(?<!\w){re.escape(t)}", re.IGNORECASE) for t in terms if t.strip()]
    out = []
    for pid, p in load_index(cfg).items():
        text = str(p.get("text") or "")
        if claims_only and p.get("use") != "claim":
            continue
        if rx and all(r.search(text) for r in rx):
            out.append({"id": pid, "where": explain.passage_label(pid, {pid: p}), "use": p.get("use"),
                        "text": text.strip()})
    return out


def _app_lines(app_dir: Path) -> list[tuple[str, str]]:
    files = shipped(app_dir)
    lines: list[tuple[str, str]] = []
    if files["resume"]:
        data = yaml.safe_load(files["resume"].read_text(encoding="utf-8")) or {}
        s = data.get("summary")
        if s:
            lines.append(("resume summary", str(s.get("text", "") if isinstance(s, dict) else s)))
        lines += [(f"resume skills ({g.get('label')})", ", ".join(map(str, g.get("items") or [])))
                  for g in data.get("skills") or []]
        lines += [(f"resume {p.split('/', 1)[1]}", str(b.get("text") or "")) for p, b in iter_bullets(data)]
    if files["letter"]:
        letter = appdir.read_json(files["letter"])
        lines += [(f"letter paragraph {i + 1}", str(p.get("text", "") if isinstance(p, dict) else p))
                  for i, p in enumerate(letter.get("paragraphs") or [])]
    return lines


def sent(cfg: dict[str, Any], pattern: str, *, statuses: list[str] | None = None) -> list[dict[str, Any]]:
    """Lines in each application's shipped resume and letter that match `pattern` (a regex,
    case-blind). `statuses` keeps only apps with one of those statuses or outcomes, e.g. ["applied"]."""
    rx = re.compile(pattern, re.IGNORECASE)
    out = []
    for path in sorted(resolve(cfg, "applications").glob("*/app.json")):
        app_dir = path.parent
        try:
            app = appdir.load_app(app_dir)
            if statuses and app.get("status") not in statuses and app.get("outcome") not in statuses:
                continue
            hits = [{"line": where, "text": text} for where, text in _app_lines(app_dir) if rx.search(text)]
        except Exception:  # noqa: BLE001, S112 - a broken folder doesn't stop the search
            continue
        if hits:
            out.append({"folder": app_dir.name, "status": app.get("status"), "hits": hits})
    return out

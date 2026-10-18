"""Read and tick the boxes in an application's check.md from the dashboard server.

check.md stays the record (approve reads it), so the server edits the same lines a
person would tick by hand: `Reviewed`, `Keep`/`Remove` (one or the other) and `Undo`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.tailor import TailorError

# One pattern per kind of line; each box is "- [ ] Name" or "- [x] Name".
_KINDS = {
    "keep_remove": re.compile(r"^- \[(?P<b0>[ xX])\] Keep\s+- \[(?P<b1>[ xX])\] Remove\s+(?P<text>.*)$"),
    "reviewed": re.compile(r"^- \[(?P<b0>[ xX])\] Reviewed\s+(?P<text>.*)$"),
    "undo": re.compile(r"^- \[(?P<b0>[ xX])\] Undo\s+(?P<text>.*)$"),
}
_OPTIONS = {"keep_remove": ["Keep", "Remove"], "reviewed": ["Reviewed"], "undo": ["Undo"]}
_BOX = re.compile(r"\[[ xX]\]")


_COMMENT = re.compile(r"\s*<!--.*?-->")


def parse(text: str) -> list[dict[str, Any]]:
    """check.md as blocks: headings, "> " notes (what a section is for), plain lines, and items
    with boxes (with their line number). An item's indented lines are its details, each with a
    level (1 for "  - ", 2 for "    - "). HTML comments (machine keys) are left out of the text."""
    blocks: list[dict[str, Any]] = []
    for i, line in enumerate(text.splitlines()):
        if not line.strip():
            continue
        if line.startswith("#"):
            blocks.append({"type": "heading", "level": len(line) - len(line.lstrip("#")),
                           "text": line.lstrip("#").strip()})
            continue
        if line.startswith(">"):
            blocks.append({"type": "note", "text": line[1:].strip()})
            continue
        for kind, rx in _KINDS.items():
            m = rx.match(line)
            if m:
                boxes = [m[f"b{n}"] != " " for n in range(len(_OPTIONS[kind]))]
                blocks.append({"type": "item", "kind": kind, "line": i, "raw": line,
                               "text": _COMMENT.sub("", m["text"]),
                               "options": [{"name": n, "checked": c} for n, c in zip(_OPTIONS[kind], boxes,
                                                                                    strict=True)],
                               "details": []})
                break
        else:
            stripped = line.lstrip()
            indent = len(line) - len(stripped)
            if indent and blocks and blocks[-1]["type"] == "item":
                blocks[-1]["details"].append({"text": stripped.removeprefix("- "), "level": 2 if indent >= 4 else 1})
            else:
                blocks.append({"type": "text", "text": stripped.removeprefix("- "),
                               "bullet": stripped.startswith("- "), "indent": line != stripped})
    return blocks


def open_items(text: str) -> int:
    """How many boxed lines still need a decision."""
    return sum(1 for b in parse(text) if b["type"] == "item" and b["kind"] != "undo"
               and not any(o["checked"] for o in b["options"]))


def set_box(text: str, line: int, raw: str, option: str, checked: bool) -> str:
    """Tick or untick one box. `raw` is the line as the page saw it, so a check.md that
    changed since (a re-run packet) is refused instead of ticking the wrong line.
    Keep and Remove are exclusive: ticking one clears the other."""
    lines = text.splitlines()
    if not 0 <= line < len(lines) or lines[line] != raw:
        raise TailorError("check.md changed since the page loaded; reload and try again")
    for kind, rx in _KINDS.items():
        if rx.match(raw):
            break
    else:
        raise TailorError("that line has no box to tick")
    names = _OPTIONS[kind]
    if option not in names:
        raise TailorError(f"{option!r} is not a box on that line")
    states = [o["checked"] for o in parse(raw)[0]["options"]]
    idx = names.index(option)
    states[idx] = checked
    if kind == "keep_remove" and checked:
        states[1 - idx] = False
    marks = iter("x" if s else " " for s in states)
    lines[line] = _BOX.sub(lambda _: f"[{next(marks)}]", raw, count=len(states))
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def tick(app_dir: Path, line: int, raw: str, option: str, checked: bool) -> list[dict[str, Any]]:
    path = app_dir / "check.md"
    if not path.exists():
        raise TailorError("check.md is missing: run the packet step first")
    text = set_box(path.read_text(encoding="utf-8"), line, raw, option, checked)
    path.write_text(text, encoding="utf-8")
    return parse(text)

"""Parse check on a rendered PDF: does an ATS-style text extraction read it back correctly?

Generic checks only (text layer, private-use glyphs, page count, contact details, section
headings and their order) plus a round trip: every bullet, title, company, date range (or
letter paragraph) of the source has to come back in the extracted text, in order.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pdfplumber
from rapidfuzz import fuzz

from src.resume import DEFAULT_ORDER, SECTION_TITLES, iter_bullets

FUZZ_MIN = 95
_PUA = re.compile("[-]")
_CITY = re.compile(r"[A-Z][A-Za-z.'\- ]+,\s*[A-Z]{2}\b")


def _check(code: str, ok: bool, detail: str = "", severity: str = "critical") -> dict[str, Any]:
    return {"code": code, "ok": bool(ok), "detail": detail, "severity": severity}


def _squash(text: str) -> str:
    """Lower-case letters and digits only: whitespace, hyphens, quotes and bullets all vanish."""
    return re.sub(r"[\W_]+", "", str(text).lower())


def _read(pdf_path: Path) -> tuple[str, int]:
    with pdfplumber.open(str(pdf_path)) as pdf:
        pages = [(p.extract_text() or "") for p in pdf.pages]
    return "\n".join(pages), len(pages)


def _round_trip(items: list[tuple[str, str]], text: str) -> list[dict[str, Any]]:
    """Find each (label, wanted) in `text`, in order. Returns the failures."""
    squashed = _squash(text)
    cursor = 0
    failures: list[dict[str, Any]] = []
    for label, wanted in items:
        want = _squash(wanted)
        if not want:
            continue
        exact = squashed.find(want, cursor)  # the earliest exact hit wins over fuzzy ties
        if exact >= 0:
            cursor = exact + len(want)
            continue
        hit = fuzz.partial_ratio_alignment(want, squashed[cursor:], score_cutoff=FUZZ_MIN)
        if hit is not None:
            cursor += hit.dest_end
            continue
        anywhere = fuzz.partial_ratio(want, squashed, score_cutoff=FUZZ_MIN)
        reason = "out of order" if anywhere else "missing"
        failures.append({"item": label, "text": str(wanted)[:80], "reason": reason})
    return failures


def _resume_items(source: dict[str, Any]) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for key in source.get("order") or DEFAULT_ORDER:
        if key == "summary" and source.get("summary"):
            items.append(("summary", source["summary"].get("text", "")))
        elif key in ("experience", "projects"):
            for e in source.get(key) or []:
                eid = e.get("id")
                if key == "experience":
                    items += [(f"{key}/{eid}/title", e.get("title", "")),
                              (f"{key}/{eid}/company", e.get("company", ""))]
                else:
                    items.append((f"{key}/{eid}/name", e.get("name", "")))
                if e.get("dates"):
                    items.append((f"{key}/{eid}/dates", str(e["dates"])))
                texts = {p: b.get("text", "") for p, b in iter_bullets({key: [e]})}
                items += list(texts.items())
        elif key == "education":
            for e in source.get("education") or []:
                eid = e.get("id")
                items += [(f"education/{eid}/school", e.get("school", "")),
                          (f"education/{eid}/dates", str(e.get("dates", ""))),
                          (f"education/{eid}/degree", e.get("degree", ""))]
    return items


def _letter_items(source: dict[str, Any]) -> list[tuple[str, str]]:
    items = []
    for i, para in enumerate(source.get("paragraphs") or []):
        text = para.get("text", "") if isinstance(para, dict) else str(para)
        items.append((f"paragraph {i + 1}", text))
    return items


def parse_check(pdf_path: Path, source: dict[str, Any], contact: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run every check; `ok` is true when no critical check failed.

    `source["kind"]` is "resume" (the resume dict plus kind) or "letter" (the cover-letter dict plus kind).
    """
    kind = source.get("kind", "resume")
    checks: list[dict[str, Any]] = []
    try:
        text, pages = _read(Path(pdf_path))
    except Exception as e:  # unreadable PDF
        return {"ok": False, "checks": [_check("text_extracts", False, f"cannot read PDF: {e}")]}

    checks.append(_check("text_extracts", len(text.strip()) > 0, f"{len(text.strip())} characters"))
    bad_glyphs = len(_PUA.findall(text)) + text.count("(cid:")
    checks.append(_check("no_garbled_glyphs", bad_glyphs == 0,
                         f"{bad_glyphs} private-use or (cid:) glyphs" if bad_glyphs else ""))
    checks.append(_check("one_page", pages == 1, f"{pages} pages",
                         severity="critical" if kind == "resume" else "warning"))

    if contact:
        squashed = _squash(text)
        digits = re.sub(r"\D", "", text)
        email = str(contact.get("email") or "").strip()
        if email:
            found = _squash(email) in squashed
            checks.append(_check("contact_email", found, "" if found else "email not found"))
        phone = re.sub(r"\D", "", str(contact.get("phone") or ""))
        if phone:
            checks.append(_check("contact_phone", phone in digits, "" if phone in digits else "phone not found"))
        m = _CITY.search(str(contact.get("location") or ""))
        if m:
            found = _squash(m.group(0)) in squashed
            checks.append(_check("contact_city", found, "" if found else f"{m.group(0)!r} not found"))

    if kind == "resume":
        order = [k for k in (source.get("order") or DEFAULT_ORDER) if source.get(k)]
        lines = [ln.strip().lower() for ln in text.splitlines()]
        positions: dict[str, int] = {}
        missing = []
        for key in order:
            title = SECTION_TITLES[key].lower()
            idx = next((i for i, ln in enumerate(lines) if ln == title), None)
            if idx is None:
                missing.append(SECTION_TITLES[key].upper())
            else:
                positions[key] = idx
        checks.append(_check("headings", not missing,
                             f"missing on their own line: {', '.join(missing)}" if missing else ""))
        found_pos = [positions[k] for k in order if k in positions]
        in_order = found_pos == sorted(found_pos)
        checks.append(_check("reading_order", in_order, "" if in_order else "headings appear out of source order"))
        items = _resume_items(source)
    else:
        items = _letter_items(source)

    failures = _round_trip(items, text)
    detail = "; ".join(f"{f['item']} ({f['reason']})" for f in failures)
    checks.append(_check("round_trip", not failures, detail))
    result: dict[str, Any] = {
        "ok": all(c["ok"] or c["severity"] != "critical" for c in checks),
        "checks": checks,
    }
    if failures:
        result["round_trip_failures"] = failures
    return result

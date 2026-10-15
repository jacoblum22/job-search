"""Export lettered resume markdown to .docx (no cover-letter header).

Mimics the hand-built Word layout: section rules, dated entry lines with
right-aligned dates, bold skill categories, hyperlinked contact line.

Usage:
  .venv\\Scripts\\python scripts/md_resume_to_docx.py resumes/Jacob Andersen-Lum Resume A.md
  .venv\\Scripts\\python scripts/md_resume_to_docx.py resumes/Jacob Andersen-Lum Resume A.md -o out/test.docx

Requires: python-docx
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

from docx import Document
from docx.enum.text import (
    WD_ALIGN_PARAGRAPH,
    WD_LINE_SPACING,
    WD_TAB_ALIGNMENT,
    WD_UNDERLINE,
)
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.shared import Inches, Pt

FONT_NAME = "Calibri"
BODY = Pt(11)
HEADER = Pt(11)
# Contact line (email / phone / LinkedIn / GitHub) — hyperlinks use the same size.
CONTACT = Pt(8)
# Slightly smaller than HEADER so the long degree line fits on one row (saves a header line).
DEGREE_LINE = Pt(10.5)
NAME = Pt(16)
# US Letter — use explicit width so tab stops match the body column.
PAGE_WIDTH = Inches(8.5)
# Narrower than 1" sides: widens the rule / text block so dates and long lines match your Word original.
SIDE_MARGIN = Inches(0.6)
# Room above the name so the header is not flush to the page edge.
TOP_MARGIN = Inches(0.85)
BOTTOM_MARGIN = Inches(0.5)
# Vertical gap before each section heading (~one blank line after the first).
SECTION_SPACE_BEFORE_FIRST = Pt(8)
SECTION_SPACE_BEFORE_REST = Pt(14)
SECTION_HEADERS = frozenset(
    {
        "Profile",
        "Technical Skills",
        "Technical Projects",
        "Research Experience",
        "Education & Certifications",
        "Education",
        "Work and Leadership Experience",
        "Professional Experience",
    }
)

def _load_project_title_links() -> tuple[tuple[str, str], ...]:
    """Load (prefix, url) pairs from ``resume-project-links.yaml`` next to this script.

    Sorted by prefix length descending so longer titles win (e.g. LLM-Based… before Firmament).
    """
    path = Path(__file__).resolve().parent / "resume-project-links.yaml"
    if not path.is_file():
        return ()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError):
        return ()
    rows: list[tuple[str, str]] = []
    for item in data.get("projects", []):
        if not isinstance(item, dict):
            continue
        prefix = str(item.get("prefix", "")).strip()
        url = str(item.get("url", "")).strip()
        if prefix and url:
            rows.append((prefix, url))
    rows.sort(key=lambda x: len(x[0]), reverse=True)
    return tuple(rows)


PROJECT_TITLE_TO_REPO_URL: tuple[tuple[str, str], ...] = _load_project_title_links()


def _font(run, *, size=BODY, bold=False, underline=False, color=None) -> None:
    run.font.name = FONT_NAME
    run.font.size = size
    run.font.bold = bold
    run.font.underline = WD_UNDERLINE.SINGLE if underline else WD_UNDERLINE.NONE
    if color is not None:
        run.font.color.rgb = color


def _tight_lines(p) -> None:
    """Single-tight line spacing to save vertical space vs default 1.08."""
    p.paragraph_format.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    p.paragraph_format.line_spacing = 1.0


def _set_paragraph_bottom_border(paragraph, *, sz_eighths: str = "8") -> None:
    """Thin full-width rule under the paragraph (like Word section headings)."""
    p_pr = paragraph._element.get_or_add_pPr()
    # Remove existing pBdr if present
    for child in list(p_pr):
        if child.tag == qn("w:pBdr"):
            p_pr.remove(child)
            break
    p_bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), sz_eighths)
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "000000")
    p_bdr.append(bottom)
    p_pr.append(p_bdr)


def _add_hyperlink(
    paragraph,
    url: str,
    text: str,
    *,
    size=HEADER,
    bold: bool = False,
) -> None:
    """Insert a real Word hyperlink (external relationship), not just blue text.

    Opens in browser / mail client when the .docx is used in Word or similar.
    """
    part = paragraph.part
    r_id = part.relate_to(url, RT.HYPERLINK, is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)

    new_run = OxmlElement("w:r")
    r_pr = OxmlElement("w:rPr")
    fonts = OxmlElement("w:rFonts")
    fonts.set(qn("w:ascii"), FONT_NAME)
    fonts.set(qn("w:hAnsi"), FONT_NAME)
    r_pr.append(fonts)
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), str(int(size.pt * 2)))
    r_pr.append(sz)
    sz_cs = OxmlElement("w:szCs")
    sz_cs.set(qn("w:val"), str(int(size.pt * 2)))
    r_pr.append(sz_cs)
    if bold:
        r_pr.append(OxmlElement("w:b"))
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "0563C1")
    r_pr.append(color)
    u = OxmlElement("w:u")
    u.set(qn("w:val"), "single")
    r_pr.append(u)

    new_run.append(r_pr)
    t = OxmlElement("w:t")
    t.set(qn("xml:space"), "preserve")
    t.text = text
    new_run.append(t)
    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)


def _add_contact_paragraph(doc: Document, line: str) -> None:
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(0)
    _tight_lines(p)
    parts = [x.strip() for x in line.split("|")]
    for k, seg in enumerate(parts):
        if k:
            s = p.add_run(" | ")
            _font(s, size=CONTACT)
        if "@" in seg:
            _add_hyperlink(p, "mailto:" + seg, seg, size=CONTACT)
        elif "linkedin.com" in seg.lower():
            url = seg if seg.lower().startswith("http") else "https://" + seg.lstrip("/")
            _add_hyperlink(p, url, seg, size=CONTACT)
        elif "github.com" in seg.lower():
            url = seg if seg.lower().startswith("http") else "https://" + seg.lstrip("/")
            _add_hyperlink(p, url, seg, size=CONTACT)
        else:
            r = p.add_run(seg)
            _font(r, size=CONTACT)


def _add_section_heading(doc: Document, text: str, *, space_before: Pt | None) -> None:
    p = doc.add_paragraph()
    if space_before is not None:
        p.paragraph_format.space_before = space_before
    # Breathing room between the rule and the section body.
    p.paragraph_format.space_after = Pt(4)
    _tight_lines(p)
    run = p.add_run(text)
    _font(run, bold=True)
    _set_paragraph_bottom_border(p)


def _add_body_para(doc: Document, text: str, *, space_after=Pt(2)) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = space_after
    _tight_lines(p)
    run = p.add_run(text)
    _font(run)


def _lookup_project_repo_url(left: str) -> str | None:
    """Return GitHub URL if `left` matches a known Technical Projects title prefix."""
    title_side = left.split("|", 1)[0].strip()
    best_url: str | None = None
    best_len = 0
    for prefix, url in PROJECT_TITLE_TO_REPO_URL:
        if title_side.startswith(prefix) and len(prefix) >= best_len:
            best_url = url
            best_len = len(prefix)
    return best_url


def _add_left_right_dated(
    doc: Document,
    left: str,
    right: str,
    *,
    content_width,
    bold_left: bool = True,
    bold_right: bool = True,
    space_after=Pt(1),
    project_repo_url: str | None = None,
) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = space_after
    _tight_lines(p)
    p.paragraph_format.tab_stops.add_tab_stop(content_width, WD_TAB_ALIGNMENT.RIGHT)
    left = left.strip()
    if project_repo_url:
        if " | " in left:
            head, sep, tail = left.partition(" | ")
            _add_hyperlink(p, project_repo_url, head.strip(), size=BODY, bold=True)
            rest = p.add_run(sep + tail.strip())
            _font(rest, bold=True)
        else:
            _add_hyperlink(p, project_repo_url, left, size=BODY, bold=True)
    else:
        r_left = p.add_run(left)
        _font(r_left, bold=bold_left)
    p.add_run("\t")
    r_right = p.add_run(right.strip())
    _font(r_right, bold=bold_right)


def _add_skills_line(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(2)
    _tight_lines(p)
    segments = re.split(r"\s·\s", text)
    for j, part in enumerate(segments):
        if j:
            s = p.add_run(" · ")
            _font(s)
        part = part.strip()
        if ":" in part:
            label, _, rest = part.partition(":")
            b = p.add_run(label + ":")
            _font(b, bold=True)
            r = p.add_run(rest)
            _font(r)
        else:
            r = p.add_run(part)
            _font(r)


def _add_education_block_line(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(1)
    _tight_lines(p)
    m = re.search(r"(cGPA\s+[\d.]+%)", text)
    if m:
        r0 = p.add_run(text[: m.start()])
        _font(r0)
        r1 = p.add_run(m.group(1))
        _font(r1, bold=True)
        r2 = p.add_run(text[m.end() :])
        _font(r2)
    else:
        r = p.add_run(text)
        _font(r)


def _try_split_education_header_line(text: str) -> tuple[str, str, str] | None:
    """Parse 'Uni | City | Sep 2022 – May 2026 · BSc Major … · cGPA x%' into (left, right, subline).

    Matches the Word layout: bold left (school | city), bold right (dates · degree abbr),
    then a normal line with bold cGPA for major + GPA.
    """
    if text.count("|") < 2:
        return None
    parts = [p.strip() for p in text.split("|")]
    left = f"{parts[0]} | {parts[1]}"
    rest = parts[2].strip()
    segs = [s.strip() for s in re.split(r"\s·\s", rest)]
    if len(segs) < 3:
        return None
    date_seg = segs[0]
    if not re.search(r"\d{4}", date_seg):
        return None
    deg_seg = segs[1]
    m = re.match(
        r"^(BSc|B\.Sc\.|BA|B\.A\.|BEng|B\.Eng\.|MSc|M\.Sc\.|MA|PhD)\s+(.+)$",
        deg_seg,
        re.I,
    )
    if not m:
        return None
    abbr = m.group(1)
    remainder = m.group(2).strip()
    cgpa_seg = segs[-1]
    if not cgpa_seg.lower().startswith("cgpa"):
        return None
    right = f"{date_seg} · {abbr}"
    degree_line = f"{remainder} · {cgpa_seg}"
    return (left, right, degree_line)


def _add_education_degree_subline(doc: Document, text: str) -> None:
    """Major line under the education header row; only cGPA is bold."""
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(1)
    _tight_lines(p)
    m = re.search(r"(cGPA\s+[\d.]+%)", text)
    if m:
        r0 = p.add_run(text[: m.start()])
        _font(r0)
        r1 = p.add_run(m.group(1))
        _font(r1, bold=True)
        r2 = p.add_run(text[m.end() :])
        _font(r2)
    else:
        r = p.add_run(text)
        _font(r)


def _add_coursework_only_line(doc: Document, text: str) -> None:
    """Single line starting with Coursework: (no Certifications on same line)."""
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(2)
    _tight_lines(p)
    t = text.strip()
    if t.startswith("Coursework:"):
        lab = p.add_run("Coursework:")
        _font(lab, bold=True)
        rest = t[len("Coursework:") :].strip()
        r = p.add_run((" " + rest) if rest else "")
        _font(r)
    else:
        r = p.add_run(t)
        _font(r)


def _add_certifications_only_line(doc: Document, text: str) -> None:
    """Certifications on its own line — paragraph body, not a list bullet."""
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(2)
    _tight_lines(p)
    t = text.strip()
    if t.startswith("Certifications:"):
        lab = p.add_run("Certifications:")
        _font(lab, bold=True)
        value = t[len("Certifications:") :].strip()
        rest = p.add_run((" " + value) if value else "")
        _font(rest)
    else:
        r = p.add_run(t)
        _font(r)


def _add_coursework_certifications_line(doc: Document, text: str) -> None:
    """Split combined coursework/certifications onto two visual lines.

    Some source resumes keep both on one markdown line using
    ``Coursework: ... · Certifications: ...``. In the rendered DOCX we always
    force a newline before ``Certifications:`` to match the expected layout.
    """
    if " · Certifications:" in text:
        left, _, right = text.partition(" · Certifications:")
        left = left.strip()   # Coursework side
        right = right.strip()  # Certifications side
        _add_coursework_only_line(doc, left)
        _add_certifications_only_line(
            doc,
            f"Certifications: {right}" if right else "Certifications:",
        )
    else:
        _add_coursework_only_line(doc, text)


def _add_bullet(doc: Document, text: str) -> None:
    text = re.sub(r"^[•\u2022]\s*", "", text.strip())
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(0)
    _tight_lines(p)
    p.paragraph_format.left_indent = Inches(0.2)
    run = p.add_run(text)
    _font(run)


def resume_md_to_docx(md_path: Path, out_path: Path | None = None) -> Path:
    raw = md_path.read_text(encoding="utf-8")
    if "\n---\n" in raw:
        raw = raw.split("\n---\n", 1)[0]
    if re.search(r"\n## Application note\b", raw):
        raw = re.split(r"\n## Application note\b", raw, 1)[0]

    lines = [ln.rstrip() for ln in raw.splitlines()]
    doc = Document()
    for section in doc.sections:
        section.page_width = PAGE_WIDTH
        section.page_height = Inches(11)
        section.left_margin = SIDE_MARGIN
        section.right_margin = SIDE_MARGIN
        section.top_margin = TOP_MARGIN
        section.bottom_margin = BOTTOM_MARGIN
    sec0 = doc.sections[0]
    content_width = sec0.page_width - sec0.left_margin - sec0.right_margin

    i = 0
    n = len(lines)
    current_section: str | None = None
    first_body_section = True

    def is_blank(idx: int) -> bool:
        return idx >= n or lines[idx].strip() == ""

    while i < n and is_blank(i):
        i += 1

    # Header: name, degree, contact
    if i < n:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(0)
        _tight_lines(p)
        run = p.add_run(lines[i].strip())
        _font(run, size=NAME, bold=True)
        i += 1
    while i < n and not is_blank(i):
        t = lines[i].strip()
        if "@" in t and "|" in t:
            _add_contact_paragraph(doc, t)
        else:
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_after = Pt(0)
            _tight_lines(p)
            run = p.add_run(t)
            _font(run, size=DEGREE_LINE)
        i += 1
    if i < n and is_blank(i):
        i += 1
    # Minimal spacer; real “newline before section” is space_before on headings.
    spacer = doc.add_paragraph()
    spacer.paragraph_format.space_after = Pt(0)
    _tight_lines(spacer)

    while i < n:
        while i < n and is_blank(i):
            i += 1
        if i >= n:
            break
        stripped = lines[i].strip()

        if stripped in SECTION_HEADERS:
            sb = SECTION_SPACE_BEFORE_FIRST if first_body_section else SECTION_SPACE_BEFORE_REST
            _add_section_heading(doc, stripped, space_before=sb)
            first_body_section = False
            current_section = stripped
            i += 1
            continue

        if current_section == "Profile":
            _add_body_para(doc, stripped, space_after=Pt(3))
            current_section = None
            i += 1
            continue

        if current_section == "Technical Skills":
            _add_skills_line(doc, stripped)
            current_section = None
            i += 1
            continue

        if current_section == "Education & Certifications":
            if " · Certifications:" in stripped:
                _add_coursework_certifications_line(doc, stripped)
                current_section = None
            elif stripped.startswith("Certifications:"):
                _add_certifications_only_line(doc, stripped)
                current_section = None
            elif stripped.startswith("Coursework:"):
                _add_coursework_only_line(doc, stripped)
            else:
                parsed = _try_split_education_header_line(stripped)
                if parsed:
                    el, er, sub = parsed
                    _add_left_right_dated(
                        doc,
                        el,
                        er,
                        content_width=content_width,
                        bold_left=True,
                        bold_right=True,
                    )
                    _add_education_degree_subline(doc, sub)
                else:
                    _add_education_block_line(doc, stripped)
            i += 1
            continue

        if current_section in (
            "Technical Projects",
            "Research Experience",
            "Work and Leadership Experience",
            "Professional Experience",
        ):
            if "\t" in stripped and not (stripped.startswith("•") or stripped.startswith("\u2022")):
                left, _, right = stripped.partition("\t")
                proj_url = (
                    _lookup_project_repo_url(left)
                    if current_section == "Technical Projects"
                    else None
                )
                _add_left_right_dated(
                    doc,
                    left,
                    right,
                    content_width=content_width,
                    project_repo_url=proj_url,
                )
            elif stripped.startswith("•") or stripped.startswith("\u2022"):
                _add_bullet(doc, stripped)
            else:
                _add_body_para(doc, stripped)
            i += 1
            continue

        if "\t" in stripped and not (stripped.startswith("•") or stripped.startswith("\u2022")):
            left, _, right = stripped.partition("\t")
            _add_left_right_dated(doc, left, right, content_width=content_width)
            i += 1
            continue

        if stripped.startswith("•") or stripped.startswith("\u2022"):
            _add_bullet(doc, stripped)
            i += 1
            continue

        _add_body_para(doc, stripped)
        i += 1

    if out_path is None:
        out_path = md_path.with_name(md_path.stem + " - from md.docx")
    doc.save(str(out_path))
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Convert resume .md to .docx")
    ap.add_argument("md_path", type=Path)
    ap.add_argument("-o", "--output", type=Path, default=None)
    args = ap.parse_args()
    md_path = args.md_path.resolve()
    if not md_path.exists():
        print(f"Not found: {md_path}", file=sys.stderr)
        sys.exit(1)
    out = resume_md_to_docx(md_path, args.output.resolve() if args.output else None)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()

"""Export markdown cover letters to Word (.docx) and PDF formats.

Converts cover letter markdown files into professionally formatted Word
documents and (on Windows) converts those to PDF via Word COM automation.

Incremental by default: only rebuilds when the markdown is newer than
its docx/pdf siblings.

Usage:
    uv run python scripts/export.py                        # incremental: only modified
    uv run python scripts/export.py --force                # rebuild all
    uv run python scripts/export.py path/to/letter.md   # convert specific file(s)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import yaml
from docx import Document
from docx.shared import Pt, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

FONT_NAME = "Calibri"
FONT_SIZE_BODY = Pt(11)
FONT_SIZE_HEADER = Pt(10)
LINE_SPACING = 1.15

CONTACT_PATH = Path(__file__).resolve().parent.parent / "config" / "contact.yaml"


def _load_contact() -> dict[str, str]:
    """Load personal contact details from the git-ignored ``config/contact.yaml``.

    Copy ``config/contact.example.yaml`` to ``config/contact.yaml`` and fill it in.
    """
    if not CONTACT_PATH.exists():
        sys.exit(
            f"Missing {CONTACT_PATH}. Copy config/contact.example.yaml to "
            "config/contact.yaml and fill in your details."
        )
    data = yaml.safe_load(CONTACT_PATH.read_text(encoding="utf-8")) or {}
    keys = ("name", "email", "phone", "linkedin", "github")
    return {k: str(data.get(k) or "") for k in keys}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_run_font(run, *, size=FONT_SIZE_BODY, bold=False):  # noqa: ANN001
    """Apply consistent font styling to a Word document run.

    Args:
        run: A ``docx.text.run.Run`` object to style.
        size: Font size (default: body size).
        bold: Whether text should be bold.
    """
    run.font.name = FONT_NAME
    run.font.size = size
    run.font.bold = bold


def _add_header(doc: Document):
    """Add contact info header (name centred, details below)."""
    contact = _load_contact()
    # Name
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.space_before = Pt(0)
    run = p.add_run(contact["name"])
    _set_run_font(run, size=Pt(14), bold=True)

    # Contact line
    contact_line = " | ".join(
        [
            v
            for v in (
                contact["email"],
                contact["phone"],
                contact["linkedin"],
                contact["github"],
            )
            if v
        ]
    )
    p2 = doc.add_paragraph()
    p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p2.paragraph_format.space_after = Pt(12)
    p2.paragraph_format.space_before = Pt(0)
    run2 = p2.add_run(contact_line)
    _set_run_font(run2, size=FONT_SIZE_HEADER)


def _add_body(doc: Document, text: str):
    """Add the letter body paragraphs."""
    paragraphs = [p.strip() for p in text.strip().split("\n\n") if p.strip()]

    for para_text in paragraphs:
        # Handle "Best regards,\nJacob Andersen-Lum" as two lines
        lines = para_text.split("\n")
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.line_spacing = LINE_SPACING

        for i, line in enumerate(lines):
            if i > 0:
                p.add_run("\n")
            run = p.add_run(line)
            _set_run_font(run)


COVER_LETTER_OUTPUT_PREFIX = "Jacob Andersen-Lum Cover Letter"


def build_cover_letter_document(text: str) -> Document:
    """Return a formatted cover letter Document (margins + contact header + body).

    Markdown should separate paragraphs with a blank line; see ``_add_body``.
    """
    text = text.strip()
    doc = Document()
    for section in doc.sections:
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(1.0)
        section.right_margin = Inches(1.0)
    _add_header(doc)
    _add_body(doc, text)
    return doc


def slug_from_cover_letter_md_path(md_path: Path) -> str:
    """Infer slug from ``Jacob Andersen-Lum Cover Letter - <slug>.md``; else stem."""
    stem = md_path.stem
    prefixed = COVER_LETTER_OUTPUT_PREFIX + " - "
    if stem.startswith(prefixed):
        s = stem[len(prefixed) :].strip()
        return s if s else stem
    return stem


def md_to_docx(md_path: Path, out_dir: Path | None = None) -> Path:
    """Convert a single markdown cover letter to a .docx file."""
    raw = md_path.read_text(encoding="utf-8")
    if "\n---\n" in raw:
        raw = raw.split("\n---\n", 1)[0]
    doc = build_cover_letter_document(raw)

    # Output path
    if out_dir is None:
        out_dir = md_path.parent
    out_path = out_dir / md_path.with_suffix(".docx").name
    doc.save(str(out_path))
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _convert_pdfs_via_com(pairs: list[tuple[str, str]]):
    """Convert docx→pdf using a single persistent Word COM instance.

    Much faster than docx2pdf's default (which opens/closes Word per file).
    """
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    word = win32com.client.Dispatch("Word.Application")
    word.Visible = False
    word.DisplayAlerts = False

    try:
        for docx_path, pdf_path in pairs:
            doc = word.Documents.Open(docx_path)
            doc.SaveAs(pdf_path, FileFormat=17)  # 17 = wdFormatPDF
            doc.Close(0)
            # Avoid Unicode checks on narrow Windows consoles (cp1252).
            print(f"  OK {Path(pdf_path).name}")
    finally:
        word.Quit()
        pythoncom.CoUninitialize()


def _needs_rebuild(md_path: Path) -> bool:
    """Check if the markdown file is newer than its docx or pdf siblings.

    Returns True if either output is missing or the markdown was modified
    after the most recent output file.
    """
    docx_path = md_path.with_suffix(".docx")
    pdf_path = md_path.with_suffix(".pdf")
    md_mtime = md_path.stat().st_mtime

    if not docx_path.exists() or not pdf_path.exists():
        return True
    return md_mtime > min(docx_path.stat().st_mtime, pdf_path.stat().st_mtime)


def main():
    """CLI entry point: convert cover letters from markdown to DOCX and PDF.

    Batch mode is legacy (old cover_letters/*/*.md tree). Prefer editing Word
    under cover_letters/ and resumes/ (see README.txt files there).

    Usage:
        uv run python scripts/export.py                 # no-op message unless legacy paths exist
        uv run python scripts/export.py --force         # rebuild all discovered .md
        uv run python scripts/export.py path/to/file.md # specific file(s)
    """
    project_root = Path(__file__).resolve().parent.parent
    cover_dir = project_root / "cover_letters"

    force = "--force" in sys.argv
    explicit_files = [Path(a) for a in sys.argv[1:] if a != "--force"]

    # Collect markdown files to process
    if explicit_files:
        md_files = explicit_files
    else:
        # Legacy batch: cover_letters/<job-name>/*.md (tree removed; kept for one-off recovery)
        md_files = sorted(cover_dir.glob("*/*.md"))

    if not md_files:
        print(
            "No markdown cover letters found. Maintain Word originals under "
            "cover_letters/ and resumes/ (see README.txt). "
            "To convert a single .md file: uv run python scripts/export.py path/to/file.md"
        )
        return

    # Filter to only those needing rebuild (unless --force)
    if force:
        to_build = md_files
    else:
        to_build = [f for f in md_files if _needs_rebuild(f)]

    skipped = len(md_files) - len(to_build)
    if skipped:
        print(f"Skipping {skipped} up-to-date cover letter(s)")

    if not to_build:
        print("All cover letters are up to date.")
        return

    # Generate DOCX files (output in same folder as markdown)
    docx_paths = []
    for md_file in to_build:
        out = md_to_docx(md_file, out_dir=md_file.parent)
        docx_paths.append(out)
        print(f"  OK {md_file.parent.name}/{out.name}")

    print(f"\nConverted {len(to_build)} cover letter(s) to .docx")

    # PDF conversion — single persistent Word instance
    try:
        pairs = [
            (str(dp.resolve()), str(dp.with_suffix(".pdf").resolve()))
            for dp in docx_paths
        ]

        print(f"\nGenerating {len(pairs)} PDFs...")
        t0 = time.perf_counter()
        _convert_pdfs_via_com(pairs)
        elapsed = time.perf_counter() - t0
        print(f"Generated {len(pairs)} PDF(s) in {elapsed:.1f}s")
    except ImportError:
        print("\nSkipping PDF generation (requires pywin32 on Windows)")
    except Exception as e:
        print(f"\nPDF generation failed: {e}")


if __name__ == "__main__":
    main()

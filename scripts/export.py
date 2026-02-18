"""Export markdown cover letters to Word (.docx) and PDF formats.

Converts cover letter markdown files into professionally formatted Word
documents and (on Windows) converts those to PDF via Word COM automation.

Usage:
    uv run python scripts/export.py                        # convert all .md in cover_letters/
    uv run python scripts/export.py cover_letters/foo.md   # convert specific file(s)
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

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

CONTACT = {
    "name": "Jake Andersen-Lum",
    "email": "jacobdavidandersenlum@gmail.com",
    "phone": "778-636-0194",
    "linkedin": "linkedin.com/in/jacob-andersen-lum",
    "github": "github.com/jacoblum22",
}


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
    # Name
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.space_before = Pt(0)
    run = p.add_run(CONTACT["name"])
    _set_run_font(run, size=Pt(14), bold=True)

    # Contact line
    contact_line = " | ".join(
        [
            CONTACT["email"],
            CONTACT["phone"],
            CONTACT["linkedin"],
            CONTACT["github"],
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
        # Handle "Best regards,\nJake Andersen-Lum" as two lines
        lines = para_text.split("\n")
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.line_spacing = LINE_SPACING

        for i, line in enumerate(lines):
            if i > 0:
                p.add_run("\n")
            run = p.add_run(line)
            _set_run_font(run)


def md_to_docx(md_path: Path, out_dir: Path | None = None) -> Path:
    """Convert a single markdown cover letter to a .docx file."""
    text = md_path.read_text(encoding="utf-8").strip()

    doc = Document()

    # Set narrow margins
    for section in doc.sections:
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(1.0)
        section.right_margin = Inches(1.0)

    _add_header(doc)
    _add_body(doc, text)

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
            print(f"  ✓ {Path(pdf_path).name}")
    finally:
        word.Quit()
        pythoncom.CoUninitialize()


def main():
    """CLI entry point: convert all (or specified) markdown cover letters to DOCX and PDF."""
    project_root = Path(__file__).resolve().parent.parent
    cover_dir = project_root / "cover_letters"
    md_dir = cover_dir / "markdown"
    docx_dir = cover_dir / "docx"
    pdf_dir = cover_dir / "pdf"
    docx_dir.mkdir(exist_ok=True)
    pdf_dir.mkdir(exist_ok=True)

    if len(sys.argv) > 1:
        files = [Path(a) for a in sys.argv[1:]]
    else:
        files = sorted(md_dir.glob("*.md"))

    if not files:
        print("No markdown files found in cover_letters/markdown/")
        return

    docx_paths = []
    for md_file in files:
        out = md_to_docx(md_file, out_dir=docx_dir)
        docx_paths.append(out)
        print(f"  ✓ {out.name}")

    print(f"\nConverted {len(files)} cover letter(s) to .docx")

    # PDF conversion — single persistent Word instance (no startup cost per file)
    try:
        pairs = [
            (str(dp.resolve()), str((pdf_dir / dp.with_suffix(".pdf").name).resolve()))
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

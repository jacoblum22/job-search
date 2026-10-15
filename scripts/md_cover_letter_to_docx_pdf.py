"""Cover letter Markdown -> Word + PDF with standard output names.

Produces (in the markdown's directory unless ``-o`` is set):

  Jacob Andersen-Lum Cover Letter - <slug>.docx
  Jacob Andersen-Lum Cover Letter - <slug>.pdf

Uses the same layout as ``scripts/export.py`` (contact header + body). Slug is
taken from ``--slug``, or inferred from filenames like
``Jacob Andersen-Lum Cover Letter - Demonware.md`` -> ``Demonware``.
Otherwise slug defaults to the ``.md`` stem (may look odd; prefer ``--slug``).

Body paragraphs must be separated by **blank lines** (``\\n\\n``), per
``export._add_body``. Text after a ``\\n---\\n`` marker is dropped (template
tail), matching the resume exporter.

Usage:
  python scripts/md_cover_letter_to_docx_pdf.py \\
    \"cover_letters/Jacob Andersen-Lum Cover Letter - Diligent.md\"
  python scripts/md_cover_letter_to_docx_pdf.py notes.md -s Acme -o cover_letters
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow `python scripts/...` from repo root
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from export import (  # noqa: E402
    COVER_LETTER_OUTPUT_PREFIX,
    _convert_pdfs_via_com,
    build_cover_letter_document,
    slug_from_cover_letter_md_path,
)


def _read_letter_body(md_path: Path) -> str:
    raw = md_path.read_text(encoding="utf-8")
    if "\n---\n" in raw:
        raw = raw.split("\n---\n", 1)[0]
    return raw.strip()


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Export cover letter .md to Jacob Andersen-Lum Cover Letter - <slug>.docx/.pdf"
    )
    ap.add_argument("md_path", type=Path, help="Source markdown file")
    ap.add_argument(
        "-s",
        "--slug",
        type=str,
        default=None,
        help="Short label for output filenames (default: parsed from filename or stem)",
    )
    ap.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for .docx and .pdf (default: same folder as .md)",
    )
    args = ap.parse_args()

    md_path = args.md_path.resolve()
    if not md_path.is_file():
        print(f"Not found: {md_path}", file=sys.stderr)
        sys.exit(1)

    slug = (args.slug or "").strip() or slug_from_cover_letter_md_path(md_path)
    out_dir = (args.output_dir or md_path.parent).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    base = f"{COVER_LETTER_OUTPUT_PREFIX} - {slug}"
    docx_path = out_dir / f"{base}.docx"
    pdf_path = out_dir / f"{base}.pdf"

    doc = build_cover_letter_document(_read_letter_body(md_path))
    doc.save(str(docx_path))
    print(f"Wrote {docx_path}")

    try:
        _convert_pdfs_via_com(
            [(str(docx_path.resolve()), str(pdf_path.resolve()))]
        )
        print(f"Wrote {pdf_path}")
    except ImportError:
        print(
            "Skipped PDF (install pywin32 on Windows for Word COM export).",
            file=sys.stderr,
        )
        sys.exit(0 if docx_path.is_file() else 1)
    except OSError as e:
        print(f"PDF generation failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

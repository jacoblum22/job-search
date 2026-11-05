"""Render structured base resumes (YAML) to .docx and .pdf.

Usage:
  .venv\\Scripts\\python scripts/render_resume.py materials/resumes/bases/data-scientist.yaml
  .venv\\Scripts\\python scripts/render_resume.py materials/resumes/bases/   # every *.yaml
  .venv\\Scripts\\python scripts/render_resume.py base.yaml -o out/ --no-pdf
  .venv\\Scripts\\python scripts/render_resume.py bases/ --strict --index materials/profile/experience-vault/vault-index.json

Contact details come from config/contact.yaml. Exits non-zero when a base
fails validation or its PDF runs past one page.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.resume import check_sources, iter_bullets, load_resume, render, validate  # noqa: E402


def _pdf_text_problems(pdf_path: Path, base_path: Path) -> list[str]:
    """With pdftotext installed, check every bullet survives text extraction."""
    if not shutil.which("pdftotext"):
        return []
    text = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"], capture_output=True, text=True, check=True
    ).stdout
    # Lines may wrap after a hyphen ("customer-" / "order"); rejoin those first.
    flat = " ".join(re.sub(r"(?<=\w-)\s*\n\s*", "", text).split())
    problems = []
    if "\uf0b7" in text:
        problems.append("PDF text contains U+F0B7 (Symbol-font bullet)")
    for path, bullet in iter_bullets(load_resume(base_path)):
        if " ".join(bullet["text"].split()) not in flat:
            problems.append(f"{path}: bullet text not found whole in the PDF")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", type=Path, help="base .yaml files or folders of them")
    ap.add_argument("-o", "--out", type=Path, default=None, help="output folder (default: next to the base)")
    ap.add_argument("--no-pdf", action="store_true")
    ap.add_argument("--strict", action="store_true", help="every bullet must cite source passage ids")
    ap.add_argument("--index", type=Path, default=None, help="vault-index.json: check cited passage ids exist")
    args = ap.parse_args()

    bases: list[Path] = []
    for p in args.paths:
        bases.extend(sorted(p.glob("*.yaml")) if p.is_dir() else [p])

    failed = False
    for base in bases:
        data = load_resume(base)
        problems = validate(data, require_sources=args.strict)
        if args.index:
            problems += check_sources(data, args.index)
        if problems:
            failed = True
            print(f"{base.name}: INVALID")
            for line in problems:
                print(f"  - {line}")
            continue
        result = render(base, args.out, pdf=not args.no_pdf)
        status = f"{base.name}: wrote {result['docx'].name}"
        if "pdf" in result:
            status += f", {result['pdf'].name} ({result['pages']} page{'s' if result['pages'] != 1 else ''})"
            extra = _pdf_text_problems(result["pdf"], base)
            if result["pages"] > 1:
                extra.insert(0, "runs past one page")
            if extra:
                failed = True
                status += "\n" + "\n".join(f"  - {line}" for line in extra)
        print(status)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

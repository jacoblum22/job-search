"""Passage index for the experience vault.

Every bullet, table row, header field and paragraph in the vault markdown is a
*passage* with a stable id like ``algaecal.sql-daily``. Tailored resumes and
cover letters cite these ids, so code can check every claim against the vault.

Ids live in the vault files themselves as Obsidian block ids (`` ^sql-daily`` at
the end of the line), so they survive edits to the text. The file's prefix comes
from an ``<!-- id: algaecal -->`` comment on its first line, falling back to the
file name. ``assign_ids`` adds missing ids; ``build_index`` reads them.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Not evidence: gap tracking is about skills Jake does NOT have.
EXCLUDED_FILES = {"skill-gaps.md"}
# Cross-reference files restate facts from the primary notes; prefer the primary passage.
CROSSREF_FILES = {"skills-map.md", "soft-skills.md"}
# Sections that hold no claims.
SKIP_SECTIONS = re.compile(r"^(related notes|tags|todo\b|architecture$|repository layout)", re.I)
# Facts for interviews only; never put them on a resume or cover letter.
INTERVIEW_ONLY = re.compile(r"not the resume|manager feedback|manager-confirmed|departure", re.I)
# Lines that tell the writer how to frame something rather than state a fact.
GUIDANCE_LABELS = {"resume framing", "status"}
GUIDANCE_TEXT = re.compile(r"\bdo not (claim|list)\b|never claim|not claimable", re.I)
AI_ASSISTED = re.compile(r"how it was built\**:?\**:?\s*ai-assisted", re.I)

PREFIX_COMMENT = re.compile(r"^<!--\s*id:\s*([a-z0-9-]+)\s*-->\s*$")
BLOCK_ID = re.compile(r"\s\^([a-z0-9-]+)\s*$")
TABLE_BLOCK_ID = re.compile(r"\s\^([a-z0-9-]+)\s*\|\s*$")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
BULLET = re.compile(r"^(\s*)[-*+]\s+(.*)$")
LABEL = re.compile(r"^\*\*([^*]+?):?\*\*:?\s*")
STAR_LABELS = {"situation", "task", "action", "result"}
COURSE = re.compile(r"^([A-Z]{3,4}) (\d{3})")
NUMBER = re.compile(r"(?<![\w.])\d(?:[\d,]*\d)?(?:\.\d+)?(?:[kKMx](?!\w))?\+?%?")
WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
STOPWORDS = set(
    "a an the and or of to in on for with from by at as is are was were be my i we our me "
    "it its this that than into via all every each per up out".split()
)
SECTION_ID_PREFIX = {
    "skills": "skill", "skills demonstrated": "skill", "what i learned": "learned",
    "tech stack": "stack", "metrics": "metric",
}


@dataclass
class Passage:
    id: str
    file: str
    line: int
    kind: str  # field | bullet | table | paragraph | heading
    section: list[str]
    text: str  # plain text, markdown removed
    markdown: str
    use: str = "claim"  # claim | interview-only | guidance
    source: str = "primary"  # primary | crossref
    ai_assisted: bool = False
    parent: str | None = None
    numbers: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)


@dataclass
class _Block:
    kind: str
    start: int  # 0-based line index of the first line
    end: int  # 0-based line index of the line that carries the id
    markdown: str
    local_id: str | None
    section: list[str]
    indent: int = 0


def plain(md: str) -> str:
    text = WIKILINK.sub(r"\1", md)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("**", "").replace("`", "")
    return re.sub(r"\s+", " ", text).strip()


def slugify(text: str, words: int = 3) -> str:
    tokens = re.findall(r"[a-z0-9]+", plain(text).lower().replace("'", "").replace("\u2019", ""))
    kept = [t for t in tokens if t not in STOPWORDS] or tokens
    return "-".join(kept[:words]) or "item"


def file_prefix(path: Path, lines: list[str]) -> str:
    if lines and (m := PREFIX_COMMENT.match(lines[0].strip())):
        return m.group(1)
    return path.stem


def _strip_id(line: str, table: bool) -> tuple[str, str | None]:
    pattern = TABLE_BLOCK_ID if table else BLOCK_ID
    m = pattern.search(line)
    if not m:
        return line, None
    rest = line[: m.start()] + (" |" if table else "")
    return rest, m.group(1)


def _blocks(lines: list[str]) -> list[_Block]:
    blocks: list[_Block] = []
    section: list[str] = []
    skipping = in_code = False
    table_header: int | None = None
    para: list[int] = []

    def flush_para() -> None:
        if not para:
            return
        text, local = _strip_id(lines[para[-1]], table=False)
        md = " ".join([lines[i].strip() for i in para[:-1]] + [text.strip()])
        blocks.append(_Block("paragraph", para[0], para[-1], md, local, list(section)))
        para.clear()

    for i, raw in enumerate(lines):
        line = raw.rstrip("\n")
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_para()
            in_code = not in_code
            continue
        if in_code:
            continue
        if m := HEADING.match(stripped):
            flush_para()
            level, (title, local) = len(m.group(1)), _strip_id(m.group(2).strip(), table=False)
            title = title.strip()
            section = section[: level - 2] + [title] if level > 1 else []
            skipping = any(SKIP_SECTIONS.match(s) for s in section)
            table_header = None
            if COURSE.match(title) and not skipping:  # course headings carry the grade
                blocks.append(_Block("heading", i, i, title, local, list(section)))
            continue
        if skipping or not stripped or stripped.startswith((">", "<!--", "---")):
            flush_para()
            if not stripped.startswith("|"):
                table_header = None
            continue
        if stripped.startswith("|"):
            flush_para()
            if table_header is None:
                table_header = i
                continue
            if re.fullmatch(r"\|[\s:|-]+\|?", stripped):
                continue
            text, local = _strip_id(stripped, table=True)
            header = [c.strip() for c in lines[table_header].strip().strip("|").split("|")]
            cells = [c.strip() for c in text.strip().strip("|").split("|")]
            parts = [f"{h}: {c}" if h else c for h, c in zip(header + [""] * len(cells), cells) if c]
            blocks.append(_Block("table", i, i, "; ".join(parts), local, list(section)))
            continue
        table_header = None
        if m := BULLET.match(line):
            flush_para()
            text, local = _strip_id(m.group(2), table=False)
            blocks.append(_Block("bullet", i, i, text.strip(), local, list(section), len(m.group(1))))
            continue
        if stripped.startswith("**") and LABEL.match(stripped):
            flush_para()  # header fields like **Role**: ... are one fact per line
            text, local = _strip_id(stripped, table=False)
            blocks.append(_Block("field", i, i, text.strip(), local, list(section)))
            continue
        para.append(i)
    flush_para()
    return blocks


def _auto_id(block: _Block) -> str:
    label_m = LABEL.match(block.markdown)
    label = label_m.group(1).strip() if label_m else ""
    heading = block.section[-1] if block.section else ""
    under_story = any(s.lower().startswith("stor") for s in block.section)
    if label.lower() in STAR_LABELS and under_story:
        story = re.sub(r"^story\s*\d*\s*:\s*", "", heading, flags=re.I)
        return f"{slugify(story, 2)}-{label.lower()}"
    if block.kind == "table":
        first = block.markdown.split(";")[0].split(":", 1)[-1]
        base = slugify(first)
    elif label and len(label.split()) <= 6:
        base = slugify(label)
    else:
        base = slugify(block.markdown)
    if block.kind == "heading" and (course := COURSE.match(block.markdown)):
        return f"{course.group(1).lower()}-{course.group(2)}"
    if course := COURSE.match(heading):
        return f"{course.group(1).lower()}-{course.group(2)}-{slugify(block.markdown, 2)}"
    prefix = SECTION_ID_PREFIX.get(heading.lower())
    if prefix and not under_story:
        return f"{prefix}-{'-'.join(base.split('-')[:2])}"
    return base


def assign_ids(path: Path) -> list[str]:
    """Add a prefix comment and a block id to every passage in ``path`` that lacks one."""
    raw = path.read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in raw else "\n"  # keep the file's own line endings
    lines = raw.splitlines()
    added: list[str] = []
    changed = not (lines and PREFIX_COMMENT.match(lines[0].strip()))
    if changed:
        lines.insert(0, f"<!-- id: {path.stem} -->")
    blocks = _blocks(lines)
    used = {b.local_id for b in blocks if b.local_id}
    for b in blocks:
        if b.local_id:
            continue
        base = _auto_id(b)[:60].strip("-")
        local, n = base, 2
        while local in used:
            local, n = f"{base}-{n}", n + 1
        used.add(local)
        line = lines[b.end].rstrip()
        if b.kind == "table":
            line = re.sub(r"\s*\|\s*$", f" ^{local} |", line)
        else:
            line = f"{line} ^{local}"
        lines[b.end] = line
        added.append(local)
    if added or changed:
        path.write_text(newline.join(lines) + newline, encoding="utf-8", newline="")
    return added


def vault_files(vault: Path) -> list[Path]:
    return sorted(
        p for p in vault.rglob("*.md")
        if p.name not in EXCLUDED_FILES and not p.name.startswith(("_", ".")) and "sources" not in p.relative_to(vault).parts
    )


def parse_file(path: Path, vault: Path) -> tuple[list[Passage], list[str]]:
    """Return the file's passages and a list of problems (missing ids)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    prefix = file_prefix(path, lines)
    rel = path.relative_to(vault).as_posix()
    ai = bool(AI_ASSISTED.search("\n".join(lines)))
    problems: list[str] = []
    passages: list[Passage] = []
    parents: list[tuple[int, str]] = []  # (indent, id) stack for nested bullets
    for b in _blocks(lines):
        if not b.local_id:
            problems.append(f"{rel}:{b.start + 1}: no id: {b.markdown[:60]}")
            continue
        pid = f"{prefix}.{b.local_id}"
        label_m = LABEL.match(b.markdown)
        label = label_m.group(1).strip().lower() if label_m else ""
        use = "claim"
        if any(INTERVIEW_ONLY.search(s) for s in b.section):
            use = "interview-only"
        elif label in GUIDANCE_LABELS or GUIDANCE_TEXT.search(b.markdown):
            use = "guidance"
        parent = None
        if b.kind == "bullet":
            while parents and parents[-1][0] >= b.indent:
                parents.pop()
            parent = parents[-1][1] if parents else None
            parents.append((b.indent, pid))
        else:
            parents.clear()
        text = plain(b.markdown)
        passages.append(Passage(
            id=pid, file=rel, line=b.start + 1, kind=b.kind, section=b.section, text=text,
            markdown=b.markdown, use=use, source="crossref" if path.name in CROSSREF_FILES else "primary",
            ai_assisted=ai, parent=parent, numbers=NUMBER.findall(text),
            links=sorted(set(WIKILINK.findall(b.markdown))),
        ))
    return passages, problems


def build_index(vault: Path) -> tuple[list[Passage], list[str]]:
    """Parse every vault file. Problems include missing and duplicate ids."""
    passages: list[Passage] = []
    problems: list[str] = []
    for path in vault_files(vault):
        got, issues = parse_file(path, vault)
        passages += got
        problems += issues
    seen: dict[str, Passage] = {}
    for p in passages:
        if p.id in seen:
            problems.append(f"duplicate id {p.id}: {seen[p.id].file}:{seen[p.id].line} and {p.file}:{p.line}")
        seen[p.id] = p
    return passages, problems


def to_json(passages: list[Passage]) -> list[dict]:
    return [asdict(p) for p in passages]

# Structured base resumes

Base resumes are YAML files in the git-ignored `materials/resumes/bases/`, one per role family
(Data Analyst / BI, Data Scientist, ML / Applied AI, Junior Software Developer). Every section,
entry and bullet has a stable id, so the tailoring pipeline can edit one bullet by its path and
check that it cites vault passages.

Render them with:

```
.venv\Scripts\python scripts/render_resume.py materials/resumes/bases/
```

This writes a `.docx` and `.pdf` next to each base (or into `-o <folder>`). It fails when a base
is malformed, runs past one page, or a bullet does not come back whole from the PDF's text
(checked with `pdftotext` when it is installed). `--strict` also fails any bullet with no
`sources`, and `--index <vault-index.json>` fails any cited passage id that is missing from the
vault index or marked interview-only or guidance. Contact details come from `config/contact.yaml`; add `location: "Vancouver, BC"` there.

## Schema

```yaml
id: data-scientist                 # lowercase letters, digits, '.', '-'
label: Data Scientist
file_stem: Jake Andersen-Lum Resume - Data Scientist   # output file name (optional)
order: [summary, skills, experience, projects, education]   # optional; this is the default
contact: {location: "Vancouver, BC"}   # optional overrides of config/contact.yaml
layout: {body_pt: 10.5}                # optional, see Layout in src/resume.py

summary: {id: summary, text: "...", sources: []}

skills:
  - {id: skills.languages, label: Languages, items: [SQL, Python]}

experience:
  - id: algaecal
    title: Associate Data Scientist     # title, company, dates are locked: tailoring never edits them
    company: AlgaeCal
    location: Vancouver, BC
    dates: Jun 2026 – Oct 2026
    bullets:
      - id: algaecal.sql-daily          # unique within the base
        text: "..."
        sources: [algaecal.sql-daily]   # vault passage ids backing the claim

projects:
  - id: the-game
    name: AI Dungeon Master
    context: Personal project           # shown in italics after the name
    dates: Sep 2026 – Present
    url: https://github.com/...         # the name becomes a link
    bullets: [...]

education:
  - id: ubc
    school: University of British Columbia
    location: Vancouver, BC
    dates: Sep 2022 – May 2026
    degree: BSc, ...
    lines:
      - {id: ubc.coursework, label: Coursework, text: "..."}
```

A bullet's path is `<section>/<entry id>/<bullet id>`, e.g. `experience/algaecal/algaecal.sql-daily`
(see `iter_bullets`). Bullets shared between bases keep the same id when their text is the same;
a reworded variant gets a suffix (`algaecal.churn.short`).

## Template

Chosen from the OpenResume parse check of the Oct 2026 resume:

- bullets are a literal U+2022 typed as text, not Word's list bullet (Symbol font, extracts as U+F0B7);
- "Vancouver, BC" leads the contact line;
- each entry line puts title, company and location in separate runs, with no pipes;
- one Experience section (work and research together), ALL CAPS headings, "Summary" not "Profile";
- one column, one page, Calibri.

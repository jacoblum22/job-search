# Third-party notices

The tailoring pipeline (`src/tailor/`, `prompts/tailor/`, `docs/`) adapts ideas and some wording from
the open-source projects and datasets below. Changes: prompts were rewritten for a diff-edit, vault-grounded
workflow; code is original unless stated.

## Adapted material

- **AI Job Hunter** by Saeed Kolivand, Apache License 2.0
  (github.com/saeedkolivand/ai-job-hunter-app). Adapted: the grounding, PRESENT/ABSENT, no-invented-metrics
  and repair-as-correction prompt rules; the cover-letter recipe; the banned-word lists and anti-AI-voice
  rules (`src/tailor/phrases.py`, `prompts/tailor/*.md`). Licence: https://www.apache.org/licenses/LICENSE-2.0
- **Resume-Matcher** by srbhr, Apache License 2.0 (github.com/srbhr/Resume-Matcher). Adapted: parts of
  the banned-phrase list and the refinement prompt rules.
- **ATS Resume Improver** by SimeonOnSecurity, MIT License. Adapted: parts of the banned-phrase list
  and keyword-handling rules.
- **ResumeFlow** by Saurabh Zinjad, MIT License. Adapted: structure ideas for the resume and letter
  generation steps.
- **O\*NET Technology Skills** (O\*NET Resource Center, U.S. Department of Labor, Employment and
  Training Administration), licensed under Creative Commons Attribution 4.0 International (CC BY 4.0).
  Used by `scripts/skills_crosscheck.py` to find tool names missing from the skills taxonomy. Any list
  derived from it carries this attribution: "This product includes information from the O*NET
  database by the U.S. Department of Labor, Employment and Training Administration (USDOL/ETA).
  Used under the CC BY 4.0 license. O*NET is a trademark of USDOL/ETA."

## Ideas only

**Reqcore**, **AIHawk** and **OpenResume** are AGPL-licensed. No code or text from them is used; they
informed design ideas only (for example the ATS parse check), and everything here is written independently.

## Not redistributed

The ESCO skills classification (European Commission) is read from a local file the user downloads;
it is not committed to this repository.

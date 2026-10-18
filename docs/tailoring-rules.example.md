# Tailoring rules (template)

Copy this file to `materials/docs/tailoring-rules.md` (git-ignored) and fill it in. The tailoring
prompts in `prompts/tailor/` and the code checks treat the filled-in file as binding. Keep personal
details (names, employers, contact details) in your copy only, never in this template.

## 1. Grounding

- Every claim in a resume or letter must be traceable to a passage in the experience vault. If it is
  not in the vault, it does not go in the document, even when the posting asks for it.
- Never claim a skill, tool, employer, project, credential or responsibility from a job posting
  alone. A missing skill may at most be named once in a letter as something I am "keen to grow into".
- Never write "familiar with X" for something the vault does not show.
- Company facts in a letter come only from the posting or from verified company notes.

## 2. No invented metrics

- No percentages, counts, team sizes, dollar amounts or timeframes unless the same number is in the
  cited vault passage.
- Do not round, convert, estimate or "improve" a number. If an achievement has no number, keep it
  qualitative.
- If a bullet needs a number I do not have, drop the number, not the bullet.

## 3. Format

- One page for the resume. Replace rather than append when space is tight.
- Cover letter: 3-5 short paragraphs, plain text, about 200-300 words.
- Job titles, employers, locations, dates, school, degree and contact details never change in a
  tailored document.
- Headline: the posting's title only when it is truthful for the work I have done.

## 4. Spelling and tone

- Spelling: <fill in, for example Canadian English: colour, centre, organization>.
- Plain words, concrete tools and scope, varied sentence length. No fake enthusiasm.
- Letter greeting: "Dear <name>," only when the posting names the hiring manager or a recruiter to
  contact; otherwise "Dear Hiring Manager,".
- Sign-off name: <fill in>.

## 5. Banned phrases and the protection rule

The full list lives in `src/tailor/phrases.py`. In short, avoid:

- Words: delve, leverage, robust, seamless, cutting-edge, tapestry, testament, realm, underscore,
  showcase, foster, intricate, pivotal, vibrant, garner, vital, crucial, harness, elevate, streamline,
  unlock, empower, multifaceted, ever-evolving, paradigm shift, spearheaded, utilize, synergy, holistic.
- Self-descriptions: passionate, results-driven, proven track record, team player, detail-oriented,
  meticulous, world-class, self-starter.
- Openers and closers: "I am writing to apply", "I am excited to apply", "As a passionate", "Thank you
  for your consideration".
- Patterns: em dashes, "not just X but Y", trailing ", showcasing ..." clauses, lists of three used
  for rhythm, a fake-profound last line.

**Protection rule:** a phrase on these lists is allowed when it is an exact term from the job posting
(and backed by the vault), or when it already appears in my own writing (the vault or my base
resumes). Matching the ATS keyword beats style.

Add your own banned phrases here: <fill in or delete>.

## 6. Employer-specific guardrails

One short section per employer where the vault needs extra care (for example: work was a co-op, work
was under NDA, a project name must not be shown, no metrics exist so none may appear, a title must
be written exactly as on the contract, dates). Delete this paragraph and list yours:

- <Employer A>: <what must or must not be said>
- <Employer B>: <what must or must not be said>

## 7. Things I never want in a document

- <fill in, for example: a specific claim I cannot back in an interview>
- <fill in>

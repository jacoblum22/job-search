---
name: "job-application-review"
description: "Review a resume and cover letter against a specific job posting: honest fit verdict, numbered fixes, exact replacement text, and follow-up rounds until it is ready to submit."
---

# Job application review

Use when the user gives a resume, a cover letter, and/or a job posting and wants feedback, rewrites, or a go/no-go on submitting. Be direct and push back substantively. Do not flatter. The goal is a stronger application that is still 100% true.

## Inputs
- Need: resume, cover letter (optional), job posting. If the posting is missing, ask for it once; do not review blind. Read every attachment from disk (pdftotext -layout for PDFs, python-docx for .docx) before commenting. Check page count.
- Read the posting FIRST. Extract: seniority and years asked, required vs preferred skills, named tools and systems (the first-named is usually the most important), the company's own vocabulary, and any note about AI/automated screening (if present, inconsistencies between documents matter more).

## Round 1: first review
Structure the reply like this:
1. **Verdict (2-4 sentences):** how well the materials match this posting, and the single biggest risk (for example a hard requirement the user lacks). Say if the role is a stretch and where their effort is better spent.
2. **Resume:** numbered, specific fixes, most important first. Quote the exact line, say what is wrong, say what to do.
3. **Cover letter:** same format.
4. **Patterns across documents** (only if you see real ones): generic or templated paragraphs, gaps named but not bridged, claims not supported in the body, fixes not carried between versions, summary claims that the bullets do not back up.
5. **Close with 1-2 questions that only the user can answer** (what they actually did, real numbers), then offer to draft.

What to look for:
- Summary and skills that use the posting's language, but only where it is true.
- Bullet order that follows the posting's priority order.
- Missing numbers (sources, counts, frequency, time saved). Any true number beats none.
- Details that are noise: grades on single courses, report marks, filler clauses, jargon a recruiter cannot parse, unsupported skills listed with no evidence.
- Overclaims: titles vs summary mismatch, "experience" claims the evidence does not carry, ownership verbs for work they only checked.
- Short tenure or gaps: do not suggest hiding dates. Suggest a short neutral spoken answer.
- Cover letter: opens with the role, uses concrete evidence, bridges each gap in the same sentence it names it, ends with a closing ask, no generic "I value meaningful work" paragraph, no company claims that cannot be verified.
- Skills a recruiter would expect for the role but that are absent (for example documentation, attribution, funnel metrics). Say what to add ONLY if the user can truthfully claim it.

## Rewrites
When asked what to change, give exact text: "Replace X with Y", section by section, in a copyable form. Use [brackets] for any number or fact only the user can supply, and tell them to delete the phrase rather than guess. Explain each change in one line. Never invent employers, tools, metrics, or outcomes; ask.

## Later rounds (user sends a revised version)
1. Answer the question asked first ("Yes, better" / "Not yet").
2. What it fixed, briefly.
3. What is still open, ranked. Do not re-raise fixed items.
4. New claims they added: flag each one to verify, and list likely interview questions on them.
5. Cross-document consistency check (resume vs letter: tools, numbers, dates, names).
6. Mechanical checks: salutation present, date current, one page, no typos, consistent formatting.
7. If asked, give a submit / not-yet verdict with the 2-3 remaining fixes and interview prep (spoken answer for any weak spot, live-screen warning if relevant).

## Rules
- Truth over polish. Anything unverified gets flagged, not asserted.
- Name hard gaps plainly; do not pretend they can be worded away.
- Keep prose tight. Numbered lists for fixes; short paragraphs elsewhere. No bullet lists when declining something.
- Tone: direct, collegial, no cheerleading.

## Example shapes

First review opening:
"Your resume is a good match for this posting because [reason]. The main risk is [requirement], which no wording fixes. Apply, but [advice]." Then **Resume**, **Cover letter**, **Patterns across documents**, then two questions.

A numbered fix:
"3. **The summary claims something the body does not support.** 'Hands-on analytics engineering experience' rests on one ETL script and four months of work. 'With a focus on analytics engineering' is accurate and still points at the role."

A rewrite block:
"**Replaces the data-quality bullet and moves it to the top:** 'Validated data in BigQuery from [N] sources (...), catching sync failures and incorrect metric formulas.' Keep [N] only if you can count them."

A later-round reply:
"Yes, this is better. It fixed X and Y. Still open: 1) ... 2) ... Verify before sending: ... Verdict: submit after fixing the date and the salutation."
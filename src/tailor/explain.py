"""Plain-language wording for check.md: what each section, check and Jev answer means.

The pipeline's own records (check.json, grade.json, plan.json) use codes, paths and passage
ids. A reviewer needs sentences: which line, what the problem is, and what to decide. Every
builder here takes those records and returns text, so check.md and the review page say the
same thing. Unknown codes fall back to the record's own message instead of failing.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.resume import iter_bullets

# ---------------------------------------------------------------------------
# Section blurbs (rendered as "> " notes under each heading)
# ---------------------------------------------------------------------------

INTRO = ("Your review list for this application. Every item needs a decision before you can approve. "
         "A decision only records your call: nothing here edits the resume or letter.")
GATE = ("Before tailoring, Jev (a small AI model the pipeline asks cheap yes/no questions) screened the "
        "posting. These answers came back against this job. They never remove a job; they only move it "
        "down the list. Mark it Reviewed once you've decided the job is still worth applying to.")
FIT = ("The ATS score estimates how well an applicant tracking system would match your resume to the "
       "posting's keywords, out of 100. Below 70 we stop and ask you to look.")
FIT_GAP = ("Here the gap is missing experience, not wording: even if the resume used every skill your "
           "vault backs, it couldn't reach 70. You can still apply; just know it's a stretch.")
WORDING_GAP = ("Here the gap is wording: your vault backs more of the posting's terms than the resume uses. "
               "The pipeline has already used its repair rounds, so no more will run on their own; "
               "the terms below are the words to work in if you edit a line yourself.")
NO_WORDING_LEFT = ("Here no repair round can help: every hard skill your vault backs is already on the resume "
                   "in the posting's words, so what's left is how close the match is, not missing wording.")
GRADE = ("The score is 60% the ATS estimate and 40% the share of Jev's checks the resume passed. The ATS "
         "estimate has five parts: keywords (the posting's terms that appear in the resume), skills (the "
         "required skills it names), title (how close your titles and headline are to this job title), "
         "sections (standard headings an ATS expects) and dates (dates it can read).")
JEV_NO = ("After writing, Jev checked the resume and letter with yes/no questions. These are the answers "
          "that came back the wrong way. Jev can be wrong, so read the part it's about and decide. "
          "If Jev is right, it's a real gap: be ready to speak to it in an interview, or fix the line. "
          "If Jev is wrong, there's nothing to do. Mark it Reviewed either way.")
JEV_NO_EVIDENCE = ("Jev also turned down these plain-word matches when looking for evidence, so the "
                   "resume doesn't use them. Nothing to decide: if one is wrong, make the vault passage "
                   "say it more clearly and rerun.")
DROPS = ("Before writing, the pipeline looks for vault passages that prove each skill the posting asks "
         "for. These passages use the word but don't show you have the skill, so they were set aside and the "
         "resume doesn't lean on them. For each, pick Correctly set aside if that's right, or Shows the skill if "
         "the passage really does show it (Set aside or Undo in check.md); approving with Shows the skill "
         "lets later applications use it again.")
SUGGESTED = ("The posting asks for these and the vault didn't back them well. Jev was asked about each "
             "passage below and said no or wasn't sure. If one does show the skill, pick This shows it: "
             "approving saves the match, so every later application counts it without asking Jev. Pick "
             "Doesn't show it to stop it being suggested again. This resume was written without these "
             "passages; to use one here, rerun from the evidence step after approving.")
ADDS = ("The plan read these passages and found they show a skill the word matching missed, so this "
        "resume could use them. Pick This shows it if that's right, or Doesn't show it if not; approving "
        "records the choice for every later application. Doesn't show it doesn't change this resume, so "
        "if a line leans on that passage, fix the line yourself.")
CHANGES = ("Every line this resume says differently from the {base} base resume. Read each one and "
           "make sure you're comfortable defending it in an interview.")
ISSUES = ("Automatic checks on the final resume and letter. Pick Keep if it's fine as it is, or Remove if "
          "you'll change it before applying. Remove only records your choice: edit the file yourself, then "
          "rerun the render and packet steps.")
NOTES = "Things the pipeline already handled. Nothing to decide; they're here so you know."
OUTSIDE = ("After the repair rounds, a fresh reviewer that never saw your vault read the posting, resume and "
           "letter and gave notes. The last round acted on the ones your vault and rules allow. Nothing to "
           "decide; the changes are in the resume and letter, and in Changes from the base.")

# ---------------------------------------------------------------------------
# Where in the resume
# ---------------------------------------------------------------------------


def _entries(data: dict[str, Any] | None) -> dict[str, tuple[str, dict[str, Any]]]:
    out = {}
    for section in ("experience", "projects"):
        for e in (data or {}).get(section) or []:
            out[f"{section}/{e.get('id')}"] = (section, e)
    return out


def entry_name(section: str, entry: dict[str, Any]) -> str:
    name = entry.get("company") or entry.get("name") or entry.get("title") or entry.get("id") or "?"
    return str(name) if section == "experience" else f"{name} project"


def path_label(path: str, data: dict[str, Any] | None) -> str:
    """'experience/algaecal/algaecal.sql-daily' -> 'AlgaeCal, bullet 1'."""
    if not path:
        return "Resume"
    if path == "summary":
        return "Summary"
    if path == "skills":
        return "Skills list"
    if path.startswith("skills/"):
        for g in (data or {}).get("skills") or []:
            if f"skills/{g.get('id')}" == path:
                return f"Skills list ({g.get('label') or g.get('id')})"
        return "Skills list"
    if path.startswith("education"):
        return "Education"
    if path in ("letter", "cover-letter.json"):
        return "Cover letter"
    m = re.match(r"paragraphs\[(\d+)\]", path)
    if m:
        return f"Cover letter, paragraph {int(m.group(1)) + 1}"
    parts = path.split("/")
    entries = _entries(data)
    key = "/".join(parts[:2])
    if key in entries:
        section, entry = entries[key]
        name = entry_name(section, entry)
        if len(parts) > 2:
            ids = [b.get("id") for b in entry.get("bullets") or []]
            if parts[2] in ids:
                return f"{name}, bullet {ids.index(parts[2]) + 1}"
            return f"{name}, a bullet"
        return name
    return path


def line_text(path: str, data: dict[str, Any] | None) -> str | None:
    """The resume text a path points at (a bullet or the summary), if any."""
    if not data:
        return None
    if path == "summary":
        return str((data.get("summary") or {}).get("text") or "") or None
    for p, b in iter_bullets(data):
        if p == path:
            return str(b.get("text") or "") or None
    return None


# ---------------------------------------------------------------------------
# Vault passages
# ---------------------------------------------------------------------------


def _file_name(file: str) -> str:
    stem = Path(file).stem.replace("-", " ").replace("_", " ")
    return stem[:1].upper() + stem[1:]


def _where(p: dict[str, Any]) -> str:
    return str(p.get("file_title") or _file_name(str(p.get("file") or "")))


def passage_label(pid: str, index: dict[str, dict] | None) -> str:
    """'resess.literature-review' -> 'Research Assistant — ReSeSS Lab, UBC (What I Did)'."""
    p = (index or {}).get(pid)
    if not p:
        return pid
    section = p.get("section") or []
    return f"{_where(p)} ({section[-1]})" if section else _where(p)


def passage_text(pid: str, index: dict[str, dict] | None, limit: int = 320) -> str | None:
    p = (index or {}).get(pid)
    if not p or not p.get("text"):
        return None
    text = str(p["text"]).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def group_passages(pids: list[str], index: dict[str, dict] | None) -> str:
    """'AlgaeCal (9), Soft skills (1), Coursework (2)': where a list of passages comes from."""
    counts: dict[str, int] = {}
    for pid in pids:
        p = (index or {}).get(pid)
        where = _where(p) if p else pid.split(".")[0]
        counts[where] = counts.get(where, 0) + 1
    return ", ".join(f"{k} ({v})" for k, v in counts.items())


# ---------------------------------------------------------------------------
# Gate flags
# ---------------------------------------------------------------------------

_GATE = {
    "seniority_fit": "The role may be more senior than entry level.",
    "must_haves": "Your resume may cover few of the posting's must-haves.",
    "domain_fit": "The kind of work may not match what you've done.",
    "location_ok": "The location may not be Vancouver or remote from Canada.",
    "requires_phd": "The posting may require a PhD.",
    "years_ok": "The posting may ask for more than about three years of experience.",
    "is_coop": "This may be a co-op or student work term.",
}


def gate_flag(flag: dict[str, Any]) -> tuple[str, list[str]]:
    qid = str(flag.get("question") or "?")
    head = _GATE.get(qid, f"{qid}: {flag.get('reason', '')}")
    details = []
    if flag.get("text"):
        details.append(f"Jev was asked: \"{flag['text']}\"")
    if flag.get("reason") == "unchecked":
        details.append("Jev couldn't answer this one, so it wasn't checked.")
    return head, details


# ---------------------------------------------------------------------------
# Jev's checklist answers (grade.json "checklist" items that failed)
# ---------------------------------------------------------------------------


def _sure(conf: Any) -> str:
    return f" ({conf:.0%} sure)" if isinstance(conf, (int, float)) else ""


def _quoted(question: str) -> str | None:
    m = re.search(r'"(.+)"\?$', question)
    return m.group(1) if m else None


def jev_item(item: dict[str, Any], reqs: dict[str, dict], data: dict[str, Any] | None,
             title: str, company: str) -> tuple[str, list[str]]:
    """A failed checklist item as a headline plus details: what Jev judged, and what to look at."""
    qid = str(item.get("id") or "")
    q = str(item.get("question") or qid)
    sure = _sure(item.get("confidence"))
    details: list[str] = []
    if qid.startswith("must."):
        r = reqs.get(item.get("req_id") or qid.removeprefix("must."), {})
        need = r.get("text") or q
        degree = item.get("fit_gap") == ["degree"]
        head = (f"Must-have may not be met: \"{need}\". Jev doubts your degree fits it{sure}." if degree else
                f"Must-have not clearly shown: \"{need}\". Jev said no bullet shows it"
                f"{' with a named tool and scope' if 'names a tool' in q else ''}{sure}.")
        if r.get("quote") and r["quote"] != need:
            details.append(f"The posting says: \"{r['quote']}\"")
        if degree:
            details.append("Your degree can't be rewritten, so no repair round tried to fix this.")
            details.append("Judge: does your degree count as the field the posting asks for? If not, it's a gap to own.")
            return head, details
        if item.get("fit_gap") == ["years of experience"]:
            details.append("Years of experience come from your dates, which no rewrite can change, so no repair "
                           "round tried to fix this; it is part of the weaker fit.")
        elif item.get("fit_gap"):
            details.append(f"Not in your vault: {', '.join(item['fit_gap'])}. The rest is already on the resume, so "
                           "no repair round tried to fix this; it is part of the weaker fit.")
        details.append("Judge: does any bullet show this? If not, it's a gap to own in the cover letter or interview.")
    elif qid == "top_third":
        head = f"The top of the resume may not read like a {title or 'this'} resume{sure}."
        if line_text("summary", data):
            details.append(f"The summary: \"{line_text('summary', data)}\"")
        details.append("Judge: would a recruiter skimming the top few lines see the right role?")
    elif qid.startswith("portable."):
        path = item.get("bullet") or qid.removeprefix("portable.")
        head = f"{path_label(path, data)} may be generic: Jev thinks it could describe almost any candidate{sure}."
        if line_text(path, data):
            details.append(f"The bullet: \"{line_text(path, data)}\"")
        details.append("Judge: does it name something only you did (a tool, a number, a result)?")
    elif qid == "letter.specific":
        head = f"The cover letter may not mention anything specific to {company or 'the company'}{sure}."
        details.append("Judge: does it name something about this company a generic letter wouldn't?")
    elif qid in ("letter.opener", "letter.closer"):
        which = "opening" if qid == "letter.opener" else "closing"
        head = f"The letter's {which} sentence may be generic: it could fit almost any job{sure}."
        sentence = item.get("sentence") or _quoted(q)
        if sentence:
            details.append(f"The sentence: \"{sentence}\"")
        details.append("Judge: would this sentence only make sense in a letter to this company?")
    else:
        head = f"Jev answered no to: \"{q}\"{sure}."
    return head, details


def evidence_no(n: dict[str, Any], index: dict[str, dict] | None) -> str:
    pid = str(n.get("passage") or "")
    text = n.get("text") or passage_text(pid, index) or ""
    where = passage_label(pid, index) if pid else "a vault passage"
    return f"{n.get('term', '?')}: not counted from {where}: \"{text}\""


# ---------------------------------------------------------------------------
# Passages that might show a skill (evidence.json candidates) and the plan's adds
# ---------------------------------------------------------------------------


def _skill(key: str) -> str:
    from src.tailor import taxonomy
    name = taxonomy.canonical(key) or key
    return name[:1].upper() + name[1:]


def suggestion(key: str, pid: str, value: float | None, req_text: str,
               index: dict[str, dict] | None) -> tuple[str, list[str]]:
    head = f"{_skill(key)}: does {passage_label(pid, index)} show it?"
    details = [f"The posting asks: \"{req_text}\""] if req_text else []
    text = passage_text(pid, index)
    if text:
        details.append(f"The passage: \"{text}\"")
    if value is not None:
        details.append(f"Jev's answer: {'not sure' if value >= 0.4 else 'no'} ({value:.2f} out of 1).")
    return head, details


def add(d: dict[str, Any], index: dict[str, dict] | None) -> tuple[str, list[str]]:
    pid = str(d.get("passage") or "?")
    head = f"{_skill(str(d.get('term') or '?'))}: counted from {passage_label(pid, index)}."
    details = []
    text = passage_text(pid, index)
    if text:
        details.append(f"The passage: \"{text}\"")
    if d.get("reason"):
        details.append(f"Why: {d['reason']}.".replace("..", "."))
    return head, details


# ---------------------------------------------------------------------------
# Evidence the plan set aside (plan.json evidence_drops)
# ---------------------------------------------------------------------------


def drop(d: dict[str, Any], index: dict[str, dict] | None, new: bool) -> tuple[str, list[str]]:
    term = str(d.get("term") or "?")
    pid = str(d.get("passage") or "?")
    head = f"{term[:1].upper() + term[1:]}: not counted from {passage_label(pid, index)}."
    details = []
    text = passage_text(pid, index)
    if text:
        details.append(f"The passage: \"{text}\"")
    if d.get("reason"):
        details.append(f"Why: {d['reason']}.".replace("..", "."))
    details.append("First set aside on this job; later jobs skip it too." if new
                   else "Set aside on an earlier job, so it was skipped here as well.")
    return head, details


# ---------------------------------------------------------------------------
# Check issues (check.json criticals, warnings and flags)
# ---------------------------------------------------------------------------

# code -> (what it means, why it matters). {term}, {n}, {phrase} come from the issue's data.
_ISSUES: dict[str, tuple[str, str]] = {
    "skill_only_in_list": ("{term} is in your skills list, but no bullet shows you using it.",
                           ("A skill with no bullet behind it can look padded. Keep it if you're happy to be "
                            "asked about {term} in an interview.")),
    "invented_skill": ("{term} isn't backed by the passages this line cites, or anywhere else in your vault "
                       "or base resume.",
                       "The resume should only claim what the vault backs. If another passage shows it, cite "
                       "that passage."),
    # invented_skill when the vault backs the skill, but not in the draft's words.
    "invented_wording": ("Your vault backs {term}, but not in the words this line uses.",
                         "The resume should say it the way the vault does."),
    "invented_number": ("The number {term} isn't in your vault or base resume.",
                        "Every number has to be one you can back up."),
    "unsupported_date": ("A year on this line isn't in your vault or base resume.",
                         "Dates have to match your record exactly."),
    "invented_employer": ("This job isn't in your base resume.", "The resume can't add employers."),
    "invented_project": ("This project isn't in your base resume.", "The resume can't add projects."),
    "dropped_employer": ("A job from your base resume is missing.", "Leaving out a job leaves a gap in your dates."),
    "locked_changed": ("A line that should never change (titles, dates, education) was edited.",
                       "Those facts must match your record."),
    "missing_source": ("This line doesn't point to any vault evidence.",
                       "Without a source nobody checked that it's true."),
    "unknown_source": ("This line points to a vault passage that doesn't exist.",
                       "Its evidence couldn't be checked."),
    "non_claim_source": ("This line's evidence is a passage marked as not for the resume (interview notes or guidance).",
                         "Those passages aren't claims you've agreed to put in writing."),
    "years_inflation": ("This line claims more years of experience than your dates support.",
                        "A recruiter will compare it with your dates."),
    "title_drift": ("This line uses a job title that isn't in your vault or base resume.",
                    "Titles must match what you actually held."),
    "keyword_coverage_dropped": ("Some posting terms the base resume covered are gone from this one.",
                                 "Those terms were helping the ATS score."),
    "term_stuffing": ("{term} is repeated many times.", "Heavy repetition reads as keyword stuffing."),
    "verbatim_posting_copy": ("This line copies 8 or more words straight from the posting.",
                              "Recruiters notice copied wording."),
    "too_many_skills": ("The skills list is long (over 30 items).", "A long list dilutes the skills that matter."),
    "bullet_count": ("This entry has an unusual number of bullets (1 to 6 is normal).",
                     "Too many crowds the page; too few undersells the job."),
    "bullet_long": ("This bullet is long (over 200 characters).", "Long bullets wrap to three lines and get skimmed."),
    "duplicate_bullets": ("Two bullets say nearly the same thing.", "Repeats waste space."),
    "ai_phrase": ("This wording is a phrase AI writing tends to use ({term}).",
                  "Recruiters increasingly spot and discount it."),
    "jev_unsupported": ("Jev doesn't think this line is backed by the vault passages it cites.",
                        "Make sure it's true as written and that you could explain it in an interview."),
    "resume_invalid": ("The resume file has a formatting problem.", "It may not render correctly."),
    "letter_shape": ("The cover letter file has a formatting problem.", "It may not render correctly."),
    "familiar_absent_term": ("The letter says you're familiar with {term}, but the vault doesn't show it.",
                             "Only claim familiarity you can back up."),
    "keen_to_grow": ("The letter says it's keen to learn or grow more than once.",
                     "Once reads as eager; more reads as inexperienced."),
    "course_grade": ("The letter uses a course grade as evidence ({term}).",
                     "The work is the evidence; name what you built or did instead."),
    "no_company_fact": ("The letter doesn't mention a checked fact about the company.",
                        "A specific fact is what makes a letter read as written for this job."),
    "unverified_company_fact": ("The letter uses a company fact that wasn't verified.",
                                "It may be wrong or out of date."),
    "paragraph_count": ("The letter has an unusual number of paragraphs (3 to 5 is normal).",
                        "Very short or long letters get skimmed."),
    "skill_name_only": ("A letter paragraph is one sentence that only names a skill.",
                        "A skill named with no story reads as padding; it belongs inside a real example."),
    "letter_length": ("The letter is outside the usual 200 to 300 words.",
                      "Too short reads as little effort; too long gets skimmed."),
}

# Older check.json files have no "data"; these pull the same field out of the message.
_TERM_FROM_MESSAGE = re.compile(r"^(?:[\w\[\]]+: )?(?:mentions |'familiar with' )?'?(?P<term>[^']+?)'?"
                                r"(?: appears| is not|, which)")


def _term(issue: dict[str, Any]) -> str | None:
    data = issue.get("data") or {}
    if data.get("term"):
        return str(data["term"])
    msg = str(issue.get("message") or "")
    if issue.get("code") == "ai_phrase":
        m = re.search(r"'([^']+)'", msg)
        return m.group(1) if m else None
    m = _TERM_FROM_MESSAGE.match(msg)
    return m.group("term") if m else None


_EXTRA = re.compile(r"even with (?P<ids>.+?) \(p=(?P<p>[\d.]+)\)|\(p=(?P<p2>[\d.]+)\)")


def _line_sources(path: str, data: dict[str, Any] | None) -> list[str]:
    if not data:
        return []
    if path == "summary":
        return list((data.get("summary") or {}).get("sources") or [])
    return next((list(b.get("sources") or []) for p, b in iter_bullets(data) if p == path), [])


def _unsupported_details(it: dict[str, Any], data: dict[str, Any] | None,
                         index: dict[str, dict] | None) -> list[str]:
    """What Jev read for a jev_unsupported line, quoted, so the doubt can be checked by eye."""
    d = it.get("data") or {}
    m = _EXTRA.search(str(it.get("message") or ""))
    extra = d.get("extra")
    if extra is None:
        extra = [x.strip() for x in m.group("ids").split(",")] if m and m.group("ids") else []
    prob = d.get("p")
    if prob is None and m:
        prob = float(m.group("p") or m.group("p2"))
    pids = [*_line_sources(str(it.get("path") or ""), data), *[x for x in extra if x]]
    pids = list(dict.fromkeys(pids))
    chance = f" (it put the chance at about {round(float(prob) * 100)}%)" if prob is not None else ""
    out = [(f"Jev read these vault passages and still wasn't sure they back every part of the line{chance}. "
            "Look for a part of the line none of them says:")]
    for pid in pids:
        text = passage_text(pid, index, limit=200)
        p = (index or {}).get(pid)
        out.append(f"{_where(p) if p else pid}: \"{text}\"" if text else pid)
    return out


def issue(it: dict[str, Any], data: dict[str, Any] | None,
          index: dict[str, dict] | None = None) -> tuple[str, list[str]]:
    """A check issue as 'Where: what it means' plus details (the line, why it matters, the raw detail)."""
    code = str(it.get("code") or "")
    path = str(it.get("path") or "")
    where = path_label(path, data) if path else ("Cover letter" if it.get("doc") == "letter" else "Resume")
    known = _ISSUES.get(code)
    if code == "invented_skill" and (it.get("data") or {}).get("wording"):
        known = _ISSUES["invented_wording"]
    term = _term(it)
    details: list[str] = []
    if known and ("{term}" not in known[0] or term):
        head = f"{where}: {known[0].format(term=term)}"
        why = known[1].format(term=term or "it")
    else:
        head = f"{where}: {it.get('message') or code}"
        why = known[1] if known else ""
    text = line_text(path, data)
    if text and path != "skills" and not path.startswith("skills/"):
        details.append(f"The line: \"{text}\"")
    if why:
        details.append(f"Why it matters: {why}")
    if code == "jev_unsupported":
        details += _unsupported_details(it, data, index)
    elif known and it.get("message") and "{term}" not in known[0]:
        details.append(f"Checker's note: {it['message']}")
    return head, details


_GAP = re.compile(r"\(p=(?P<first>[\d.]+)\) but agreed once (?P<ids>.+) were cited too \(p=(?P<second>[\d.]+)\)")


def is_note(it: dict[str, Any]) -> bool:
    """Issues the pipeline already resolved (shown without a box)."""
    return it.get("code") == "jev_citation_gap"


def note(it: dict[str, Any], data: dict[str, Any] | None, index: dict[str, dict] | None) -> str:
    """jev_citation_gap: Jev doubted a line until it saw more of the vault; the sources were widened."""
    where = path_label(str(it.get("path") or ""), data)
    d = it.get("data") or {}
    added = d.get("added")
    if added is None:
        m = _GAP.search(str(it.get("message") or ""))
        added = [s.strip() for s in m.group("ids").split(",")] if m else []
    if not added:
        return f"{where}: {it.get('message', '')}"
    return (f"{where}: Jev first doubted this line from the passages it cited, then agreed once it also saw "
            f"{len(added)} more of your vault passages ({group_passages(added, index)}). Those were added as "
            "its sources; the wording didn't change.")

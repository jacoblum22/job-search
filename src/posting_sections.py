"""Which part of a posting a word sits in: a requirement, a nice-to-have, or text about the employer.

Postings mark their nice-to-haves with headings ("Preferred Qualifications", "Bonus
Points", "Assets") or inline cues ("Python is a plus", "Redshift experience preferred").
Text about the company, its team or its products ("Our portfolio includes Microsoft
Fabric, Azure Cosmos DB ... and Power BI") names tools nobody is asking the candidate
for. `Sections(text).kind(pos)` reads both and returns one of:

  "required"  under a requirements heading ("Basic Qualifications", "What you'll bring")
  "preferred" under a nice-to-have heading, or in a clause with a cue ("a plus")
  "about"     about-the-company prose ("About us", "Our products ...")
  "other"     anything else (duties, the role, no heading at all)

Postings stored without headings (some arrive flattened onto one line) mostly come
out "other", which the tier score counts like "required".
"""

from __future__ import annotations

import re

_HTML = re.compile(r"<(?:p|div|br|ul|ol|li|h[1-6]|strong|b|span|a)\b[^>]*>", re.IGNORECASE)

_PREF_H = (r"(?:preferred|nice[ -]to[ -]haves?|bonus|desired|desirable|assets?|plus(?:es)?|ideally|helpful|"
           r"would be (?:especially )?(?:useful|great|nice)|you may have|also has|not required|extra credit|"
           r"good to have|additional (?:skills|qualifications))")
_REQ_H = (r"(?:required|requirements?|minimum|basic|must[ -]haves?|qualifications|what you(?:'|’)?ll bring|"
          r"what you will bring|what you bring|what will you bring|what they look for|key qualifications|you have|"
          r"what we(?:'|’)?re looking for|what we are looking for|who you are|skills|experience|education)")
_OTHER_H = (r"(?:responsibilities|your role|role overview|role summary|position summary|job summary|job description|"
            r"the position|what you(?:'|’)?ll do|what you will do|the role|about (?:the role|the job|the position|"
            r"this role|the opportunity)|benefits|perks|compensation|salary|why|key duties|duties|in this role|"
            r"day to day|your impact|the opportunity)")
_ABOUT_H = (r"(?:overview|company overview|about (?:us|the company|the team|\w+(?: \w+)?)|who we are|"
            r"our (?:team|mission|story|company|values|culture)|the team|life at \w+)")

# A heading line: markdown heading, bold, ending in a colon, or a short plain line.
_LINE_H = re.compile(r"^\s*(?:#+\s*|\*\*|__)?(?P<h>[^\n]{3,80}?)(?:\*\*|__)?\s*:?\s*$", re.MULTILINE)
# Headings inside a flattened posting: "Preferred Qualifications - ...", "Assets:".
_INLINE = re.compile(rf"(?i)\b(?P<h>(?:{_PREF_H}|basic|minimum|required)\s+(?:qualifications|requirements|skills)|"
                     r"nice to haves?|assets?(?=\s*:)|bonus(?: points)?(?=\s*:))\b(?=\s*(?:[:\-–]|\(|\n))")
_BOLD = re.compile(r"\*\*(?P<h>[^*\n]{3,60}?)\s*:?\s*\*\*")
_RUN_IN = re.compile(r"(?i)\b(?P<h>about (?:the team|us|the company)|your role|what you(?:'|’)?ll do|what you will do|"
                     r"responsibilities|what you(?:'|’)?ll bring|what you will bring)\s*:")
# A sentence about the employer: "We connect field operations ... and 180+ ERP integrations".
_WE = re.compile(r"^\W*(?:we (?:connect|serve|help|power|enable|provide|offer)\b|"
                 r"our (?:products?|portfolio|customers|clients|mission)\b)", re.IGNORECASE)
# A clause that asks for something; it ends an about-the-team section in a flattened posting.
_ASK = re.compile(r"^\W*(?:experience|strong|proficien|knowledge|familiar|have|bachelor|master|degree|\d+\+? years|"
                  r"ability|expertise|hands-on|solid|deep|working knowledge|understanding)", re.IGNORECASE)
_CUE = re.compile(r"(?i)\b(?:preferred|is a plus|an? (?:strong )?asset|nice to have|bonus|ideally|advantage(?:ous)?|"
                  r"(?:strong )?preference for|desirable|would be great|helpful|not required|good to have|"
                  r"an? (?:strong |big |huge |definite )?plus)\b")
_CLAUSE_SEP = re.compile(r"(?<=[.;!?])\s+(?=[A-Z*•+-])| [-+•*·] ")


def to_markdown(description: str) -> str:
    """Postings stored as HTML read as markdown, so headings and bullets survive."""
    if _HTML.search(description or ""):
        from markdownify import markdownify

        return re.sub(r"\n{3,}", "\n\n", markdownify(description)).strip()
    return (description or "").strip()


def heading_kind(heading: str) -> str | None:
    h = heading.lower()
    if re.search(rf"\b{_PREF_H}\b", h):
        return "preferred"
    # "The ideal candidate: requirements and experience" is the main list; "an ideal candidate also has" isn't.
    if re.search(r"\bideal\b", h) and not re.search(r"\brequire", h):
        return "preferred"
    if re.search(r"\babout (?:you|yourself)\b", h):
        return "required"
    if re.search(rf"\b{_OTHER_H}\b", h):
        return "other"
    if re.search(rf"^\W*{_ABOUT_H}\W*$", h):
        return "about"
    if re.search(rf"\b{_REQ_H}\b", h):
        return "required"
    return None


class Sections:
    """A posting's headings, read once; `kind(pos)` classifies any position in it."""

    def __init__(self, text: str) -> None:
        self.text = text
        marks = []
        for m in _LINE_H.finditer(text):
            line = m.group(0)
            plain = (len(m["h"].split()) <= 6 and not re.search(r"[.,;!?]\s*$|\.\s", m["h"])
                     and not line.lstrip().startswith(("-", "*", "+", "•")))
            if line.strip().startswith(("#", "**", "__")) or line.rstrip().endswith(":") or plain:
                # An unknown heading still ends an about-the-company section.
                marks.append((m.start(), heading_kind(m["h"]) or "unknown"))
        # Bold text is a heading only after a line or sentence end; at a bullet's start it labels an
        # item, and mid-sentence ("Experience with **CRM platforms; HubSpot preferred**") it's emphasis.
        bold = [m for m in _BOLD.finditer(text)
                if text[:m.start()].rstrip(" ").endswith(("\n", ".", ":", "!", "?", "**")) or not text[:m.start()].strip()]
        for m in [*_INLINE.finditer(text), *bold, *_RUN_IN.finditer(text)]:
            k = heading_kind(m["h"])
            if k:
                marks.append((m.start(), k))
        self.marks = sorted(marks)

    def kind(self, pos: int) -> str:
        text = self.text
        kind = "other"
        for start, k in self.marks:
            if start > pos:
                break
            if k != "unknown":
                kind = k
            elif kind == "about":
                kind = "other"
        a = text.rfind("\n", 0, pos) + 1
        b = text.find("\n", pos)
        b = len(text) if b < 0 else b
        line_a, line_b = a, b
        # An about-the-team section is prose; a bulleted list after it is the posting's asks.
        if kind == "about" and re.match(r"\s*[-*•+]\s", text[a:b]):
            kind = "other"
        # The sentence or flattened bullet around the position.
        starts = [m.end() for m in _CLAUSE_SEP.finditer(text, a, pos)]
        a = starts[-1] if starts else a
        m = _CLAUSE_SEP.search(text, pos, b)
        b = m.start() if m else b
        clause, rel = text[a:b], pos - a
        # A cue inside brackets applies to the bracket only: "Strong SQL (Redshift experience a plus)".
        for m in re.finditer(r"\([^()]*\)", clause):
            if not m.start() <= rel < m.end():
                clause = clause[:m.start()] + " " * (m.end() - m.start()) + clause[m.end():]
        if kind == "about" and _ASK.match(clause):
            kind = "other"
        if _CUE.search(clause):
            return "preferred"
        if kind == "other" and _WE.match(clause):
            return "about"
        # A short cue sentence later in the same bullet covers it: "... Linux. Preferred but not required."
        if any(len(s.split()) <= 6 and _CUE.search(s) for s in re.split(r"(?<=[.;!?])\s+", text[line_a:line_b])):
            return "preferred"
        return kind

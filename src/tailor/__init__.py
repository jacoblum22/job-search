"""Tailoring pipeline: one job posting -> tailored resume and cover letter.

See docs/tailoring-contract.md for the file layout, JSON shapes and the
split between code steps (this package) and Claude steps (prompts/tailor/).
"""


class TailorError(Exception):
    """An input file is missing or malformed; the message says which and why."""

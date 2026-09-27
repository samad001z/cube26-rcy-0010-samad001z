"""Checks a model's explanation against the decision trace (CLAUDE.md rule 3). Any failure
rejects the text, and the standard template is used instead.

Accepted only if:
  - the answer is JSON with exactly one string field, `explanation`, of sensible length;
  - every ID-like token, snake_case name, ISO date and number in it appears in the trace;
  - it writes no date in any other form (so no date can slip past the ISO check);
  - the only decision word in capitals is the record's own decision, and it is there;
  - it has no link and none of the forbidden phrases (CLAUDE.md).
"""

import json
import re
from typing import Any

from app.llm.trace import corpus

MIN_CHARS = 40
MAX_CHARS = 1200

FORBIDDEN = (
    "tamper-proof",
    "tamper-evident",
    "immutable",
    "production-grade",
    "guaranteed",
    "autonomous recovery",
    "works well",
    "highly accurate",
    "ai decides",
)

_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T[\d:.]+Z?)?\b")
OTHER_DATE = re.compile(
    rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}(?:\s+\d{{2,4}})?\b"
    rf"|\b{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?\b"
    r"|\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b",
    re.IGNORECASE,
)
# DEMO-F01-1, FBA-DEMO-01, R_DUPLICATE, DO_NOT_CLAIM
ID_SEPARATED = re.compile(r"\b[A-Z][A-Z0-9]*(?:[-_][A-Z0-9]+)+\b")
# X00DEMO0001, B0DEMO0001: letters and digits run together
ID_RUN = re.compile(r"\b(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{5,}\b")
SNAKE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
NUMBER = re.compile(r"\d+(?:\.\d+)?")
DNC = re.compile(r"\bDO[ _]NOT[ _]CLAIM\b")
CLAIM = re.compile(r"\bCLAIM\b")
REVIEW = re.compile(r"\bREVIEW\b")


class ExplanationRejected(ValueError):
    """Why a model's text was not used (stored as the fallback reason)."""


def _parse(raw: str) -> str:
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        raise ExplanationRejected("answer is not JSON") from None
    if not isinstance(data, dict) or set(data) != {"explanation"}:
        raise ExplanationRejected("answer must be a JSON object with only `explanation`")
    text = data["explanation"]
    if not isinstance(text, str):
        raise ExplanationRejected("`explanation` is not a string")
    text = " ".join(text.split())
    if not MIN_CHARS <= len(text) <= MAX_CHARS:
        raise ExplanationRejected(f"explanation length {len(text)} outside {MIN_CHARS}-{MAX_CHARS}")
    return text


def _decision_words(text: str) -> set[str]:
    found = {"DO_NOT_CLAIM"} if DNC.search(text) else set()
    rest = DNC.sub(" ", text)
    if CLAIM.search(rest):
        found.add("CLAIM")
    if REVIEW.search(rest):
        found.add("REVIEW")
    return found


def validate_explanation(raw: str, trace: dict[str, Any]) -> str:
    """The explanation text if it passes every check, else ExplanationRejected."""
    text = _parse(raw)
    lower = text.lower()
    for phrase in FORBIDDEN:
        if phrase in lower:
            raise ExplanationRejected(f"forbidden phrase {phrase!r}")
    if "http" in lower or "www." in lower:
        raise ExplanationRejected("contains a link")

    words = _decision_words(text)
    if words != {trace["decision"]}:
        found = sorted(words) or "none"
        raise ExplanationRejected(
            f"decision words {found} do not match the decision {trace['decision']}"
        )

    source = corpus(trace)
    rest = text
    for m in ISO_DATE.findall(rest):
        if m not in source:
            raise ExplanationRejected(f"date {m} is not in the trace")
    rest = ISO_DATE.sub(" ", rest)
    other = OTHER_DATE.search(rest)
    if other:
        raise ExplanationRejected(f"date written as {other.group(0)!r}, not YYYY-MM-DD")

    decision_value = DNC.sub(" ", rest)  # "DO NOT CLAIM" is a phrase, not an ID
    for pattern, kind in ((ID_SEPARATED, "ID"), (ID_RUN, "ID"), (SNAKE, "name")):
        for m in pattern.findall(decision_value):
            if m not in source:
                raise ExplanationRejected(f"{kind} {m} is not in the trace")
        decision_value = pattern.sub(" ", decision_value)

    numbers = set(NUMBER.findall(source))
    for m in NUMBER.findall(decision_value):
        if m not in numbers:
            raise ExplanationRejected(f"number {m} is not in the trace")
    return text

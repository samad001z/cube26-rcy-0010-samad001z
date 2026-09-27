"""Checks a model's explanation against the decision trace (CLAUDE.md rule 3). Any failure
rejects the text, and the standard template is used instead.

Accepted only if:
  - the answer is JSON with exactly one string field, `explanation`, of sensible length;
  - every ID-like token, snake_case name, ISO date and number in it appears in the trace;
  - it writes no date in any other form (so no date can slip past the ISO check);
  - the only decision word in capitals is the record's own decision, and it is there;
  - it contains no phrasing, in any case, that argues for a different decision (e.g.
    "you should claim the fee now" on a REVIEW record);
  - it has no currency symbol, no currency code other than the trace's own, no percentage,
    no number word ("twice", "half", ...) and no negative number;
  - the figure nearest the word "claim" is the claim amount itself, not some other number;
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
# DEMO-F01-1, FBA-DEMO-01, R_DUPLICATE, DO_NOT_CLAIM; matched case-insensitively so a
# lower-case rendering of an ID (e.g. "demo-f01-1") is checked too, not silently skipped.
ID_SEPARATED = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)+\b")
# X00DEMO0001, B0DEMO0001: letters and digits run together, either case.
ID_RUN = re.compile(r"\b(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{5,}\b")
SNAKE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
NUMBER = re.compile(r"\d+(?:\.\d+)?")
# A minus not glued to a letter or digit before it, so a hyphenated ID like "PRP-1" is not
# mistaken for a negative number.
NEGATIVE_NUMBER = re.compile(r"(?<![A-Za-z0-9])-\s?\d+(?:\.\d+)?")
CURRENCY_SYMBOL = re.compile(r"[$€£¥]")
KNOWN_CURRENCY_CODES = ("USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "CNY", "INR", "MXN")
CURRENCY_CODE = re.compile(r"\b(?:" + "|".join(KNOWN_CURRENCY_CODES) + r")\b")
PERCENT = re.compile(r"\d\s*%")
NUMBER_WORD = re.compile(
    r"\b(?:once|twice|thrice|double|triple|quadruple|half|quarter|dozen)\b", re.IGNORECASE
)
# "claim amount 12.50" when 12.50 is really the charge: the number nearest "claim" must be
# the claim amount itself, not any other figure in the trace. The gap excludes sentence
# punctuation, so this does not reach into an unrelated later sentence, and hyphens, so it
# does not reach past a hyphenated ID (e.g. "claimed for L-1") into the ID's own digits.
CLAIM_AMOUNT_NEAR = re.compile(r"\bclaim\w*\b[^.?!\d-]{0,40}?(\d+(?:\.\d+)?)", re.IGNORECASE)
DNC = re.compile(r"\bDO[ _]NOT[ _]CLAIM\b")
CLAIM = re.compile(r"\bCLAIM\b")
REVIEW = re.compile(r"\bREVIEW\b")

# Case-insensitive phrasing that argues for a decision, however it is cased: "You should
# claim the fee now" on a REVIEW record, or "do not claim this yet" on a CLAIM record. The
# capitalised checks above only catch the record's own decision word; these catch the model
# arguing for a different one in lower case, which the capitals check never sees.
_DNC_SIGNAL = re.compile(
    r"\bdo\s*n[o']?t\s+claim\b"
    r"|\bshould\s+not\s+(?:be\s+)?claim(?:ed)?\b"
    r"|\b(?:cannot|can't)\s+be\s+claim(?:ed)?\b"
    r"|\bnot\s+(?:yet\s+)?claim(?:able|ed)?\b",
    re.IGNORECASE,
)
_CLAIM_SIGNAL = re.compile(
    r"\bshould\s+(?:be\s+)?claim(?:ed)?\b"
    r"|\bcan\s+be\s+claim(?:ed)?\b"
    r"|\beligible\s+to\s+claim\b"
    r"|\brecommend(?:s|ed)?\s+claim(?:ing)?\b"
    r"|\bclaim\s+(?:the|this|it)\b"
    r"|\bfile\s+(?:a|the)\s+claim\b(?!\s+outside)",
    re.IGNORECASE,
)
_REVIEW_SIGNAL = re.compile(
    r"\bneeds?\s+(?:further\s+)?review\b"
    r"|\bshould\s+be\s+reviewed\b"
    r"|\bsend\s+(?:it|this)?\s*for\s+review\b"
    r"|\bunder\s+review\b",
    re.IGNORECASE,
)


def _decision_signals(text: str) -> set[str]:
    found: set[str] = set()
    rest = text
    if _DNC_SIGNAL.search(rest):
        found.add("DO_NOT_CLAIM")
        rest = _DNC_SIGNAL.sub(" ", rest)
    if _CLAIM_SIGNAL.search(rest):
        found.add("CLAIM")
        rest = _CLAIM_SIGNAL.sub(" ", rest)
    if _REVIEW_SIGNAL.search(rest):
        found.add("REVIEW")
    return found


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

    other_signals = _decision_signals(text) - {trace["decision"]}
    if other_signals:
        raise ExplanationRejected(
            f"wording argues for {sorted(other_signals)}, not the decision {trace['decision']}"
        )

    if CURRENCY_SYMBOL.search(text):
        raise ExplanationRejected("contains a currency symbol; write amounts as in the trace")
    for code in CURRENCY_CODE.findall(text):
        if code != trace.get("currency"):
            raise ExplanationRejected(f"currency {code} is not the trace's currency")
    if PERCENT.search(text):
        raise ExplanationRejected("contains a percentage, which is not in the trace")
    if NUMBER_WORD.search(text):
        raise ExplanationRejected("contains a number word instead of a figure from the trace")
    if NEGATIVE_NUMBER.search(text):
        raise ExplanationRejected("contains a negative number, which is not in the trace")
    claim_amount = trace["claim"]["amount"] if trace.get("claim") else None
    for m in CLAIM_AMOUNT_NEAR.findall(text):
        if m != claim_amount:
            raise ExplanationRejected(f'the amount near "claim" ({m}) is not the claim amount')

    source = corpus(trace)
    # Whole-token sets, not the raw corpus string: a substring check would let "DEMO-F01-1"
    # pass against a trace that only has "DEMO-F01-12", or "R_CONTRADICTED" against
    # "R_CONTRADICTED_FULL". IDs are folded to upper case so a lower-case rendering is
    # still checked, not skipped.
    id_tokens = {m.upper() for m in ID_SEPARATED.findall(source)}
    id_tokens |= {m.upper() for m in ID_RUN.findall(source)}
    name_tokens = set(SNAKE.findall(source))
    rest = text
    for m in ISO_DATE.findall(rest):
        if m not in source:
            raise ExplanationRejected(f"date {m} is not in the trace")
    rest = ISO_DATE.sub(" ", rest)
    other = OTHER_DATE.search(rest)
    if other:
        raise ExplanationRejected(f"date written as {other.group(0)!r}, not YYYY-MM-DD")

    decision_value = DNC.sub(" ", rest)  # "DO NOT CLAIM" is a phrase, not an ID
    # SNAKE first: it only matches all-lower-case, underscore-only tokens, so it claims
    # genuine snake_case names before the now case-insensitive ID_SEPARATED can.
    for m in SNAKE.findall(decision_value):
        if m not in name_tokens and m.upper() not in id_tokens:
            raise ExplanationRejected(f"name {m} is not in the trace")
    decision_value = SNAKE.sub(" ", decision_value)
    for pattern in (ID_SEPARATED, ID_RUN):
        for m in pattern.findall(decision_value):
            if m.upper() not in id_tokens:
                raise ExplanationRejected(f"ID {m} is not in the trace")
        decision_value = pattern.sub(" ", decision_value)

    numbers = set(NUMBER.findall(source))
    for m in NUMBER.findall(decision_value):
        if m not in numbers:
            raise ExplanationRejected(f"number {m} is not in the trace")
    return text

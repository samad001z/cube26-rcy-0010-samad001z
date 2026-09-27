"""The standard explanation: built by code from the trace, used whenever a model's text is
not (LLM off, call failed, text rejected, fail-open record)."""

from typing import Any

from app.llm.prompt import DECISION_WORDS


def _sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    text = text[0].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else text + "."


def template_text(trace: dict[str, Any]) -> str:
    parts = [f"{DECISION_WORDS[trace['decision']]}. {_sentence(trace['reason'])}"]
    if trace["claim"]:
        parts.append(f"Claim {trace['claim']['amount']} {trace['currency']}.")
    evidence = [c["id"] for c in trace["cited"] if c["kind"] == "evidence"]
    lines = [c["id"] for c in trace["cited"] if c["kind"] == "charge"]
    parts.append(
        f"Evidence cited: {', '.join(evidence)}." if evidence else "No upstream record is cited."
    )
    if lines:
        parts.append(f"Charge lines cited: {', '.join(lines)}.")
    if trace["next_action"]:
        parts.append(f"Next: {_sentence(trace['next_action'])}")
    return " ".join(parts)

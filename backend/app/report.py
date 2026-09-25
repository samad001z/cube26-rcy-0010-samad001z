"""Plain-text rendering of decisions for the CLI. Formatting only; no decisions here."""

from collections import Counter
from decimal import Decimal

from app.core.rules import ChannelRules, FilingWindowRule, RuleValue
from app.models.decision import DecisionRecord
from app.models.vocab import Decision


def _short(h: str) -> str:
    return f"sha256:{h[:12]}"


def render_decision(d: DecisionRecord) -> list[str]:
    s = d.subject
    amount = f"{d.amount_charged} {d.currency}"
    claim = f"  claim {d.claim.amount} {d.claim.currency}" if d.claim else ""
    lines = [
        f"{s.line_id}  {s.charge_type.value}  {amount}  ->  {d.decision.value} "
        f"({d.evidence_status.value})  {d.rule_id}"
        + (f" [{d.reason_code.value}]" if d.reason_code else "")
        + f"  routing confidence {d.confidence}{claim}"
        + ("  STATUS PENDING" if d.status.value == "pending" else ""),
        f"  reason:   {d.reason}",
    ]
    if d.citations:
        for c in d.citations:
            keys = f" [{', '.join(c.check_keys)}]" if c.check_keys else ""
            lines.append(f"  evidence: {c.kind} {c.id} ({_short(c.content_hash)}) {c.role}{keys}")
    else:
        lines.append("  evidence: none cited")
    cited = {c.id for c in d.citations}
    for r in d.evidence_considered:
        if r.record_id not in cited:
            state = "usable, not cited" if r.usable else "not usable"
            lines.append(f"  read:     {r.record_id} ({r.agent}) {state}: {r.reason}")
    lines.append("  checks:   " + " ".join(f"{c.check_key}={c.verdict.value}" for c in d.checks))
    for w in d.warnings:
        lines.append(f"  warning:  {w}")
    if d.claim:
        for step in d.claim.computation:
            lines.append(f"  amount:   {step}")
    if d.next_action:
        lines.append(f"  next:     {d.next_action}")
    lines.append(f"  record:   {d.record_id} ({_short(d.content_hash or '')})")
    return lines


def render_summary(decisions: list[DecisionRecord]) -> list[str]:
    by_decision = Counter(d.decision.value for d in decisions)
    by_rule = Counter(d.rule_id for d in decisions)
    pending = sum(1 for d in decisions if d.status.value == "pending")
    totals: dict[str, Decimal] = {}
    for d in decisions:
        if d.claim:
            cur = d.claim.currency
            totals[cur] = totals.get(cur, Decimal("0.00")) + d.claim.amount
    total_text = ", ".join(f"{amt} {cur}" for cur, amt in sorted(totals.items())) or "0.00"
    lines = [
        f"decisions: {len(decisions)}  "
        + "  ".join(f"{k}={by_decision.get(k.value, 0)}" for k in Decision),
        f"claim total: {total_text}   pending (failed open or invalid citations): {pending}",
        "by rule: " + ", ".join(f"{r}={n}" for r, n in sorted(by_rule.items())),
    ]
    return lines


def rules_status(rules: ChannelRules) -> str:
    values: list[FilingWindowRule | RuleValue] = [
        *rules.filing_windows.values(),
        rules.fulfilment_fee_schedule,
    ]
    sourced = sum(1 for v in values if v.verified)
    return (
        f"channel rules {rules.channel}: {sourced} of {len(values)} values sourced "
        f"({_short(rules.rules_hash)})"
    )

"""Evidence assessment per charge type: what the usable upstream records say about the
charge. Pure; no decisions here (engine/__init__.py maps an assessment to a decision).

Polarity is always relative to what the line asserts (D-016):
  contradicts  the evidence says the line is wrong
  supports     the evidence is consistent with the line
  uncertain    the evidence cannot settle it (UNCERTAIN verdict, pending record, ...)
For a fee, "the line is wrong" favours recovery. For a loss event (lost, damaged, refunded
and not returned) the line is what the seller would be reimbursed for, so "supports"
favours recovery and "contradicts" makes the loss doubtful. The engine maps each case.
"""

from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from app.core.rules import ChannelRules, EngineConfig
from app.models.charge import Charge
from app.models.contract import EvidenceRecord
from app.models.vocab import ChargeType, EvidenceStatus, RecordStatus, Verdict
from app.retrieval import Candidate

Polarity = Literal["contradicts", "supports", "uncertain"]
ONE = Decimal(1)


@dataclass(frozen=True)
class Finding:
    record: EvidenceRecord
    check_keys: tuple[str, ...]
    polarity: Polarity
    detail: str


@dataclass(frozen=True)
class Assessment:
    status: EvidenceStatus
    findings: tuple[Finding, ...]
    detail: str
    # True when no usable record carries anything that can speak to the charge.
    no_relevant: bool = False
    # Share of the charged units the decisive evidence covers (CONTRADICTED only).
    coverage: Decimal | None = None
    scope_note: str | None = None
    # Loss events: the row of config loss_event_outcomes this evidence maps to (D-016).
    outcome: str | None = None


def unit_coverage(charge: Charge, units_covered: int) -> Decimal:
    """Unit-level records each cover one unit; a line may cover several (quantity)."""
    return min(ONE, (Decimal(units_covered) / Decimal(charge.quantity)).quantize(Decimal("0.0001")))


def _verdicts(record: EvidenceRecord, keys: Sequence[str]) -> dict[str, Verdict]:
    return {c.check_key: c.verdict for c in record.checks if c.check_key in keys}


def _fmt(verdicts: dict[str, Verdict]) -> str:
    return ", ".join(f"{k}={v.value}" for k, v in sorted(verdicts.items()))


def _pending(record: EvidenceRecord) -> bool:
    """Only final records can settle a charge; pending or overridden ones are uncertain."""
    return record.status != RecordStatus.FINAL


def assess_inbound_defect(
    charge: Charge, usable: Sequence[EvidenceRecord], cfg: EngineConfig, rules: ChannelRules
) -> Assessment:
    ct_cfg = cfg.charge_types[charge.charge_type]
    category = charge.defect_category
    if category is not None and category not in cfg.inbound_defect_categories:
        return Assessment(
            EvidenceStatus.INSUFFICIENT,
            (),
            f"defect category {category!r} has no mapping to upstream checks "
            "(config/engine.yaml inbound_defect_categories)",
        )
    if category is not None:
        keys = cfg.inbound_defect_categories[category]
        scope_note = f"scope: defect category {category!r} -> {', '.join(keys)}"
    else:
        keys = ct_cfg.scope_checks
        scope_note = "scope: prep/label checks only; the line names no defect category"

    findings: list[Finding] = []
    per_key: dict[str, set[Verdict]] = defaultdict(set)
    for r in usable:
        v = _verdicts(r, keys)
        if not v:
            continue
        for k, verdict in v.items():
            per_key[k].add(Verdict.UNCERTAIN if _pending(r) else verdict)
        if _pending(r) or Verdict.UNCERTAIN in v.values():
            pol: Polarity = "uncertain"
        elif Verdict.FAIL in v.values():
            pol = "supports"
        else:
            pol = "contradicts"
        note = f" (record status {r.status.value})" if _pending(r) else ""
        findings.append(Finding(r, tuple(sorted(v)), pol, f"{r.record_id}: {_fmt(v)}{note}"))

    if not findings:
        return Assessment(
            EvidenceStatus.INSUFFICIENT,
            (),
            f"no usable record carries any of {', '.join(keys)}",
            no_relevant=True,
            scope_note=scope_note,
        )
    fmt = "; ".join(f.detail for f in findings)
    if any({Verdict.PASS, Verdict.FAIL} <= vs for vs in per_key.values()):
        return Assessment(
            EvidenceStatus.CONFLICTING,
            tuple(findings),
            f"records disagree on the same check: {fmt}",
            scope_note=scope_note,
        )
    if any(Verdict.FAIL in vs for vs in per_key.values()):
        return Assessment(
            EvidenceStatus.SUPPORTED,
            tuple(f for f in findings if f.polarity == "supports"),
            f"a prep check in scope failed, consistent with the fee: {fmt}",
            scope_note=scope_note,
        )
    missing = [k for k in keys if k not in per_key] if category is not None else []
    if any(Verdict.UNCERTAIN in vs for vs in per_key.values()) or missing:
        gap = f"; not recorded: {', '.join(missing)}" if missing else ""
        return Assessment(
            EvidenceStatus.INSUFFICIENT,
            tuple(findings),
            f"prep evidence cannot settle the fee: {fmt}{gap}",
            scope_note=scope_note,
        )
    return Assessment(
        EvidenceStatus.CONTRADICTED,
        tuple(findings),
        f"every prep check in scope passed before the fee was posted: {fmt}",
        coverage=unit_coverage(charge, 1),
        scope_note=scope_note,
    )


def assess_weight_tier(
    charge: Charge, usable: Sequence[EvidenceRecord], cfg: EngineConfig, rules: ChannelRules
) -> Assessment:
    keys = cfg.charge_types[charge.charge_type].required_checks
    findings = [
        Finding(r, tuple(sorted(v)), "uncertain", f"{r.record_id}: {_fmt(v)}")
        for r in usable
        if (v := _verdicts(r, keys))
    ]
    if not findings:
        return Assessment(
            EvidenceStatus.INSUFFICIENT,
            (),
            f"no upstream record carries {' or '.join(keys)}, so the weight tier cannot be checked",
            no_relevant=True,
        )
    return Assessment(
        EvidenceStatus.INSUFFICIENT,
        tuple(findings),
        "measurements exist but the fulfilment fee schedule is not sourced in config/rules/, "
        "so the charged tier cannot be compared",
    )


def assess_lost_inbound(
    charge: Charge, usable: Sequence[EvidenceRecord], cfg: EngineConfig, rules: ChannelRules
) -> Assessment:
    """The line asserts the unit was lost inbound. Prep on the shipment is consistent with it
    (supports); a final record of the unit after the loss (a customer return) says the line
    is wrong (contradicts), whatever prep shows."""
    findings: list[Finding] = []
    for r in usable:
        if r.agent == "prep":
            findings.append(
                Finding(
                    r,
                    (),
                    "uncertain" if _pending(r) else "supports",
                    f"{r.record_id}: unit prepared for {r.subject.fba_shipment_id} before the "
                    "loss was posted",
                )
            )
        elif r.agent == "returns":
            findings.append(
                Finding(
                    r,
                    (),
                    "uncertain" if _pending(r) else "contradicts",
                    f"{r.record_id}: unit returned by a customer after the loss was posted",
                )
            )
    if not findings:
        return Assessment(
            EvidenceStatus.INSUFFICIENT,
            (),
            "no prep or later returns record for this unit",
            no_relevant=True,
        )
    pols = {f.polarity for f in findings}
    fmt = "; ".join(f.detail for f in findings)
    if "contradicts" in pols:
        return Assessment(
            EvidenceStatus.CONTRADICTED,
            tuple(findings),
            fmt,
            coverage=ONE,
            outcome="later_sighting",
        )
    if "uncertain" in pols:
        return Assessment(EvidenceStatus.INSUFFICIENT, tuple(findings), fmt)
    return Assessment(
        EvidenceStatus.SUPPORTED, tuple(findings), fmt, outcome="shipped_no_later_sighting"
    )


def assess_damaged_in_warehouse(
    charge: Charge, usable: Sequence[EvidenceRecord], cfg: EngineConfig, rules: ChannelRules
) -> Assessment:
    """The line asserts the unit was damaged in the warehouse. Prep recording the unit leave
    with no failed check is consistent with it (supports); a failed prep check means it may
    have arrived damaged, which cannot settle the line (uncertain)."""
    findings: list[Finding] = []
    for r in usable:
        fails = [c.check_key for c in r.checks if c.verdict == Verdict.FAIL]
        if _pending(r) or fails:
            detail = f"{r.record_id}: prep recorded {', '.join(fails) or 'pending review'}"
            findings.append(Finding(r, tuple(sorted(fails)), "uncertain", detail))
        else:
            findings.append(
                Finding(
                    r,
                    tuple(sorted(c.check_key for c in r.checks)),
                    "supports",
                    f"{r.record_id}: unit left prep with no failed check",
                )
            )
    return _combine(
        findings, "no prep record for this unit on this shipment", supports="left_prep_undamaged"
    )


def assess_refund_not_returned(
    charge: Charge, usable: Sequence[EvidenceRecord], cfg: EngineConfig, rules: ChannelRules
) -> Assessment:
    """The line asserts a refund was issued and the item was not returned. The ordered item
    coming back says the line is wrong (contradicts); a different item coming back is
    consistent with it (supports). The item counts as returned complete only when identity,
    parts and condition all PASS; anything else is returned incomplete or damaged."""
    findings: list[Finding] = []
    complete: list[bool] = []
    for r in usable:
        v = {c.check_key: c.verdict for c in r.checks}
        cond = _fmt(v)
        identity = v.get("identity_match")
        if _pending(r) or identity in (None, Verdict.UNCERTAIN):
            findings.append(Finding(r, tuple(sorted(v)), "uncertain", f"{r.record_id}: {cond}"))
        elif identity == Verdict.FAIL:
            findings.append(
                Finding(
                    r,
                    ("identity_match",),
                    "supports",
                    f"{r.record_id}: a different item came back ({cond})",
                )
            )
        else:
            whole = all(
                v.get(k) == Verdict.PASS for k in ("parts_complete", "returned_item_condition")
            )
            complete.append(whole)
            state = "complete" if whole else "incomplete, damaged or condition uncertain"
            findings.append(
                Finding(
                    r,
                    tuple(sorted(v)),
                    "contradicts",
                    f"{r.record_id}: the ordered item was returned, {state} ({cond})",
                )
            )
    return _combine(
        findings,
        "no returns record for this order",
        contradicts="returned_complete" if all(complete) else "returned_incomplete_or_damaged",
        supports="wrong_item_returned",
    )


def _combine(
    findings: list[Finding],
    none_text: str,
    *,
    contradicts: str | None = None,
    supports: str | None = None,
) -> Assessment:
    """Loss events: one polarity across all findings settles the line; the outcome labels
    name the row of config loss_event_outcomes that applies."""
    if not findings:
        return Assessment(EvidenceStatus.INSUFFICIENT, (), none_text, no_relevant=True)
    pols = {f.polarity for f in findings}
    fmt = "; ".join(f.detail for f in findings)
    if {"contradicts", "supports"} <= pols:
        return Assessment(EvidenceStatus.CONFLICTING, tuple(findings), fmt)
    if pols == {"contradicts"}:
        return Assessment(
            EvidenceStatus.CONTRADICTED, tuple(findings), fmt, coverage=ONE, outcome=contradicts
        )
    if pols == {"supports"}:
        return Assessment(EvidenceStatus.SUPPORTED, tuple(findings), fmt, outcome=supports)
    return Assessment(EvidenceStatus.INSUFFICIENT, tuple(findings), fmt)


Assessor = Callable[[Charge, Sequence[EvidenceRecord], EngineConfig, ChannelRules], Assessment]

ASSESSORS: dict[ChargeType, Assessor] = {
    ChargeType.INBOUND_DEFECT_FEE: assess_inbound_defect,
    ChargeType.FULFILMENT_FEE_WEIGHT_TIER: assess_weight_tier,
    ChargeType.LOST_INBOUND: assess_lost_inbound,
    ChargeType.DAMAGED_IN_WAREHOUSE: assess_damaged_in_warehouse,
    ChargeType.REFUND_ISSUED_ITEM_NOT_RETURNED: assess_refund_not_returned,
}


def assess(
    charge: Charge, candidates: Sequence[Candidate], cfg: EngineConfig, rules: ChannelRules
) -> Assessment:
    usable = [c.record for c in candidates if c.usable]
    return ASSESSORS[charge.charge_type](charge, usable, cfg, rules)

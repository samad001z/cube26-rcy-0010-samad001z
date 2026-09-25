"""Deterministic rule engine: one charge in, one decision record out. Pure; no I/O and no
model calls. Decisions, amounts and citations are set here and nowhere else.

Rules are evaluated in order; the first that matches fires. Each rule names the check its
decision rests on, and the decision's confidence is that check's confidence.

  #   rule_id                    when                                          decision
  1   R_FILING_WINDOW_NOT_OPEN   sourced window has not opened yet (D-017)     REVIEW
  2   R_FEE_REFUND_LINE          reimbursement line on a fee type              DO_NOT_CLAIM
  3   R_ZERO_FEE                 fee line of 0.00                              DO_NOT_CLAIM
  4   R_REIMBURSEMENT_AMBIGUOUS  a refund could belong to this or another fee  REVIEW
  5   R_DUPLICATE                duplicate of an earlier fee line              CLAIM
  6   R_ALREADY_REIMBURSED       reimbursed >= charged                         DO_NOT_CLAIM
  7   R_UNRESOLVED_UNIT          unit resolution failed                        REVIEW
  8   R_EVIDENCE_OUTSIDE_WINDOW  in-scope records, none in custody window      REVIEW
  9   R_NO_RELEVANT_EVIDENCE     nothing can speak to the charge               REVIEW
  Loss events only (D-016), never CLAIM:
  10  R_FILING_WINDOW_PASSED     sourced deadline has passed                   DO_NOT_CLAIM
  11  R_CONFLICTING              records disagree                              REVIEW
  12  R_INSUFFICIENT             evidence cannot settle it                     REVIEW
  13  (config row)               loss_event_outcomes[type][outcome]            REVIEW/DO_NOT_CLAIM
        R_AMOUNT_NOT_COMPUTABLE, R_ITEM_RETURNED, R_RETURNED_INCOMPLETE_OR_DAMAGED,
        R_LOSS_DOUBTFUL (see config/engine.yaml)
  Fees only:
  14  R_CONFLICTING              records disagree                              REVIEW
  15  R_SUPPORTED                evidence supports the charge                  DO_NOT_CLAIM
  16  R_INSUFFICIENT             evidence cannot settle it                     REVIEW
  17  R_AMOUNT_NOT_COMPUTABLE    fee whose amount needs an unsourced rule      REVIEW
  18  R_PARTIAL_COVERAGE         contradicted for some of the units            REVIEW
  19  R_DEFECT_CATEGORY_MISSING  inbound defect fee names no category          REVIEW
  20  R_FILING_WINDOW_PASSED     sourced deadline has passed                   DO_NOT_CLAIM
  21  R_CONTRADICTED_FULL        contradicted for every unit                   CLAIM

A window that has not opened (rule 1) is REVIEW, never CLAIM or DO_NOT_CLAIM (D-017). A
duplicate (rule 5) is still subject to rule 6 and the deadline: fully reimbursed -> rule 6;
a passed deadline -> DO_NOT_CLAIM with FILING_WINDOW_EXPIRED (D-015a). An unverified
deadline never blocks a CLAIM; it adds the warning "filing deadline not verified" (D-014).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.claims import compute_full_amount_claim
from app.core.rules import ChannelRules, EngineConfig, LossEventMapping
from app.engine.assess import Assessment, assess
from app.models.charge import Charge
from app.models.contract import Check, Outcome
from app.models.decision import (
    Citation,
    Claim,
    ConsideredRecord,
    DecisionRecord,
    DecisionSubject,
)
from app.models.vocab import ChargeType, Decision, EvidenceStatus, ReasonCode, RecordStatus, Verdict
from app.precheck import FILING_NOT_VERIFIED, Precheck, is_fee_refund_line
from app.resolution import Resolution
from app.retrieval import Candidate

ENGINE_VERSION = "0.3.0"
DECIDED_BY = f"rules@{ENGINE_VERSION}"
ZERO = Decimal("0.00")

NEXT_CONFIRM_CATEGORY = (
    "Confirm the defect type for this fee in Seller Central; if it is one of the prep/label "
    "categories shown as passed here, override to CLAIM with the defect type as the reason."
)
NEXT_UNIT_VALUE = (
    "Find the channel's reimbursement valuation for this unit (or an authoritative unit "
    "value) and the claim window, then decide and record an override with the amount."
)


@dataclass(frozen=True)
class Fired:
    rule_id: str
    decision: Decision
    reason_code: ReasonCode | None
    key_check: str
    reason: str
    next_action: str | None = None


def _check(key: str, verdict: Verdict, confidence: Decimal, detail: str) -> Check:
    return Check(check_key=key, verdict=verdict, confidence=confidence, detail=detail)


def _evidence_checks(
    charge: Charge,
    resolution: Resolution,
    candidates: Sequence[Candidate],
    a: Assessment,
    cfg: EngineConfig,
) -> list[Check]:
    exact, operator = cfg.confidence.exact, cfg.confidence.operator_check
    in_scope = [c for c in candidates if c.in_scope]
    out_window = [c for c in in_scope if not c.in_window]

    present = _check(
        "evidence_present",
        Verdict.FAIL if a.no_relevant else Verdict.PASS,
        exact,
        f"{len(a.findings)} usable record(s) speak to the charge" if a.findings else a.detail,
    )
    if not resolution.resolved or not in_scope:
        window = _check(
            "evidence_in_custody_window",
            Verdict.UNCERTAIN,
            exact,
            "no relevant evidence to check (no in-scope upstream record)"
            if a.no_relevant
            else "not applicable: no in-scope upstream record",
        )
    elif len(out_window) == len(in_scope):
        window = _check(
            "evidence_in_custody_window",
            Verdict.FAIL,
            exact,
            "; ".join(c.reason for c in out_window),
        )
    elif a.no_relevant:
        # Records inside the window exist but none speaks to the charge: nothing to place.
        window = _check(
            "evidence_in_custody_window",
            Verdict.UNCERTAIN,
            exact,
            "no relevant evidence to check",
        )
    else:
        skipped = f"; outside window: {', '.join(c.record.record_id for c in out_window)}"
        window = _check(
            "evidence_in_custody_window",
            Verdict.PASS,
            exact,
            f"{len(in_scope) - len(out_window)} in-scope record(s) inside the custody window"
            + (skipped if out_window else ""),
        )

    if a.no_relevant or not resolution.resolved:
        contra = _check("evidence_contradicts_charge", Verdict.UNCERTAIN, exact, a.detail)
    elif a.status == EvidenceStatus.CONTRADICTED:
        cov = a.coverage if a.coverage is not None else Decimal(1)
        contra = _check(
            "evidence_contradicts_charge",
            Verdict.PASS,
            (operator * cov).quantize(Decimal("0.01")),
            a.detail + (f" [{a.scope_note}]" if a.scope_note else "") + f" (coverage {cov})",
        )
    elif a.status == EvidenceStatus.SUPPORTED:
        contra = _check("evidence_contradicts_charge", Verdict.FAIL, operator, a.detail)
    else:
        contra = _check(
            "evidence_contradicts_charge",
            Verdict.UNCERTAIN,
            operator,
            f"{a.status.value}: {a.detail}",
        )
    return [present, window, contra]


def _reimbursed_check(charge: Charge, pre: Precheck, cfg: EngineConfig) -> Check:
    exact = cfg.confidence.exact
    reimbursed = pre.reimbursed_amount
    if is_fee_refund_line(charge, cfg):
        return _check(
            "not_already_reimbursed", Verdict.FAIL, exact, "this line is itself a reimbursement"
        )
    if pre.ambiguous_reimbursements:
        ids = ", ".join(r.line_id for r in pre.ambiguous_reimbursements)
        return _check(
            "not_already_reimbursed",
            Verdict.UNCERTAIN,
            exact,
            f"refund line(s) {ids} could belong to this fee or to another one on the same unit",
        )
    if pre.reimbursements:
        ids = ", ".join(r.line_id for r in pre.reimbursements)
        full = charge.amount > ZERO and reimbursed >= charge.amount
        return _check(
            "not_already_reimbursed",
            Verdict.FAIL if full else Verdict.PASS,
            exact,
            f"reimbursed {reimbursed} {charge.currency} of {charge.amount} via {ids}",
        )
    return _check("not_already_reimbursed", Verdict.PASS, exact, "no matching reimbursement line")


def _amount_check(
    charge: Charge, cfg: EngineConfig, rules: ChannelRules
) -> tuple[Check, str | None]:
    """(check, reason if not computable)."""
    exact = cfg.confidence.exact
    basis = cfg.charge_types[charge.charge_type].claim_basis
    if basis == "full_amount":
        return (
            _check(
                "amount_computable",
                Verdict.PASS,
                exact,
                f"full fee {charge.amount} {charge.currency}",
            ),
            None,
        )
    if basis == "fee_difference" and rules.fulfilment_fee_schedule.verified:
        # A sourced schedule exists but tier computation needs measured weight/dimensions,
        # which no upstream record carries. Kept explicit rather than silently computed.
        why = "fee schedule is sourced but no measurement exists to place the unit in a tier"
    elif basis == "fee_difference":
        why = (
            "recoverable = fee charged - correct fee, and the fulfilment fee schedule is not "
            "sourced in config/rules/"
        )
    else:
        why = (
            f"{charge.amount} {charge.currency} is the reimbursement already paid; what is owed "
            "needs an authoritative unit value, which no upstream record provides (D-011)"
        )
    return _check("amount_computable", Verdict.FAIL, exact, why), why


def _fire(
    charge: Charge,
    pre: Precheck,
    resolution: Resolution,
    candidates: Sequence[Candidate],
    a: Assessment,
    amount_why: str | None,
    cfg: EngineConfig,
) -> Fired:
    kind = cfg.charge_types[charge.charge_type].kind
    if pre.filing.state == "not_open":
        assert pre.filing.opens is not None
        return Fired(
            "R_FILING_WINDOW_NOT_OPEN",
            Decision.REVIEW,
            ReasonCode.FILING_WINDOW_NOT_OPEN,
            "within_filing_window",
            "the filing window has not opened yet, so this can be neither claimed nor "
            f"dismissed ({pre.filing.proxy_note}): {pre.filing.detail}.",
            f"Re-run on or after {pre.filing.opens}, when the filing window opens.",
        )
    if is_fee_refund_line(charge, cfg):
        return Fired(
            "R_FEE_REFUND_LINE",
            Decision.DO_NOT_CLAIM,
            None,
            "not_already_reimbursed",
            f"{charge.line_id} is a reimbursement of {charge.amount} {charge.currency} "
            "credited to the seller, not a charge; it offsets the matching fee.",
        )
    if kind == "fee" and charge.amount == ZERO:
        return Fired(
            "R_ZERO_FEE",
            Decision.DO_NOT_CLAIM,
            None,
            "amount_computable",
            f"fee of 0.00 {charge.currency}: nothing was charged, so nothing is recoverable "
            "from this line (D-011).",
        )
    if pre.ambiguous_reimbursements:
        ids = ", ".join(r.line_id for r in pre.ambiguous_reimbursements)
        return Fired(
            "R_REIMBURSEMENT_AMBIGUOUS",
            Decision.REVIEW,
            None,
            "not_already_reimbursed",
            f"refund line(s) {ids} could belong to this fee or to another fee on the same unit, "
            "so what is already reimbursed cannot be computed.",
            "Match the refund to its fee (e.g. by reimbursement or case id in Seller Central), "
            "then decide by override.",
        )
    cap = charge.amount - pre.reimbursed_amount
    if pre.duplicate_of is not None and cap > ZERO:
        c = pre.duplicate_of
        if pre.filing.state == "passed":
            return Fired(
                "R_FILING_WINDOW_PASSED",
                Decision.DO_NOT_CLAIM,
                ReasonCode.FILING_WINDOW_EXPIRED,
                "within_filing_window",
                f"duplicate of {c.line_id}, but the filing window has passed, so it can no "
                f"longer be claimed: {pre.filing.detail}.",
            )
        return Fired(
            "R_DUPLICATE",
            Decision.CLAIM,
            ReasonCode.DUPLICATE_CHARGE,
            "not_duplicate",
            f"duplicate of {c.line_id} (same unit, type, shipment, order, quantity and "
            f"amount, posted {c.posted_date}); the earlier line is the valid one.",
        )
    if charge.amount > ZERO and cap <= ZERO:
        ids = ", ".join(r.line_id for r in pre.reimbursements)
        return Fired(
            "R_ALREADY_REIMBURSED",
            Decision.DO_NOT_CLAIM,
            ReasonCode.ALREADY_REIMBURSED,
            "not_already_reimbursed",
            f"already reimbursed {pre.reimbursed_amount} {charge.currency} ({ids}) against "
            f"a charge of {charge.amount}.",
        )
    if not resolution.resolved:
        return Fired(
            "R_UNRESOLVED_UNIT",
            Decision.REVIEW,
            ReasonCode.UNRESOLVED_UNIT,
            "unit_resolved",
            f"unit could not be resolved: {resolution.failure}.",
            "Check the unit_id and keys on the report line against the upstream records.",
        )
    in_scope = [c for c in candidates if c.in_scope]
    if in_scope and not any(c.in_window for c in in_scope):
        return Fired(
            "R_EVIDENCE_OUTSIDE_WINDOW",
            Decision.REVIEW,
            ReasonCode.EVIDENCE_OUTSIDE_WINDOW,
            "evidence_in_custody_window",
            "upstream records exist for this unit but none was captured inside the custody "
            "window: " + "; ".join(c.reason for c in in_scope) + ".",
            "Find evidence captured inside the custody window, or review manually.",
        )
    loss = cfg.loss_event_outcomes.get(charge.charge_type) if kind == "loss_event" else None
    if a.no_relevant:
        note = f"; {loss.no_evidence}" if loss is not None and loss.no_evidence else ""
        return Fired(
            "R_NO_RELEVANT_EVIDENCE",
            Decision.REVIEW,
            ReasonCode.NO_RELEVANT_EVIDENCE,
            "evidence_present",
            f"no upstream evidence speaks to this charge: {a.detail}{note}.",
            _no_evidence_action(charge, cfg),
        )
    if loss is not None:
        return _fire_loss_event(pre, a, loss)
    if a.status == EvidenceStatus.CONFLICTING:
        return Fired(
            "R_CONFLICTING",
            Decision.REVIEW,
            None,
            "evidence_contradicts_charge",
            f"upstream evidence conflicts: {a.detail}.",
            "Inspect the conflicting records and their photos, then decide.",
        )
    if a.status == EvidenceStatus.SUPPORTED:
        return Fired(
            "R_SUPPORTED",
            Decision.DO_NOT_CLAIM,
            None,
            "evidence_contradicts_charge",
            f"upstream evidence supports the charge: {a.detail}.",
        )
    if a.status == EvidenceStatus.INSUFFICIENT:
        return Fired(
            "R_INSUFFICIENT",
            Decision.REVIEW,
            None,
            "evidence_contradicts_charge",
            f"evidence is insufficient: {a.detail}.",
            "Check the uncertain items (photos, operator notes) and decide.",
        )
    if amount_why is not None:
        return Fired(
            "R_AMOUNT_NOT_COMPUTABLE",
            Decision.REVIEW,
            None,
            "amount_computable",
            f"evidence contradicts the charge ({a.detail}); but no claim amount can be "
            f"computed: {amount_why}.",
            "Source the missing channel rule in config/rules/, then re-run.",
        )
    assert a.status == EvidenceStatus.CONTRADICTED
    if a.coverage is None or a.coverage < Decimal(1):
        return Fired(
            "R_PARTIAL_COVERAGE",
            Decision.REVIEW,
            None,
            "evidence_contradicts_charge",
            f"evidence contradicts the charge for only part of it (coverage {a.coverage} of "
            f"quantity {charge.quantity}): {a.detail}.",
            "Find evidence for the remaining units, or claim the covered part by override.",
        )
    if charge.charge_type == ChargeType.INBOUND_DEFECT_FEE and charge.defect_category is None:
        return Fired(
            "R_DEFECT_CATEGORY_MISSING",
            Decision.REVIEW,
            None,
            "evidence_contradicts_charge",
            f"{a.detail}; but the line names no defect category, so the evidence cannot be "
            "shown to cover the defect charged.",
            NEXT_CONFIRM_CATEGORY,
        )
    if pre.filing.state == "passed":
        return Fired(
            "R_FILING_WINDOW_PASSED",
            Decision.DO_NOT_CLAIM,
            ReasonCode.FILING_WINDOW_EXPIRED,
            "within_filing_window",
            f"evidence contradicts the charge, but the filing window has passed, so it can no "
            f"longer be claimed: {pre.filing.detail}.",
        )
    return Fired(
        "R_CONTRADICTED_FULL",
        Decision.CLAIM,
        None,
        "evidence_contradicts_charge",
        f"upstream evidence contradicts the charge: {a.detail}"
        + (f" [{a.scope_note}]" if a.scope_note else "")
        + ".",
    )


def _fire_loss_event(pre: Precheck, a: Assessment, loss: LossEventMapping) -> Fired:
    """Loss events (D-016): a passed sourced deadline, then generic INSUFFICIENT/CONFLICTING,
    then the per-charge-type row of config loss_event_outcomes. Never CLAIM (D-011)."""
    if pre.filing.state == "passed":
        return Fired(
            "R_FILING_WINDOW_PASSED",
            Decision.DO_NOT_CLAIM,
            ReasonCode.FILING_WINDOW_EXPIRED,
            "within_filing_window",
            f"evidence is {a.status.value} ({a.detail}); but the filing deadline has passed, "
            f"{pre.filing.proxy_note}: {pre.filing.detail}.",
        )
    if a.status == EvidenceStatus.CONFLICTING:
        return Fired(
            "R_CONFLICTING",
            Decision.REVIEW,
            None,
            "evidence_contradicts_charge",
            f"upstream evidence conflicts: {a.detail}.",
            "Inspect the conflicting records and their photos, then decide.",
        )
    if a.status == EvidenceStatus.INSUFFICIENT:
        return Fired(
            "R_INSUFFICIENT",
            Decision.REVIEW,
            None,
            "evidence_contradicts_charge",
            f"evidence is insufficient: {a.detail}.",
            "Check the uncertain items (photos, operator notes) and decide.",
        )
    row = loss.outcomes.get(a.outcome or "")
    if row is None or row.evidence_status != a.status.value:
        raise ValueError(f"no loss_event_outcomes row {a.outcome!r} for evidence {a.status.value}")
    if row.amount_needed:
        why = (
            "what is owed needs an authoritative unit value, which no upstream record "
            "provides (D-011)"
        )
        return Fired(
            row.rule_id,
            Decision.REVIEW,
            None,
            "amount_computable",
            f"{row.reason} ({a.detail}); but no claim amount can be computed: {why}.",
            NEXT_UNIT_VALUE,
        )
    return Fired(
        row.rule_id,
        Decision(row.decision),
        None,
        "evidence_contradicts_charge",
        f"{row.reason}: {a.detail}.",
        row.next_action,
    )


def _no_evidence_action(charge: Charge, cfg: EngineConfig) -> str:
    required = cfg.charge_types[charge.charge_type].required_checks
    if required:
        return f"Record {', '.join(required)} for this unit, or review manually."
    return "Find upstream evidence for this unit, or review manually."


def _citations(charge: Charge, pre: Precheck, a: Assessment, fired: Fired) -> list[Citation]:
    out: list[Citation] = []
    dup = pre.duplicate_of
    if dup is not None:  # the earlier line is the evidence that this one is a duplicate
        out.append(
            Citation(
                kind="charge",
                id=dup.line_id,
                content_hash=dup.compute_hash(),
                role="canonical_charge",
            )
        )
    for r in (*pre.reimbursements, *pre.ambiguous_reimbursements):
        out.append(
            Citation(
                kind="charge", id=r.line_id, content_hash=r.compute_hash(), role="reimbursement"
            )
        )
    for f in a.findings:
        assert f.record.content_hash is not None
        out.append(
            Citation(
                kind="evidence",
                id=f.record.record_id,
                content_hash=f.record.content_hash,
                role=f.polarity,
                check_keys=list(f.check_keys),
            )
        )
    return out


def decide(
    charge: Charge,
    pre: Precheck,
    resolution: Resolution,
    candidates: Sequence[Candidate],
    rules: ChannelRules,
    cfg: EngineConfig,
    *,
    run_id: str,
    decided_at: datetime,
) -> DecisionRecord:
    exact = cfg.confidence.exact
    a = (
        assess(charge, candidates, cfg, rules)
        if resolution.resolved
        else Assessment(EvidenceStatus.INSUFFICIENT, (), resolution.failure or "unit not resolved")
    )
    amount_check, amount_why = _amount_check(charge, cfg, rules)

    dup = pre.duplicate_of
    reimbursed = pre.reimbursed_amount
    checks = [
        _check(
            "unit_resolved",
            Verdict.PASS if resolution.resolved else Verdict.FAIL,
            exact,
            f"{charge.unit_id} found in {len(resolution.records)} upstream record(s)"
            + (f"; {'; '.join(resolution.notes)}" if resolution.notes else "")
            if resolution.resolved
            else resolution.failure or "",
        ),
        _check(
            "not_duplicate",
            Verdict.FAIL if dup else Verdict.PASS,
            exact,
            f"same fingerprint as {dup.line_id} posted {dup.posted_date}"
            if dup
            else "no earlier line with the same fingerprint",
        ),
        _reimbursed_check(charge, pre, cfg),
        _check("within_filing_window", pre.filing.verdict, exact, pre.filing.detail),
        *_evidence_checks(charge, resolution, candidates, a, cfg),
        amount_check,
    ]
    fired = _fire(charge, pre, resolution, candidates, a, amount_why, cfg)

    warnings: list[str] = []
    if pre.filing.verdict == Verdict.UNCERTAIN:
        warnings.append(FILING_NOT_VERIFIED)
    reason = fired.reason
    if fired.decision == Decision.CLAIM and pre.filing.verdict == Verdict.UNCERTAIN:
        reason += f" Warning: {FILING_NOT_VERIFIED}."

    claim: Claim | None = None
    if fired.decision == Decision.CLAIM:
        coverage = Decimal(1) if fired.rule_id == "R_DUPLICATE" else (a.coverage or ZERO)
        claim = compute_full_amount_claim(
            charge, coverage, reimbursed, [r.line_id for r in pre.reimbursements]
        )
        if claim is None:  # defensive: an empty claim is never a CLAIM
            fired = Fired(
                "R_AMOUNT_NOT_COMPUTABLE",
                Decision.REVIEW,
                fired.reason_code,
                "amount_computable",
                reason + " Computed claim amount is zero.",
                "Review the amounts.",
            )
            reason = fired.reason

    key = next(c for c in checks if c.check_key == fired.key_check)
    assert key.confidence is not None
    considered = [
        ConsideredRecord(
            record_id=c.record.record_id,
            agent=c.record.agent,
            content_hash=c.record.content_hash or "",
            usable=c.usable,
            reason=c.reason,
        )
        for c in candidates
    ]
    record = DecisionRecord(
        record_id=f"DEC-{run_id}-{charge.line_id}",
        organization_id=charge.organization_id,
        client_id=charge.organization_id,
        subject=DecisionSubject(
            line_id=charge.line_id,
            unit_id=charge.unit_id,
            charge_type=charge.charge_type,
            report_type=charge.report_type,
            fba_shipment_id=charge.fba_shipment_id,
            order_id=charge.order_id,
            defect_category=charge.defect_category,
            charge_content_hash=charge.compute_hash(),
        ),
        captured_at=decided_at,
        checks=checks,
        outcome=Outcome(
            decision=fired.decision.value, decided_by=DECIDED_BY, decided_at=decided_at
        ),
        status=RecordStatus.FINAL,
        run_id=run_id,
        decision=fired.decision,
        evidence_status=a.status,
        reason_code=fired.reason_code,
        rule_id=fired.rule_id,
        rule_path=[fired.rule_id],
        reason=reason,
        warnings=warnings,
        next_action=fired.next_action,
        confidence=key.confidence,
        coverage=a.coverage,
        amount_charged=charge.amount,
        amount_reimbursed=reimbursed,
        currency=charge.currency,
        claim=claim,
        citations=_citations(charge, pre, a, fired),
        evidence_considered=considered,
        resolved_unit=resolution.unit_id,
        engine_version=ENGINE_VERSION,
        rules_hash=rules.rules_hash,
        config_hash=cfg.config_hash,
    )
    return record.with_hash()

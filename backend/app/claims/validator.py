"""Citation validator. Runs on every decision after the engine, against data re-read from
the store (not the objects the engine used), and fails closed:

- every cited evidence record exists for this organisation, its stored hash equals the
  cited hash, the body re-hashes to the same value, and every cited check_key exists on it;
- evidence cited as contradicting or supporting the charge lies inside its custody window;
- every cited charge line exists and re-hashes to the cited hash; so does the decided charge;
- the reimbursed amount is no more than the cited refund lines add up to in the store;
- a CLAIM has a positive amount no greater than charged - reimbursed, and cites at least one
  contradicting record or a canonical duplicate; a non-CLAIM carries no claim amount;
- the decision's own content hash verifies.

On any failure the decision becomes REVIEW with status pending and rule R_CITATION_INVALID.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from app.core.rules import EngineConfig
from app.models.charge import Charge
from app.models.contract import EvidenceRecord
from app.models.decision import DecisionRecord
from app.models.vocab import Decision, RecordStatus
from app.retrieval import in_custody_window, in_scope

RULE_ID = "R_CITATION_INVALID"


@dataclass(frozen=True)
class StoredRecord:
    record: EvidenceRecord
    stored_hash: str  # the content_hash column, written at ingestion


class Lookup(Protocol):
    def evidence(self, record_id: str) -> StoredRecord | None: ...

    def charge(self, line_id: str) -> Charge | None: ...


def validate(
    decision: DecisionRecord, charge: Charge, lookup: Lookup, cfg: EngineConfig
) -> list[str]:
    errors: list[str] = []
    org = decision.organization_id
    if charge.organization_id != org:
        errors.append("charge belongs to another organisation")
    if decision.subject.charge_content_hash != charge.compute_hash():
        errors.append(f"charge {charge.line_id} hash does not match the decision subject")
    stored_charge = lookup.charge(charge.line_id)
    if stored_charge is None or stored_charge.compute_hash() != charge.compute_hash():
        errors.append(f"charge {charge.line_id} not found in the store or changed")

    refunded = Decimal("0.00")
    for cite in decision.citations:
        if cite.kind == "evidence":
            stored = lookup.evidence(cite.id)
            if stored is None:
                errors.append(f"cited record {cite.id} not found")
                continue
            rec = stored.record
            if rec.organization_id != org:
                errors.append(f"cited record {cite.id} belongs to another organisation")
            if not (stored.stored_hash == cite.content_hash == rec.content_hash):
                errors.append(f"cited record {cite.id} hash mismatch")
            elif not rec.verify_hash():
                errors.append(f"cited record {cite.id} body does not match its hash")
            missing = set(cite.check_keys) - {c.check_key for c in rec.checks}
            if missing:
                errors.append(f"cited record {cite.id} has no check {sorted(missing)}")
            if cite.role in ("contradicts", "supports"):
                if not in_scope(charge, rec, cfg):
                    errors.append(f"cited record {cite.id} is out of scope for the charge")
                if not in_custody_window(charge, rec, cfg):
                    errors.append(f"cited record {cite.id} is outside the custody window")
        else:
            other = lookup.charge(cite.id)
            if other is None:
                errors.append(f"cited charge {cite.id} not found")
            elif other.organization_id != org or other.compute_hash() != cite.content_hash:
                errors.append(f"cited charge {cite.id} hash mismatch")
            elif cite.role == "reimbursement":
                refunded += other.amount

    # The reimbursed amount must be backed by the refund lines cited, read from the store.
    if decision.amount_reimbursed > refunded:
        errors.append(
            f"amount_reimbursed {decision.amount_reimbursed} exceeds the cited refund lines "
            f"({refunded})"
        )

    claim = decision.claim
    if decision.decision == Decision.CLAIM:
        cap = charge.amount - decision.amount_reimbursed
        if claim is None:
            errors.append("CLAIM without an amount")
        else:
            if not isinstance(claim.amount, Decimal) or claim.amount <= 0:
                errors.append(f"claim amount {claim.amount} is not positive")
            if claim.amount > cap:
                errors.append(f"claim {claim.amount} exceeds charged - reimbursed = {cap}")
        if not any(c.role in ("contradicts", "canonical_charge") for c in decision.citations):
            errors.append("CLAIM cites no contradicting evidence or canonical charge")
        if cfg.charge_types[charge.charge_type].kind == "loss_event":
            errors.append("a loss event is never CLAIM (D-011, D-016)")
    elif claim is not None:
        errors.append(f"{decision.decision.value} carries a claim amount")

    if not decision.verify_hash():
        errors.append("decision content hash does not verify")
    return errors


def enforce(decision: DecisionRecord, errors: list[str]) -> DecisionRecord:
    """Return the decision unchanged if valid, else the fail-closed REVIEW version."""
    if not errors:
        return decision
    reason = "citation validation failed: " + "; ".join(errors) + f". Original: {decision.reason}"
    downgraded = decision.model_copy(
        update={
            "decision": Decision.REVIEW,
            "status": RecordStatus.PENDING,
            "rule_id": RULE_ID,
            "rule_path": [*decision.rule_path, RULE_ID],
            "reason": reason,
            "claim": None,
            "next_action": "Re-ingest or inspect the cited records, then re-run.",
            "outcome": decision.outcome.model_copy(update={"decision": Decision.REVIEW.value}),
            "content_hash": None,
        }
    )
    return downgraded.with_hash()

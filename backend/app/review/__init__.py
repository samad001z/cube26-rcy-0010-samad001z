"""Human review of decisions: overrides and the effective decision (D-021).

An override is data (CLAUDE.md rule 11). It is written to its own append-only table and
never changes the decision row it points at, whose content hash therefore still verifies.
The effective decision of a record is the newest override's new decision, or the engine's
decision when there is none. The effective record is the engine record with `overrides`
filled, `status: overridden`, `outcome.decided_by: human:<reviewer>`, the new decision and,
for a CLAIM, a claim amount; it gets its own content hash.

Each override stores the content hash of the engine record and of the previous override
(a hash chain, checked at application level). Rules that keep money honest:

- Only the newest decision of a charge line can be overridden. Older runs are history; their
  reimbursement figures may be out of date.
- A human CLAIM claims the remaining charge: amount charged minus amount already
  reimbursed, as the engine's pre-check computed it (rule 9). If nothing remains, the
  override is refused.
- A human CLAIM is refused when the engine could not establish what is owed or whether it
  can be filed: a pending (fail-open) record, a loss event (its amount is what was already
  paid, D-011), a fee refund line, a filing window that is closed or not yet open, or a
  reimbursement check that is not PASS (fully reimbursed, or a refund that could belong to
  more than one fee).
- The would-be CLAIM record then goes through the same citation validator as the engine's
  CLAIMs, re-reading the charge and cited refund lines from the store. The only check left
  out is "cites contradicting evidence": the reviewer's reason stands in for it.
- An override must change the effective decision; a no-op is refused.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.claims.validator import validate
from app.core.hashing import content_hash
from app.core.rules import EngineConfig, load_engine_config
from app.db import repo
from app.models.contract import Check, Outcome, Override
from app.models.decision import Claim, DecisionRecord
from app.models.vocab import Decision, RecordStatus, ReportType, Verdict
from app.pipeline import DbLookup

ZERO = Decimal("0.00")
HUMAN_PREFIX = "human:"

Reviewer = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._@-]{0,63}$")
]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)]


class OverrideError(ValueError):
    """The override was refused. `status` is the HTTP status the API answers with."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


class OverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_decision: Decision
    reason: Reason
    reviewer: Reviewer


class OverrideRecord(BaseModel):
    """One stored override. `override` is the contract's Override shape."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision_record_id: str
    line_id: str
    sequence: int = Field(ge=1)
    override: Override
    claim: Claim | None
    engine_record_hash: str
    previous_override_hash: str | None
    content_hash: str | None = None

    @field_validator("claim")
    @classmethod
    def _positive(cls, v: Claim | None) -> Claim | None:
        if v is not None and v.amount <= ZERO:
            raise ValueError("an override claim must be positive")
        return v

    def _hash_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="python", exclude={"content_hash"})

    def compute_hash(self) -> str:
        return content_hash(self._hash_payload())

    def with_hash(self) -> Self:
        return self.model_copy(update={"content_hash": self.compute_hash()})

    def verify_hash(self) -> bool:
        return self.content_hash is not None and self.content_hash == self.compute_hash()


def effective_decision(engine: DecisionRecord, overrides: list[OverrideRecord]) -> Decision:
    return Decision(overrides[-1].override.new_decision) if overrides else engine.decision


def effective_record(engine: DecisionRecord, overrides: list[OverrideRecord]) -> DecisionRecord:
    """The engine record as a reviewer left it. Unchanged when there is no override."""
    if not overrides:
        return engine
    last = overrides[-1]
    new = Decision(last.override.new_decision)
    return engine.model_copy(
        update={
            "overrides": [o.override for o in overrides],
            "status": RecordStatus.OVERRIDDEN,
            "decision": new,
            "outcome": Outcome(
                decision=new.value,
                decided_by=f"{HUMAN_PREFIX}{last.override.reviewer}",
                decided_at=last.override.at,
            ),
            "claim": last.claim if new == Decision.CLAIM else None,
        }
    ).with_hash()


def check_chain(engine: DecisionRecord, overrides: list[OverrideRecord]) -> list[str]:
    """Problems with the stored chain, or [] when every hash and link verifies."""
    problems: list[str] = []
    if not engine.verify_hash():
        problems.append(f"{engine.record_id}: engine record hash does not verify")
    previous: str | None = None
    current = engine.decision
    for o in overrides:
        if not o.verify_hash():
            problems.append(f"override {o.sequence}: content hash does not verify")
        if o.engine_record_hash != engine.content_hash:
            problems.append(f"override {o.sequence}: points at a different engine record")
        if o.previous_override_hash != previous:
            problems.append(f"override {o.sequence}: previous-override link is broken")
        if o.override.original_decision != current.value:
            problems.append(f"override {o.sequence}: original decision is not the one it replaced")
        is_claim = o.override.new_decision == Decision.CLAIM.value
        if is_claim != (o.claim is not None):
            problems.append(f"override {o.sequence}: claim amount does not match its decision")
        elif o.claim is not None and (
            o.claim.amount != engine.amount_charged - engine.amount_reimbursed
            or o.claim.currency != engine.currency
        ):
            problems.append(
                f"override {o.sequence}: claim {o.claim.amount} {o.claim.currency} is not the "
                f"charge not yet reimbursed "
                f"({engine.amount_charged - engine.amount_reimbursed} {engine.currency})"
            )
        previous = o.content_hash
        current = Decision(o.override.new_decision)
    return problems


def _check(rec: DecisionRecord, key: str) -> Check | None:
    return next((c for c in rec.checks if c.check_key == key), None)


def claim_refusal(engine: DecisionRecord, cfg: EngineConfig) -> str | None:
    """Why a reviewer may not set this record to CLAIM, or None when they may."""
    if engine.status == RecordStatus.PENDING:
        return (
            "this decision is pending (the engine did not finish), so amounts already "
            "reimbursed were never computed; re-run the charge before claiming it"
        )
    if cfg.charge_types[engine.subject.charge_type].kind == "loss_event":
        return (
            "a loss event is never CLAIM: its amount is what the channel already paid, and "
            "what is owed needs an authoritative unit value (D-011, D-016)"
        )
    if (
        engine.subject.report_type == ReportType.REIMBURSEMENT_REPORT
        and cfg.charge_types[engine.subject.charge_type].kind == "fee"
    ):
        return "this line is a refund of a fee (money back to the seller), not a charge"
    window = _check(engine, "within_filing_window")
    if window is None or window.verdict == Verdict.FAIL:
        detail = window.detail if window else "not recorded"
        return f"the filing window does not allow a claim: {detail}"
    reimbursed = _check(engine, "not_already_reimbursed")
    if reimbursed is None or reimbursed.verdict != Verdict.PASS:
        detail = reimbursed.detail if reimbursed else "not recorded"
        return f"what was already reimbursed is not settled: {detail}"
    if engine.amount_charged - engine.amount_reimbursed <= ZERO:
        return (
            f"nothing left to claim: charged {engine.amount_charged}, already reimbursed "
            f"{engine.amount_reimbursed} {engine.currency}"
        )
    return None


def _override_claim(engine: DecisionRecord, reviewer: str, cfg: EngineConfig) -> Claim:
    refusal = claim_refusal(engine, cfg)
    if refusal is not None:
        raise OverrideError(refusal, 409)
    remaining = engine.amount_charged - engine.amount_reimbursed
    cur = engine.currency
    return Claim(
        amount=remaining,
        currency=cur,
        computation=[
            f"human override by {reviewer}: claim the charge not yet reimbursed",
            f"charged {engine.amount_charged} {cur} on {engine.subject.line_id}",
            f"already reimbursed {engine.amount_reimbursed} {cur} (engine pre-check)",
            f"claim = {engine.amount_charged} - {engine.amount_reimbursed} = {remaining} {cur}",
        ],
    )


def apply_override(
    session: Session,
    organization_id: str,
    record_id: str,
    req: OverrideRequest,
    at: datetime,
    cfg: EngineConfig | None = None,
) -> tuple[OverrideRecord, DecisionRecord]:
    """Store one override of `record_id` and return it with the new effective record.
    Serialised per decision with a transaction-scoped advisory lock, so two reviewers
    cannot both override from the same starting decision."""
    cfg = cfg or load_engine_config()
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
        {"k": f"override:{organization_id}:{record_id}"},
    )
    engine = repo.get_decision(session, record_id)
    if engine is None:
        raise OverrideError(f"no decision {record_id!r}", 404)
    newest = repo.list_decisions_for_line(session, engine.subject.line_id)[-1]
    if newest.record_id != engine.record_id:
        raise OverrideError(
            f"a newer run decided this charge line ({newest.record_id}); override that "
            "decision instead, older runs are kept as history",
            409,
        )
    overrides = repo.list_overrides(session, record_id)
    problems = check_chain(engine, overrides) + repo.override_column_problems(session, record_id)
    if problems:
        raise OverrideError("stored history does not verify: " + "; ".join(problems), 409)
    current = effective_decision(engine, overrides)
    if req.new_decision == current:
        raise OverrideError(f"the decision is already {current.value}", 409)
    claim = (
        _override_claim(engine, req.reviewer, cfg) if req.new_decision == Decision.CLAIM else None
    )
    rec = OverrideRecord(
        decision_record_id=engine.record_id,
        line_id=engine.subject.line_id,
        sequence=len(overrides) + 1,
        override=Override(
            original_decision=current.value,
            new_decision=req.new_decision.value,
            reason=req.reason,
            reviewer=req.reviewer,
            at=at,
        ),
        claim=claim,
        engine_record_hash=engine.content_hash or "",
        previous_override_hash=overrides[-1].content_hash if overrides else None,
    ).with_hash()
    effective = effective_record(engine, [*overrides, rec])
    if claim is not None:
        charge = repo.get_charge(session, engine.subject.line_id)
        errors = (
            ["charge not found in the store"]
            if charge is None
            else validate(effective, charge, DbLookup(session), cfg, human_override=True)
        )
        if errors:
            raise OverrideError("the claim does not validate: " + "; ".join(errors), 409)
    repo.insert_override(session, organization_id, rec)
    repo.add_audit_event(
        session,
        organization_id,
        "DECISION_OVERRIDDEN",
        {
            "record_id": engine.record_id,
            "line_id": engine.subject.line_id,
            "sequence": rec.sequence,
            "original_decision": current.value,
            "new_decision": req.new_decision.value,
            "reviewer": req.reviewer,
            "reason": req.reason,
            "claim_amount": str(claim.amount) if claim else None,
            "content_hash": rec.content_hash,
            "previous_override_hash": rec.previous_override_hash,
        },
    )
    return rec, effective

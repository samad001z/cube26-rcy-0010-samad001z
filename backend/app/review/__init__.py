"""Human review of decisions: overrides and the effective decision (D-021).

An override is data (CLAUDE.md rule 11). It is written to its own append-only table and
never changes the decision row it points at, whose content hash therefore still verifies.
The effective decision of a record is the newest override's new decision, or the engine's
decision when there is none. The effective record is the engine record with `overrides`
filled, `status: overridden`, `outcome.decided_by: human:<reviewer>`, the new decision and,
for a CLAIM, a claim amount; it gets its own content hash.

Each override stores the content hash of the engine record and of the previous override
(a hash chain, checked at application level). Rules that keep money honest:

- A human CLAIM claims the remaining charge: amount charged minus amount already
  reimbursed, as the engine's pre-check computed it (rule 9). If nothing remains, the
  override is refused.
- A pending (fail-open) record cannot be overridden to CLAIM: its reimbursements were never
  computed, so the cap is unknown. Re-run it first. It can be set to DO_NOT_CLAIM.
- An override must change the effective decision; a no-op is refused.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.hashing import content_hash
from app.db import repo
from app.models.contract import Outcome, Override
from app.models.decision import Claim, DecisionRecord
from app.models.vocab import Decision, RecordStatus

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
        previous = o.content_hash
        current = Decision(o.override.new_decision)
    return problems


def _override_claim(engine: DecisionRecord, reviewer: str) -> Claim:
    if engine.status == RecordStatus.PENDING:
        raise OverrideError(
            "this decision is pending (the engine did not finish), so amounts already "
            "reimbursed were never computed; re-run the charge before claiming it",
            409,
        )
    remaining = engine.amount_charged - engine.amount_reimbursed
    if remaining <= ZERO:
        raise OverrideError(
            f"nothing left to claim: charged {engine.amount_charged}, already reimbursed "
            f"{engine.amount_reimbursed} {engine.currency}",
            409,
        )
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
    session: Session, organization_id: str, record_id: str, req: OverrideRequest, at: datetime
) -> tuple[OverrideRecord, DecisionRecord]:
    """Store one override of `record_id` and return it with the new effective record.
    Serialised per decision with a transaction-scoped advisory lock, so two reviewers
    cannot both override from the same starting decision."""
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
        {"k": f"override:{organization_id}:{record_id}"},
    )
    engine = repo.get_decision(session, record_id)
    if engine is None:
        raise OverrideError(f"no decision {record_id!r}", 404)
    overrides = repo.list_overrides(session, record_id)
    problems = check_chain(engine, overrides)
    if problems:
        raise OverrideError("stored history does not verify: " + "; ".join(problems), 409)
    current = effective_decision(engine, overrides)
    if req.new_decision == current:
        raise OverrideError(f"the decision is already {current.value}", 409)
    claim = _override_claim(engine, req.reviewer) if req.new_decision == Decision.CLAIM else None
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
            "claim_amount": str(claim.amount) if claim else None,
            "content_hash": rec.content_hash,
        },
    )
    return rec, effective_record(engine, [*overrides, rec])

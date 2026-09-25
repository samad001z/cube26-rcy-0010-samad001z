"""Claim amounts. Decimal only; every step is written out as a computation line.

Invariant (CLAUDE.md rule 9): a claim never exceeds the charge amount minus amounts
already reimbursed, and is never zero or negative (no claim is made instead).
"""

from decimal import ROUND_HALF_EVEN, Decimal

from app.core.money import CENT
from app.models.charge import Charge
from app.models.decision import Claim

ZERO = Decimal("0.00")


def claim_cap(charge: Charge, reimbursed: Decimal) -> Decimal:
    return max(charge.amount - reimbursed, ZERO)


def compute_full_amount_claim(
    charge: Charge, coverage: Decimal, reimbursed: Decimal, reimbursement_ids: list[str]
) -> Claim | None:
    """Claim for a fee that should not have been charged (claim_basis: full_amount)."""
    if not (Decimal(0) <= coverage <= Decimal(1)):
        raise ValueError(f"coverage must be within [0, 1], got {coverage}")
    gross = (charge.amount * coverage).quantize(CENT, rounding=ROUND_HALF_EVEN)
    cap = claim_cap(charge, reimbursed)
    amount = min(gross, cap)
    cur = charge.currency
    lines = [
        f"charged {charge.amount} {cur} on {charge.line_id} (quantity {charge.quantity})",
        f"evidence coverage {coverage} -> {charge.amount} x {coverage} = {gross} {cur}",
        f"already reimbursed {reimbursed} {cur}"
        + (f" ({', '.join(reimbursement_ids)})" if reimbursement_ids else ""),
        f"claim = min({gross}, {charge.amount} - {reimbursed}) = {amount} {cur}",
    ]
    if amount <= ZERO:
        return None
    return Claim(amount=amount, currency=cur, computation=lines)

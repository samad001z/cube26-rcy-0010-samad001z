"""Pre-checks that run before any evidence is read. Pure functions over ingested charges.

- Duplicate: a fee line whose fingerprint matches an earlier line posted within the
  configured window. The earliest is canonical; the later one is the duplicate (D-003).
- Already reimbursed (heuristic): a `reimbursement_report` line for a fee charge type on
  the same unit, posted on or after the fee, offsets that fee. Each reimbursement line is
  allocated to one fee only, earliest fee first.
- Filing window: deadline = posted date + the sourced window from config/rules/. With no
  sourced window the verdict is UNCERTAIN ("filing deadline not verified").
"""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.core.rules import ChannelRules, EngineConfig
from app.models.charge import Charge
from app.models.vocab import ReportType, Verdict

ZERO = Decimal("0.00")
FILING_NOT_VERIFIED = "filing deadline not verified"


@dataclass(frozen=True)
class FilingWindow:
    verdict: Verdict
    deadline: date | None
    window_days: int | None
    source_url: str | None
    detail: str


@dataclass(frozen=True)
class Precheck:
    duplicate_of: Charge | None
    reimbursements: tuple[Charge, ...]
    reimbursed_amount: Decimal
    filing: FilingWindow


def is_fee(charge: Charge, cfg: EngineConfig) -> bool:
    return cfg.charge_types[charge.charge_type].kind == "fee"


def is_fee_refund_line(charge: Charge, cfg: EngineConfig) -> bool:
    """A reimbursement-report line on a fee charge type: money back to the seller."""
    return charge.report_type == ReportType.REIMBURSEMENT_REPORT and is_fee(charge, cfg)


def _is_chargeable_fee(charge: Charge, cfg: EngineConfig) -> bool:
    return is_fee(charge, cfg) and not is_fee_refund_line(charge, cfg) and charge.amount > ZERO


def _fingerprint(c: Charge) -> tuple[object, ...]:
    return (
        c.organization_id,
        c.report_type,
        c.charge_type,
        c.unit_id,
        c.sku,
        c.fba_shipment_id,
        c.order_id,
        c.quantity,
        c.amount,
        c.currency,
    )


def _order(c: Charge) -> tuple[date, str]:
    return (c.posted_date, c.line_id)


def find_duplicates(charges: Sequence[Charge], cfg: EngineConfig) -> dict[str, Charge]:
    """line_id of each duplicate -> its canonical (earliest) charge."""
    groups: dict[tuple[object, ...], list[Charge]] = defaultdict(list)
    for c in charges:
        if _is_chargeable_fee(c, cfg):
            groups[_fingerprint(c)].append(c)
    window = timedelta(days=cfg.duplicate.window_days)
    result: dict[str, Charge] = {}
    for group in groups.values():
        group.sort(key=_order)
        canonical = group[0]
        for c in group[1:]:
            if c.posted_date - canonical.posted_date <= window:
                result[c.line_id] = canonical
            else:
                canonical = c
    return result


def match_reimbursements(
    charges: Sequence[Charge], cfg: EngineConfig
) -> dict[str, tuple[Charge, ...]]:
    """fee line_id -> reimbursement lines allocated to it (heuristic, see module doc)."""
    refunds = sorted((c for c in charges if is_fee_refund_line(c, cfg)), key=_order)
    fees = sorted((c for c in charges if _is_chargeable_fee(c, cfg)), key=_order)
    used: set[str] = set()
    result: dict[str, tuple[Charge, ...]] = {}
    for fee in fees:
        matched = []
        for r in refunds:
            if (
                r.line_id not in used
                and r.organization_id == fee.organization_id
                and r.unit_id == fee.unit_id
                and r.charge_type == fee.charge_type
                and r.currency == fee.currency
                and r.posted_date >= fee.posted_date
            ):
                matched.append(r)
                used.add(r.line_id)
        if matched:
            result[fee.line_id] = tuple(matched)
    return result


def filing_window(charge: Charge, rules: ChannelRules, as_of: date) -> FilingWindow:
    rule = rules.filing_window_days[charge.charge_type]
    if rule.value is None:
        return FilingWindow(
            Verdict.UNCERTAIN,
            None,
            None,
            None,
            f"{FILING_NOT_VERIFIED}: no sourced filing window for {charge.charge_type.value} "
            "in config/rules/",
        )
    assert isinstance(rule.value, int)
    deadline = charge.posted_date + timedelta(days=rule.value)
    verdict = Verdict.FAIL if as_of > deadline else Verdict.PASS
    state = "passed" if verdict == Verdict.FAIL else "open"
    return FilingWindow(
        verdict,
        deadline,
        rule.value,
        rule.source_url,
        f"posted {charge.posted_date} + {rule.value} days = deadline {deadline}; "
        f"as of {as_of} the window is {state} (source: {rule.source_url})",
    )


def run_prechecks(
    charges: Sequence[Charge], rules: ChannelRules, cfg: EngineConfig, as_of: date
) -> dict[str, Precheck]:
    dups = find_duplicates(charges, cfg)
    reimb = match_reimbursements(charges, cfg)
    out: dict[str, Precheck] = {}
    for c in charges:
        lines = reimb.get(c.line_id, ())
        out[c.line_id] = Precheck(
            duplicate_of=dups.get(c.line_id),
            reimbursements=lines,
            reimbursed_amount=sum((r.amount for r in lines), ZERO),
            filing=filing_window(c, rules, as_of),
        )
    return out

"""Write eval/labelling_sheet.csv (and blank labels_A.csv / labels_B.csv) from the held-out
eval CSVs, in the plain terms of eval/LABELLING_GUIDE.md.

The summaries are built from the ingested records only: the csv_v0 adapter (which maps raw
values to PASS / FAIL / UNCERTAIN, the same records the agent reads; every verdict is shown
with the raw value the team recorded, so labellers can disagree with the mapping) and the
sourced channel rules for deadlines. Nothing here imports the decision path (app.engine,
app.precheck, app.resolution, app.retrieval, app.pipeline, app.claims), and nothing states
or hints at an answer. Deterministic: the same inputs give byte-identical output.

    cd backend && uv run python ../eval/make_sheet.py [--templates]

--templates also (re)writes the blank labels_A.csv and labels_B.csv. It refuses to
overwrite a label file that already has a label in it.
"""

import argparse
import csv
import sys
from collections.abc import Mapping
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from app.adapters.csv_v0 import load_config, load_fee_report, load_upstream
from app.core.rules import ChannelRules, load_rules
from app.models.charge import Charge
from app.models.contract import EvidenceRecord
from app.models.vocab import RecordStatus
from common import (
    AS_OF,
    CHARGE_TYPE_NAMES,
    FEE_TYPES,
    LABELS_A,
    LABELS_B,
    REPORT_CSV,
    SHEET_CSV,
    TEAM_NAMES,
    UPSTREAM_DIR,
)

# Plain names for the checks each team records (labelling guide, section 5).
CHECK_NAMES = {
    "polybag_present_sealed": "plastic bag present and sealed",
    "suffocation_warning": "suffocation warning sticker",
    "fnsku_label_placement": "Amazon label placement",
    "original_barcode_covered": "original barcode covered",
    "expiry_date": "expiry date",
    "handling_marks": "handling marks",
    "identity_match": "right item",
    "returned_item_condition": "condition",
    "parts_complete": "all parts present",
    "carton_damage": "no carton damage",
    "unit_damage": "no unit damage",
    "qty_received_matches_ordered": "quantity received matches order",
    "cartons_received_matches_ordered": "cartons received match order",
    "quality_flags": "no quality flags",
    "contents_match_order": "box contents match the order",
}
# Prep work-order requirement flags and the check each one switches on.
REQUIREMENT_NAMES = {
    "wo_polybag": "plastic bag",
    "wo_suffocation_warning": "suffocation warning sticker",
    "wo_expiry_date": "expiry date",
    "wo_handling_marks": "handling marks",
}
DEFECT_NAMES = {
    "label": "label problem",
    "polybag": "plastic bag problem",
    "suffocation_warning": "missing suffocation warning",
    "expiry_date": "expiry date problem",
    "handling_marks": "handling marks problem",
}
REPORT_NAMES = {
    "fee_report": "fee report",
    "inventory_adjustment": "inventory adjustment",
    "reimbursement_report": "reimbursement report",
}


def _money(amount: Decimal) -> str:
    return f"${amount:.2f}"


def _plain(raw: str) -> str:
    return raw.replace("_", " ")


def amount_text(c: Charge) -> str:
    if c.report_type.value == "reimbursement_report" and c.charge_type.value in FEE_TYPES:
        return f"{_money(c.amount)} paid back to the seller by Amazon (a refund of this fee type)"
    if c.charge_type.value in FEE_TYPES:
        return f"{_money(c.amount)} taken by Amazon"
    if c.amount == 0:
        return f"{_money(c.amount)} already paid back to the seller (Amazon paid nothing)"
    return f"{_money(c.amount)} already paid back to the seller by Amazon"


def charge_line(c: Charge) -> str:
    parts = [
        CHARGE_TYPE_NAMES[c.charge_type.value],
        amount_text(c),
        f"unit {c.unit_id}",
        f"SKU {c.sku}",
        f"shipment {c.fba_shipment_id or '(none)'}",
        f"order {c.order_id or '(none)'}",
        f"quantity {c.quantity}",
        f"posted {c.posted_date}",
        f"line from the {REPORT_NAMES[c.report_type.value]}",
    ]
    if c.charge_type.value == "inbound_defect_fee":
        cat = c.defect_category
        parts.append(
            f"defect_category: {DEFECT_NAMES.get(cat, _plain(cat))} ({cat})"
            if cat
            else "defect_category: blank"
        )
    return "; ".join(parts)


def deadline_text(c: Charge, rules: ChannelRules) -> str:
    """Deadline status from the sourced channel rules, counted from the posted date."""
    rule = rules.filing_windows[c.charge_type]
    name = CHARGE_TYPE_NAMES[c.charge_type.value]
    if rule.window_open_days is None and rule.window_close_days is None:
        return f"Deadline: no known filing deadline for {name.lower()} claims."
    # The source counts from the event (refund, damage report); no record carries that date,
    # so the posted date stands in for it, as it does for the agent (D-017).
    since = f"counted from the posted date {c.posted_date}, used in place of the event date"
    if rule.window_open_days is not None:
        opens = c.posted_date + timedelta(days=rule.window_open_days)
        if opens > AS_OF:
            return (
                f"Deadline: filing window NOT YET OPEN on {AS_OF}; it opens on {opens} "
                f"({rule.window_open_days} days, {since})."
            )
    if rule.window_close_days is not None:
        closes = c.posted_date + timedelta(days=rule.window_close_days)
        if closes < AS_OF:
            return (
                f"Deadline: known deadline PASSED on {closes} "
                f"({rule.window_close_days} days, {since})."
            )
        return (
            f"Deadline: inside the known filing window on {AS_OF}; it closes on {closes} "
            f"({rule.window_close_days} days, {since})."
        )
    return f"Deadline: window open on {AS_OF}; no known closing date."


# (pod, check_key) -> the raw CSV column the adapter maps to PASS / FAIL / UNCERTAIN.
_ENUM_COLUMNS = {
    (pod, spec["check_key"]): spec["column"]
    for pod, pod_cfg in load_config()["pods"].items()
    for spec in pod_cfg["enum_checks"]
}


def _check_text(pod: str, key: str, verdict: str, detail: str | None, raw: dict[str, str]) -> str:
    """The verdict, always followed by what the team actually recorded, so a labeller can
    judge the adapter's PASS / FAIL / UNCERTAIN mapping instead of inheriting it."""
    name = CHECK_NAMES.get(key, _plain(key))
    column = _ENUM_COLUMNS.get((pod, key))
    recorded = (raw.get(column) or "").strip() if column else (detail or "")
    if not recorded:
        return f"{name} {verdict}"
    return f"{name} {verdict} (recorded: {_plain(recorded).replace('=', ': ')})"


def record_text(r: EvidenceRecord, raw: dict[str, str]) -> str:
    team = TEAM_NAMES[r.agent]
    where = [f"recorded {r.captured_at:%Y-%m-%d %H:%M} UTC"]
    s = r.subject
    if r.agent == "prep":
        where.append(f"shipment {s.fba_shipment_id}")
    if s.order_id:
        where.append(f"order {s.order_id}")
    if s.sku:
        where.append(f"SKU {s.sku}")
    head = f"{team} record {r.record_id} ({', '.join(where)})"
    checks = [_check_text(r.agent, c.check_key, c.verdict.value, c.detail, raw) for c in r.checks]
    text = head + ": " + (", ".join(checks) if checks else "no checks recorded")
    if r.agent == "prep":
        not_required = [
            name
            for flag, name in REQUIREMENT_NAMES.items()
            if s.requirements.get(flag, "") in ("", "False")
        ]
        if not_required:
            text += "; the work order did not require: " + ", ".join(not_required)
    # A pending record's disposition only says it is pending; the PENDING line says that.
    if r.outcome is not None and r.status != RecordStatus.PENDING:
        text += f"; operator decision: {_plain(r.outcome.decision)}"
    if r.status == RecordStatus.PENDING:
        text += "; this record is still PENDING (not finalised by the team)"
    return text + "."


def summary(
    c: Charge,
    records: list[EvidenceRecord],
    others: list[Charge],
    rules: ChannelRules,
    raw: Mapping[tuple[str, str], dict[str, str]],
) -> str:
    lines: list[str] = []
    mine = sorted(
        (r for r in records if r.subject.unit_id == c.unit_id),
        key=lambda r: (r.captured_at, r.agent, r.record_id),
    )
    if not mine:
        lines.append(f"No team has any record for unit {c.unit_id}.")
    else:
        lines.extend(record_text(r, raw[(r.agent, r.record_id)]) for r in mine)
        missing = [TEAM_NAMES[p] for p in TEAM_NAMES if not any(r.agent == p for r in mine)]
        if missing:
            lines.append("No records from: " + ", ".join(missing) + ".")
    if c.charge_type.value == "fulfilment_fee_weight_tier":
        measured = any(
            ch.check_key in ("measured_weight", "measured_dimensions")
            for r in mine
            for ch in r.checks
        )
        if not measured:
            lines.append("No team recorded a measured weight or size for this unit.")
    for o in sorted(others, key=lambda o: (o.posted_date, o.line_id)):
        lines.append(f"Other report line for this unit: {o.line_id}: {charge_line(o)}.")
    lines.append(deadline_text(c, rules))
    return "\n".join(lines)


def build_rows() -> list[dict[str, str]]:
    fees = load_fee_report(REPORT_CSV)
    # Attachment keys are not used by the sheet, so any HMAC secret will do.
    ups = load_upstream(UPSTREAM_DIR, secret="labelling-sheet")  # noqa: S106
    if fees.quarantined or ups.quarantined:
        raise SystemExit(f"eval data has quarantined rows: {fees.quarantined + ups.quarantined}")
    rules = load_rules()
    raw = {key: src.raw for key, src in ups.sources.items()}
    rows = []
    for c in sorted(fees.charges, key=lambda c: c.line_id):
        org_records = [r for r in ups.records if r.organization_id == c.organization_id]
        others = [
            o
            for o in fees.charges
            if o.unit_id == c.unit_id
            and o.organization_id == c.organization_id
            and o.line_id != c.line_id
        ]
        rows.append(
            {
                "case_id": c.line_id,
                "charge_line": charge_line(c),
                "evidence_summary": summary(c, org_records, others, rules, raw),
                "label": "",
                "reason": "",
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def _has_labels(path: Path) -> bool:
    if not path.exists():
        return False
    with path.open(newline="", encoding="utf-8") as fh:
        return any((row.get("label") or "").strip() for row in csv.DictReader(fh))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--templates", action="store_true", help="also write blank label files")
    args = parser.parse_args(argv)
    rows = build_rows()
    write_csv(SHEET_CSV, rows)
    print(f"wrote {SHEET_CSV.name}: {len(rows)} cases (as of {AS_OF})")
    if args.templates:
        for path in (LABELS_A, LABELS_B):
            if _has_labels(path):
                print(f"refusing to overwrite {path.name}: it already has labels", file=sys.stderr)
                return 1
            write_csv(path, rows)
            print(f"wrote blank {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

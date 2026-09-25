"""Builders for small, explicit test inputs. Test-only; the sample CSVs are never edited."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from app.models.charge import Charge, SourceRef
from app.models.contract import Check, EvidenceRecord, Outcome, Subject
from app.models.vocab import ChargeType, RecordStatus, ReportType, Verdict

ORG = "org_test"


def charge(
    line_id: str = "L-1",
    *,
    charge_type: ChargeType = ChargeType.INBOUND_DEFECT_FEE,
    report_type: ReportType = ReportType.FEE_REPORT,
    unit_id: str = "U-1",
    amount: str = "2.00",
    quantity: int = 1,
    posted: date = date(2026, 7, 18),
    sku: str | None = "SKU-1",
    fnsku: str | None = "X-1",
    fba_shipment_id: str | None = "FBA-1",
    order_id: str | None = None,
    defect_category: str | None = None,
    org: str = ORG,
) -> Charge:
    return Charge(
        line_id=line_id,
        report_type=report_type,
        organization_id=org,
        unit_id=unit_id,
        sku=sku,
        fnsku=fnsku,
        fba_shipment_id=fba_shipment_id,
        order_id=order_id,
        charge_type=charge_type,
        quantity=quantity,
        amount=Decimal(amount),
        posted_date=posted,
        defect_category=defect_category,
        source=SourceRef(file_sha256="0" * 64, row=1, raw={"line_id": line_id}),
    )


def check(key: str, verdict: Verdict | str, detail: str | None = None) -> Check:
    return Check(check_key=key, verdict=Verdict(verdict), detail=detail)


def record(
    record_id: str = "PRP-1",
    *,
    agent: str = "prep",
    unit_id: str = "U-1",
    captured: datetime = datetime(2026, 6, 6, 7, 36, tzinfo=UTC),
    checks: list[Check] | None = None,
    sku: str | None = "SKU-1",
    fnsku: str | None = "X-1",
    fba_shipment_id: str | None = "FBA-1",
    order_id: str | None = None,
    outcome: str | None = None,
    status: RecordStatus = RecordStatus.FINAL,
    org: str = ORG,
    **subject: Any,
) -> EvidenceRecord:
    return EvidenceRecord(
        record_id=record_id,
        schema_version="csv_v0",
        organization_id=org,
        client_id=org,
        agent=agent,
        subject=Subject(
            unit_id=unit_id,
            sku=sku,
            fnsku=fnsku,
            fba_shipment_id=fba_shipment_id,
            order_id=order_id,
            **subject,
        ),
        captured_at=captured,
        operator_label="op_test",
        checks=checks or [],
        outcome=(
            Outcome(decision=outcome, decided_by="operator:op_test", decided_at=captured)
            if outcome
            else None
        ),
        status=status,
    ).with_hash()


def prep_all_pass(record_id: str = "PRP-1", **kw: Any) -> EvidenceRecord:
    return record(
        record_id,
        checks=[
            check("fnsku_label_placement", "PASS"),
            check("original_barcode_covered", "PASS"),
            check("handling_marks", "PASS"),
        ],
        **kw,
    )

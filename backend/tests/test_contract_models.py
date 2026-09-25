from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.models.charge import Charge, SourceRef
from app.models.contract import Check, EvidenceRecord, Override, Subject
from app.models.vocab import RecordStatus, Verdict

T = datetime(2026, 6, 4, 12, 0, tzinfo=UTC)


def _record(**kw):
    base = {
        "record_id": "PRP-0001",
        "schema_version": "csv_v0",
        "organization_id": "org_demo_alpha",
        "client_id": "org_demo_alpha",
        "agent": "prep",
        "subject": Subject(unit_id="UNIT-0001"),
        "captured_at": T,
        "status": RecordStatus.FINAL,
    }
    return EvidenceRecord(**{**base, **kw})


def test_hash_round_trip_and_tamper_detection():
    rec = _record().with_hash()
    assert rec.verify_hash()
    tampered = rec.model_copy(update={"operator_label": "someone_else"})
    assert not tampered.verify_hash()


def test_hash_excludes_hash_field_and_is_stable():
    assert _record().with_hash().content_hash == _record().with_hash().content_hash


def test_unhashed_record_does_not_verify():
    assert not _record().verify_hash()


def test_bad_verdict_rejected():
    with pytest.raises(ValidationError):
        Check(check_key="x", verdict="MAYBE")


def test_confidence_bounds_and_no_floats_needed():
    with pytest.raises(ValidationError):
        Check(check_key="x", verdict=Verdict.PASS, confidence="1.5")


def test_naive_timestamp_rejected():
    with pytest.raises(ValidationError):
        _record(captured_at=datetime(2026, 6, 4, 12, 0))


def test_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        _record(surprise=1)


def test_override_requires_reason():
    with pytest.raises(ValidationError):
        Override(original_decision="a", new_decision="b", reason="", reviewer="r", at=T)


def _charge(**kw):
    base = {
        "line_id": "FEE-1",
        "report_type": "fee_report",
        "organization_id": "org_demo_alpha",
        "unit_id": "UNIT-0001",
        "charge_type": "inbound_defect_fee",
        "quantity": 1,
        "amount": "4.25",
        "posted_date": date(2026, 6, 24),
        "source": SourceRef(file_sha256="0" * 64, row=1, raw={}),
    }
    return Charge(**{**base, **kw})


def test_charge_amount_is_decimal_and_rejects_float():
    from decimal import Decimal

    assert _charge().amount == Decimal("4.25")
    assert _charge(amount="0.00").amount == Decimal("0.00")
    with pytest.raises(ValidationError):
        _charge(amount=4.25)


def test_charge_rejects_unknown_type_and_zero_quantity():
    with pytest.raises(ValidationError):
        _charge(charge_type="made_up")
    with pytest.raises(ValidationError):
        _charge(quantity=0)

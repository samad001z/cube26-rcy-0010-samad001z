"""Adapter: older flat sample CSVs -> official evidence contract records and charges.

Faithful ingestion only. No decisions are made here. Bad rows are quarantined with a
reason, never dropped silently. Verdict mappings live in config/adapters/csv_v0.yaml.
"""

import csv
import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.core.config import REPO_ROOT
from app.models.charge import Charge, SourceRef
from app.models.contract import Check, EvidenceRecord, Image, Outcome, Subject
from app.models.vocab import RecordStatus, Verdict

CONFIG_PATH = REPO_ROOT / "config" / "adapters" / "csv_v0.yaml"


@dataclass(frozen=True)
class Quarantined:
    file: str
    row: int
    reason: str
    raw: dict[str, str]


@dataclass(frozen=True)
class AttachmentRef:
    organization_id: str
    record_id: str
    key: str
    source_path: str


@dataclass
class UpstreamLoad:
    records: list[EvidenceRecord] = field(default_factory=list)
    sources: dict[str, SourceRef] = field(default_factory=dict)  # record_id -> raw row
    attachments: list[AttachmentRef] = field(default_factory=list)
    quarantined: list[Quarantined] = field(default_factory=list)


@dataclass
class ChargeLoad:
    charges: list[Charge] = field(default_factory=list)
    quarantined: list[Quarantined] = field(default_factory=list)


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(cfg, dict)
    return cfg


def attachment_key(secret: str, organization_id: str, record_id: str, path: str) -> str:
    """Non-guessable, org-scoped key. Deterministic, so reloads are idempotent."""
    msg = f"{organization_id}|{record_id}|{path}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value.strip())
    if dt.tzinfo is None:
        raise ValueError(f"timestamp has no timezone: {value!r}")
    return dt


def _verdict(v: str) -> Verdict:
    return Verdict(v)


def _lines(value: str) -> list[str]:
    return sorted(p.strip() for p in value.split(";") if p.strip())


def _derived_checks(name: str, row: dict[str, str]) -> list[Check]:
    if name == "qty_received_matches_ordered":
        ordered, received = int(row["qty_ordered"]), int(row["qty_received"])
        return [
            Check(
                check_key=name,
                verdict=Verdict.PASS if ordered == received else Verdict.FAIL,
                detail=f"ordered={ordered} received={received}",
            )
        ]
    if name == "cartons_received_matches_ordered":
        ordered, received = int(row["cartons_ordered"]), int(row["cartons_received"])
        return [
            Check(
                check_key=name,
                verdict=Verdict.PASS if ordered == received else Verdict.FAIL,
                detail=f"ordered={ordered} received={received}",
            )
        ]
    if name == "quality_flags":
        flags = _clean(row.get("quality_flags"))
        return [
            Check(
                check_key=name,
                verdict=Verdict.FAIL if flags else Verdict.PASS,
                detail=flags,
            )
        ]
    if name == "contents_match_order":
        expected, observed = _lines(row["order_lines"]), _lines(row["observed_in_box"])
        return [
            Check(
                check_key=name,
                verdict=Verdict.PASS if expected == observed else Verdict.FAIL,
                detail=f"expected={';'.join(expected)} observed={';'.join(observed)}",
            )
        ]
    if name == "parts_complete":
        missing = _clean(row.get("parts_missing"))
        return [
            Check(
                check_key=name,
                verdict=Verdict.FAIL if missing else Verdict.PASS,
                detail=f"missing={missing}" if missing else None,
            )
        ]
    raise KeyError(f"unknown derived check {name!r}")


def _enum_checks(pod_cfg: dict[str, Any], row: dict[str, str]) -> list[Check]:
    checks: list[Check] = []
    for spec in pod_cfg["enum_checks"]:
        raw = (row.get(spec["column"]) or "").strip()
        if not all(isinstance(k, str) for k in spec["map"]):
            raise TypeError(f"non-string key in mapping for {spec['check_key']!r} (quote yes/no)")
        mapping: dict[str, str] = spec["map"]
        if raw not in mapping:
            raise ValueError(f"unmapped value {raw!r} in column {spec['column']!r}")
        mapped = mapping[raw]
        if mapped == "OMIT":
            continue
        # Keep the raw value where it carries information the verdict does not.
        detail = raw if mapped != "PASS" else None
        checks.append(Check(check_key=spec["check_key"], verdict=_verdict(mapped), detail=detail))
    return checks


def _build_record(
    pod: str,
    pod_cfg: dict[str, Any],
    schema_version: str,
    row: dict[str, str],
    secret: str,
) -> tuple[EvidenceRecord, list[AttachmentRef]]:
    record_id = row[pod_cfg["id_column"]].strip()
    org = row["org_id"].strip()
    if not record_id or not org:
        raise ValueError("record_id and org_id are required")
    captured_at = _parse_ts(row["captured_at"])

    subject_fields = {k: _clean(row.get(col)) for k, col in pod_cfg["subject_columns"].items()}
    requirements = {col: (row.get(col) or "").strip() for col in pod_cfg["requirement_columns"]}

    checks = _enum_checks(pod_cfg, row)
    for name in pod_cfg["derived_checks"]:
        checks.extend(_derived_checks(name, row))

    operator = _clean(row.get("operator_id"))
    outcome: Outcome | None = None
    status = RecordStatus.FINAL
    outcome_col = pod_cfg["outcome_column"]
    if outcome_col:
        decision = (row.get(outcome_col) or "").strip()
        if not decision:
            raise ValueError(f"empty outcome column {outcome_col!r}")
        outcome = Outcome(
            decision=decision,
            decided_by=f"operator:{operator}" if operator else "operator:unknown",
            decided_at=captured_at,
        )
        if decision == "pending_review":
            status = RecordStatus.PENDING

    images: list[Image] = []
    attachments: list[AttachmentRef] = []
    for path in (p.strip() for p in (row.get("photo_refs") or "").split(";")):
        if not path:
            continue
        key = attachment_key(secret, org, record_id, path)
        images.append(Image(key=key))
        attachments.append(AttachmentRef(org, record_id, key, path))

    record = EvidenceRecord(
        record_id=record_id,
        schema_version=schema_version,
        organization_id=org,
        client_id=org,  # csv_v0 has no client column; see DECISIONS D-008
        agent=pod,
        subject=Subject(
            unit_id=row["unit_id"].strip(), requirements=requirements, **subject_fields
        ),
        captured_at=captured_at,
        operator_label=operator,
        images=images,
        checks=checks,
        outcome=outcome,
        status=status,
    ).with_hash()
    return record, attachments


def load_upstream(
    directory: Path, secret: str, config: dict[str, Any] | None = None
) -> UpstreamLoad:
    cfg = config or load_config()
    result = UpstreamLoad()
    seen: set[tuple[str, str]] = set()
    for pod, pod_cfg in cfg["pods"].items():
        path = directory / pod_cfg["file"]
        file_hash = _file_sha256(path)
        with path.open(newline="", encoding="utf-8") as fh:
            for n, row in enumerate(csv.DictReader(fh), start=1):
                try:
                    record, atts = _build_record(pod, pod_cfg, cfg["schema_version"], row, secret)
                    key = (record.organization_id, record.record_id)
                    if key in seen:
                        raise ValueError(f"duplicate record_id {record.record_id!r}")
                except (ValueError, KeyError, ValidationError) as exc:
                    result.quarantined.append(Quarantined(path.name, n, str(exc), dict(row)))
                    continue
                seen.add(key)
                result.records.append(record)
                result.sources[record.record_id] = SourceRef(
                    file_sha256=file_hash, row=n, raw=dict(row)
                )
                result.attachments.extend(atts)
    return result


def load_fee_report(path: Path) -> ChargeLoad:
    result = ChargeLoad()
    file_hash = _file_sha256(path)
    seen: set[tuple[str, str]] = set()
    with path.open(newline="", encoding="utf-8") as fh:
        for n, row in enumerate(csv.DictReader(fh), start=1):
            try:
                charge = Charge(
                    line_id=row["line_id"].strip(),
                    report_type=row["report_type"].strip(),
                    organization_id=row["org_id"].strip(),
                    unit_id=row["unit_id"].strip(),
                    sku=_clean(row.get("sku")),
                    fnsku=_clean(row.get("fnsku")),
                    fba_shipment_id=_clean(row.get("fba_shipment_id")),
                    order_id=_clean(row.get("order_id")),
                    charge_type=row["charge_type"].strip(),
                    quantity=int(row["quantity"]),
                    amount=Decimal(row["amount_usd"].strip()),
                    posted_date=row["posted_date"].strip(),
                    source=SourceRef(file_sha256=file_hash, row=n, raw=dict(row)),
                )
                key = (charge.organization_id, charge.line_id)
                if key in seen:
                    raise ValueError(f"duplicate line_id {charge.line_id!r}")
            except (ValueError, KeyError, ArithmeticError, ValidationError) as exc:
                result.quarantined.append(Quarantined(path.name, n, str(exc), dict(row)))
                continue
            seen.add(key)
            result.charges.append(charge)
    return result

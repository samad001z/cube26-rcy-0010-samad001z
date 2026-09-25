"""Load charges and upstream evidence for one organisation into Postgres. Idempotent:
re-running inserts nothing new. Rows belonging to other organisations are skipped, not
loaded under this one."""

from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import Engine

from app.adapters.csv_v0 import file_sha256, load_fee_report, load_upstream
from app.db import repo
from app.db import tables as t
from app.db.session import org_session

PODS = ("receiving", "prep", "pack", "returns")


@dataclass
class IngestSummary:
    org: str
    charges_inserted: int = 0
    charges_total: int = 0
    records: dict[str, tuple[int, int]] = field(default_factory=dict)  # pod -> (inserted, total)
    quarantined: int = 0
    skipped_other_org: int = 0
    db_charges: int = 0
    db_records: int = 0
    db_attachments: int = 0


def ingest_org(
    engine: Engine, org: str, report: Path, upstream: Path, secret: str
) -> IngestSummary:
    fees = load_fee_report(report)
    ups = load_upstream(upstream, secret)

    charges = [c for c in fees.charges if c.organization_id == org]
    records = [r for r in ups.records if r.organization_id == org]
    attachments = [a for a in ups.attachments if a.organization_id == org]
    quarantined = fees.quarantined + ups.quarantined
    summary = IngestSummary(
        org=org,
        charges_total=len(charges),
        quarantined=len(quarantined),
        skipped_other_org=(len(fees.charges) - len(charges)) + (len(ups.records) - len(records)),
    )

    with org_session(engine, org) as session:
        fee_file = repo.upsert_ingest_file(
            session, org, report.name, file_sha256(report), "fee_report"
        )
        summary.charges_inserted = repo.insert_charges(session, charges, fee_file)
        for pod in PODS:
            pod_records = [r for r in records if r.agent == pod]
            pod_path = next(
                p for p in upstream.glob(f"{pod}_*.csv")
            )  # file names come from config/adapters/csv_v0.yaml
            file_id = repo.upsert_ingest_file(
                session, org, pod_path.name, file_sha256(pod_path), pod
            )
            summary.records[pod] = (
                repo.insert_records(session, pod_records, ups.sources, file_id),
                len(pod_records),
            )
        repo.insert_attachments(session, attachments)
        repo.insert_quarantined(session, org, quarantined)
        repo.add_audit_event(
            session,
            org,
            "INGEST",
            {
                "charges_inserted": summary.charges_inserted,
                "records_inserted": {k: v[0] for k, v in summary.records.items()},
                "quarantined": summary.quarantined,
                "rows_for_other_orgs_skipped": summary.skipped_other_org,
            },
        )
        summary.db_charges = repo.count_rows(session, t.charges)
        summary.db_records = repo.count_rows(session, t.evidence_records)
        summary.db_attachments = repo.count_rows(session, t.attachments)
    return summary

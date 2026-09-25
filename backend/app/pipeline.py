"""Run the decision pipeline for one organisation: pre-checks, resolution, retrieval, rule
engine, citation validation against the store, persistence and audit.

Every charge gets a persisted decision. If deciding a charge raises, that charge is still
persisted, as REVIEW with status pending (fail open, CLAUDE.md rule 5); the error is in
the reason and in the audit log. Everything runs inside one org-scoped session, so row-level
security applies to every read and write.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.claims.validator import StoredRecord, enforce, validate
from app.core.rules import ChannelRules, EngineConfig, load_engine_config, load_rules
from app.db import repo
from app.db.session import org_session
from app.engine import DECIDED_BY, ENGINE_VERSION, decide
from app.models.charge import Charge
from app.models.contract import Check, EvidenceRecord, Outcome
from app.models.decision import DecisionRecord, DecisionSubject
from app.models.vocab import Decision, EvidenceStatus, RecordStatus, Verdict
from app.precheck import Precheck, run_prechecks
from app.resolution import resolve_unit
from app.retrieval import retrieve

ENGINE_ERROR_RULE = "R_ENGINE_ERROR"
CHECK_KEYS = (
    "unit_resolved",
    "not_duplicate",
    "not_already_reimbursed",
    "within_filing_window",
    "evidence_present",
    "evidence_in_custody_window",
    "evidence_contradicts_charge",
    "amount_computable",
)


@dataclass(frozen=True)
class RunResult:
    run_id: str
    organization_id: str
    as_of: date
    decisions: list[DecisionRecord]


class DbLookup:
    """Validator lookup backed by the org-scoped session (RLS applies)."""

    def __init__(self, session: Session):
        self.session = session

    def evidence(self, record_id: str) -> StoredRecord | None:
        found = repo.get_record_with_hash(self.session, record_id)
        return StoredRecord(*found) if found else None

    def charge(self, line_id: str) -> Charge | None:
        return repo.get_charge(self.session, line_id)


def fail_open_decision(
    charge: Charge,
    exc: BaseException,
    *,
    run_id: str,
    decided_at: datetime,
    rules: ChannelRules,
    cfg: EngineConfig,
) -> DecisionRecord:
    """REVIEW, pending, nothing evaluated. The charge and the error are kept."""
    why = f"not evaluated: {type(exc).__name__}: {exc}"
    zero = Decimal("0.00")
    return DecisionRecord(
        record_id=f"DEC-{run_id[:8]}-{charge.line_id}",
        organization_id=charge.organization_id,
        client_id=charge.organization_id,
        subject=DecisionSubject(
            line_id=charge.line_id,
            unit_id=charge.unit_id,
            charge_type=charge.charge_type,
            report_type=charge.report_type,
            fba_shipment_id=charge.fba_shipment_id,
            order_id=charge.order_id,
            defect_category=charge.defect_category,
            charge_content_hash=charge.compute_hash(),
        ),
        captured_at=decided_at,
        checks=[
            Check(check_key=k, verdict=Verdict.UNCERTAIN, confidence=zero, detail=why)
            for k in CHECK_KEYS
        ],
        outcome=Outcome(
            decision=Decision.REVIEW.value, decided_by=DECIDED_BY, decided_at=decided_at
        ),
        status=RecordStatus.PENDING,
        run_id=run_id,
        decision=Decision.REVIEW,
        evidence_status=EvidenceStatus.INSUFFICIENT,
        reason_code=None,
        rule_id=ENGINE_ERROR_RULE,
        rule_path=[ENGINE_ERROR_RULE],
        reason=f"The engine failed on this charge, so it was kept for review ({why}).",
        next_action="Fix the error and re-run; the charge and evidence are unchanged.",
        confidence=zero,
        amount_charged=charge.amount,
        amount_reimbursed=zero,
        currency=charge.currency,
        claim=None,
        citations=[],
        evidence_considered=[],
        resolved_unit=None,
        engine_version=ENGINE_VERSION,
        rules_hash=rules.rules_hash,
        config_hash=cfg.config_hash,
    ).with_hash()


def _decide_one(
    session: Session,
    charge: Charge,
    pre: Precheck,
    by_unit: dict[str, list[EvidenceRecord]],
    rules: ChannelRules,
    cfg: EngineConfig,
    run_id: str,
    decided_at: datetime,
) -> DecisionRecord:
    res = resolve_unit(charge, by_unit.get(charge.unit_id, []))
    cands = retrieve(charge, res, cfg)
    d = decide(charge, pre, res, cands, rules, cfg, run_id=run_id, decided_at=decided_at)
    return enforce(d, validate(d, charge, DbLookup(session), cfg))


def _audit_payload(d: DecisionRecord) -> dict[str, object]:
    return {
        "run_id": d.run_id,
        "record_id": d.record_id,
        "line_id": d.subject.line_id,
        "decision": d.decision.value,
        "rule_id": d.rule_id,
        "status": d.status.value,
        "claim_amount": str(d.claim.amount) if d.claim else None,
        "content_hash": d.content_hash,
    }


def run_org(
    engine: Engine,
    org: str,
    as_of: date,
    *,
    rules: ChannelRules | None = None,
    cfg: EngineConfig | None = None,
    now: datetime | None = None,
) -> RunResult:
    rules = rules or load_rules()
    cfg = cfg or load_engine_config()
    decided_at = now or datetime.now(UTC)
    run_id = str(uuid.uuid4())
    decisions: list[DecisionRecord] = []
    with org_session(engine, org) as session:
        charges = repo.list_charges(session)
        by_unit: dict[str, list[EvidenceRecord]] = defaultdict(list)
        for r in repo.list_records(session):
            by_unit[r.subject.unit_id].append(r)
        prechecks = run_prechecks(charges, rules, cfg, as_of)
        repo.add_audit_event(
            session,
            org,
            "RUN_STARTED",
            {
                "run_id": run_id,
                "as_of": as_of.isoformat(),
                "charges": len(charges),
                "engine_version": ENGINE_VERSION,
                "rules_hash": rules.rules_hash,
                "config_hash": cfg.config_hash,
            },
        )
        for charge in charges:
            try:
                with session.begin_nested():
                    d = _decide_one(
                        session,
                        charge,
                        prechecks[charge.line_id],
                        by_unit,
                        rules,
                        cfg,
                        run_id,
                        decided_at,
                    )
                    repo.insert_decision(session, d)
            except Exception as exc:  # fail open: never drop a charge
                d = fail_open_decision(
                    charge, exc, run_id=run_id, decided_at=decided_at, rules=rules, cfg=cfg
                )
                repo.insert_decision(session, d)
                repo.add_audit_event(
                    session, org, "DECISION_FAILED_OPEN", {**_audit_payload(d), "error": repr(exc)}
                )
            repo.add_audit_event(session, org, "DECISION", _audit_payload(d))
            decisions.append(d)
        counts: dict[str, int] = defaultdict(int)
        for d in decisions:
            counts[d.decision.value] += 1
        repo.add_audit_event(
            session, org, "RUN_COMPLETED", {"run_id": run_id, "decisions": dict(counts)}
        )
    return RunResult(run_id, org, as_of, decisions)

"""Review endpoints for the operator UI: runs, decisions with their effective (possibly
overridden) outcome, one decision with its full evidence trail, and overrides.

Same rules as POST /agent: the organisation comes only from the API key, and every read and
write runs in a session scoped to it, so row-level security applies. A record of another
organisation answers 404, exactly like a record that does not exist.

The reviewer name on an override is supplied by the caller. The API key identifies an
organisation, not a person, so the name is recorded as given (limitation, README).
"""

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.api.agent import db_engine
from app.api.auth import require_org
from app.db import repo
from app.db.session import org_session
from app.models.decision import DecisionRecord
from app.review import (
    OverrideError,
    OverrideRequest,
    apply_override,
    check_chain,
    effective_record,
)

router = APIRouter()

Org = Annotated[str, Depends(require_org)]
Db = Annotated[Engine, Depends(db_engine)]


def _unavailable(exc: SQLAlchemyError) -> HTTPException:
    return HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE, f"dependency unavailable: {type(exc).__name__}"
    )


def _summary(engine_rec: DecisionRecord, eff: DecisionRecord, n_overrides: int) -> dict[str, Any]:
    s = eff.subject
    return {
        "record_id": eff.record_id,
        "run_id": eff.run_id,
        "line_id": s.line_id,
        "unit_id": s.unit_id,
        "charge_type": s.charge_type.value,
        "report_type": s.report_type.value,
        "amount_charged": str(eff.amount_charged),
        "amount_reimbursed": str(eff.amount_reimbursed),
        "currency": eff.currency,
        "engine_decision": engine_rec.decision.value,
        "decision": eff.decision.value,
        "status": eff.status.value,
        "evidence_status": eff.evidence_status.value,
        "reason_code": eff.reason_code.value if eff.reason_code else None,
        "rule_id": eff.rule_id,
        "confidence": str(eff.confidence),
        "claim_amount": str(eff.claim.amount) if eff.claim else None,
        "override_count": n_overrides,
        "reason": eff.reason,
    }


@router.get("/runs")
def list_runs(org: Org, engine: Db) -> list[dict[str, Any]]:
    try:
        with org_session(engine, org) as session:
            runs = repo.list_runs(session)
    except SQLAlchemyError as exc:
        raise _unavailable(exc) from None
    return [
        {
            "run_id": r.run_id,
            "decided_at": r.decided_at.isoformat(),
            "charges": r.charges,
            "counts": r.counts,
        }
        for r in runs
    ]


@router.get("/decisions")
def list_decisions(
    org: Org, engine: Db, run_id: Annotated[str | None, Query()] = None
) -> dict[str, Any]:
    """Decisions of one run (default: the newest run), with the effective outcome."""
    try:
        with org_session(engine, org) as session:
            runs = repo.list_runs(session)
            if not runs:
                return {"run": None, "items": []}
            run = next((r for r in runs if r.run_id == run_id), None) if run_id else runs[0]
            if run is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"no run {run_id!r}")
            decisions = repo.list_decisions(session, run.run_id)
            overrides = repo.overrides_by_record(session, [d.record_id for d in decisions])
    except SQLAlchemyError as exc:
        raise _unavailable(exc) from None
    items = []
    for d in decisions:
        ovs = overrides.get(d.record_id, [])
        items.append(_summary(d, effective_record(d, ovs), len(ovs)))
    return {
        "run": {
            "run_id": run.run_id,
            "decided_at": run.decided_at.isoformat(),
            "charges": run.charges,
            "counts": run.counts,
        },
        "items": items,
    }


@router.get("/decisions/{record_id}")
def get_decision(record_id: str, org: Org, engine: Db) -> dict[str, Any]:
    """One decision with everything a reviewer needs to check it: the charge, every
    upstream record considered (with whether its stored hash still verifies), the engine
    record, the override history and earlier decisions of the same charge line."""
    try:
        with org_session(engine, org) as session:
            rec = repo.get_decision(session, record_id)
            if rec is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"no decision {record_id!r}")
            overrides = repo.list_overrides(session, record_id)
            charge = repo.get_charge(session, rec.subject.line_id)
            evidence = []
            for c in rec.evidence_considered:
                found = repo.get_record_with_hash(session, c.agent, c.record_id)
                body, stored = found if found else (None, None)
                evidence.append(
                    {
                        "record_id": c.record_id,
                        "agent": c.agent,
                        "usable": c.usable,
                        "why": c.reason,
                        "cited": any(
                            x.kind == "evidence" and x.id == c.record_id and x.agent == c.agent
                            for x in rec.citations
                        ),
                        "hash_at_decision": c.content_hash,
                        "hash_matches_decision": stored == c.content_hash,
                        "record_hash_verifies": body.verify_hash() if body else False,
                        "record": body.model_dump(mode="json") if body else None,
                    }
                )
            history = []
            for d in repo.list_decisions_for_line(session, rec.subject.line_id):
                ovs = repo.list_overrides(session, d.record_id)
                history.append(_summary(d, effective_record(d, ovs), len(ovs)))
    except SQLAlchemyError as exc:
        raise _unavailable(exc) from None
    return {
        "record": effective_record(rec, overrides).model_dump(mode="json"),
        "engine_record": rec.model_dump(mode="json"),
        "overrides": [o.model_dump(mode="json") for o in overrides],
        "integrity_problems": check_chain(rec, overrides),
        "charge": charge.model_dump(mode="json") if charge else None,
        "evidence": evidence,
        "line_history": history,
    }


@router.post("/decisions/{record_id}/overrides", status_code=status.HTTP_201_CREATED)
def post_override(record_id: str, req: OverrideRequest, org: Org, engine: Db) -> dict[str, Any]:
    at = datetime.now(UTC)
    try:
        with org_session(engine, org) as session:
            rec, eff = apply_override(session, org, record_id, req, at)
    except OverrideError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    except SQLAlchemyError as exc:
        raise _unavailable(exc) from None
    return {"override": rec.model_dump(mode="json"), "record": eff.model_dump(mode="json")}

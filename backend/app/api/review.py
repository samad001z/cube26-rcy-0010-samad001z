"""Review endpoints for the operator UI: runs, decisions with their effective (possibly
overridden) outcome, one decision with its full evidence trail, and overrides.

Same rules as POST /agent: the organisation comes only from the API key, and every read and
write runs in a session scoped to it, so row-level security applies. A record of another
organisation answers 404, exactly like a record that does not exist.

The reviewer name on an override is supplied by the caller. The API key identifies an
organisation, not a person, so the name is recorded as given (limitation, README).
"""

from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.agent import db_engine
from app.api.auth import require_org
from app.core.rules import ChannelRules, EngineConfig, load_engine_config, load_rules
from app.db import repo
from app.db.session import org_session
from app.models.charge import Charge
from app.models.contract import EvidenceRecord
from app.models.decision import DecisionRecord
from app.models.vocab import ChargeType, Decision
from app.precheck import filing_window
from app.retrieval import custody_window
from app.review import (
    OverrideError,
    OverrideRecord,
    OverrideRequest,
    apply_override,
    check_chain,
    claim_refusal_now,
    effective_record,
)

router = APIRouter()

Org = Annotated[str, Depends(require_org)]
Db = Annotated[Engine, Depends(db_engine)]


def _unavailable(exc: SQLAlchemyError) -> HTTPException:
    return HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE, f"dependency unavailable: {type(exc).__name__}"
    )


def _summary(
    engine_rec: DecisionRecord, overrides: list[OverrideRecord], problems: list[str]
) -> dict[str, Any]:
    eff = effective_record(engine_rec, overrides)
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
        "override_count": len(overrides),
        "integrity_problems": problems,
        "reason": eff.reason,
    }


def _problems(session: Session, rec: DecisionRecord, overrides: list[OverrideRecord]) -> list[str]:
    if not overrides:
        return check_chain(rec, overrides)
    return check_chain(rec, overrides) + repo.override_column_problems(session, rec.record_id)


def _earlier_override(
    found: tuple[OverrideRecord, datetime] | None, current: DecisionRecord, current_at: datetime
) -> dict[str, Any] | None:
    """The newest human override of the same charge line, when it was made on an earlier run.
    Overrides attach to one decision, so a re-run does not carry them; the list shows this
    one so the newest human judgement stays visible. When browsing an older run, an override
    on a later run is not "earlier" and nothing is shown (the line history lists them all)."""
    if found is None:
        return None
    o, overridden_at = found
    if o.decision_record_id == current.record_id or overridden_at >= current_at:
        return None
    return {
        "record_id": o.decision_record_id,
        "decision": o.override.new_decision,
        "reviewer": o.override.reviewer,
        "at": o.override.at.isoformat(),
        "reason": o.override.reason,
    }


def _iso(dt: datetime) -> str:
    """UTC timestamps in the same form as the records' own JSON (trailing Z)."""
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _custody_window(
    charge: Charge | None, body: EvidenceRecord | None, rec: DecisionRecord, cfg: EngineConfig
) -> dict[str, Any] | None:
    """The window in which this pod's records can speak to the charge, as the engine used it.
    Computed only when the engine config and the stored charge are the ones the decision was
    made with (same hashes); otherwise null, and the stored `why` text is the record of it."""
    if (
        charge is None
        or body is None
        or cfg.config_hash != rec.config_hash
        or charge.compute_hash() != rec.subject.charge_content_hash
    ):
        return None
    rel = cfg.charge_types[charge.charge_type].pods.get(body.agent)  # type: ignore[call-overload]
    if rel is None:
        return None
    start, end = custody_window(charge, rel)
    return {
        "start": _iso(start),
        "end": _iso(end),  # exclusive
        "basis": rel.window,
        "anchor": "posted_date",
        "posted_date": charge.posted_date.isoformat(),
        "captured_inside": start <= body.captured_at < end,
    }


_STATE = {"open": "open", "passed": "passed", "not_open": "not_yet_open", "unknown": "not_verified"}


def _deadline(
    rec: DecisionRecord, charge: Charge | None, rules: ChannelRules, today: date
) -> dict[str, Any]:
    """The filing deadline judged today from the sourced rules (open, passed, not yet open,
    or not verified when no rule is sourced), plus what the decision's own check said at the
    run's as-of date. Today is what a reviewer acts on; a run may be days old."""
    at_decision = next((x for x in rec.checks if x.check_key == "within_filing_window"), None)
    decided = {
        "verdict": at_decision.verdict.value if at_decision else None,
        "detail": at_decision.detail if at_decision else None,
    }
    if charge is None or charge.compute_hash() != rec.subject.charge_content_hash:
        return {
            "status": "unknown",
            "as_of": today.isoformat(),
            "opens": None,
            "deadline": None,
            "detail": "the charge is not in the store as decided",
            "at_decision": decided,
        }
    fw = filing_window(charge, rules, today)
    return {
        "status": _STATE[fw.state],
        "as_of": today.isoformat(),
        "opens": fw.opens.isoformat() if fw.opens else None,
        "deadline": fw.deadline.isoformat() if fw.deadline else None,
        "detail": fw.detail,
        "at_decision": decided,
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
    org: Org,
    engine: Db,
    run_id: Annotated[str | None, Query()] = None,
    decision: Annotated[Decision | None, Query(description="effective decision")] = None,
    charge_type: Annotated[ChargeType | None, Query()] = None,
    rule_id: Annotated[str | None, Query(max_length=64)] = None,
) -> dict[str, Any]:
    """Decisions of one run (default: the newest run), with the effective outcome.

    Filters narrow `items` only; `counts` (effective decisions) and `facets` always describe
    the whole run, so the page can show totals and the available filter values."""
    try:
        with org_session(engine, org) as session:
            runs = repo.list_runs(session)
            if not runs:
                return {"run": None, "counts": {}, "facets": {}, "filters": {}, "items": []}
            run = next((r for r in runs if r.run_id == run_id), None) if run_id else runs[0]
            if run is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"no run {run_id!r}")
            decisions = repo.list_decisions(session, run.run_id)
            overrides = repo.overrides_by_record(session, [d.record_id for d in decisions])
            newest = repo.newest_override_by_line(session, [d.subject.line_id for d in decisions])
            items = []
            for d in decisions:
                ovs = overrides.get(d.record_id, [])
                item = _summary(d, ovs, _problems(session, d, ovs))
                item["earlier_override"] = _earlier_override(
                    newest.get(d.subject.line_id), d, run.decided_at
                )
                items.append(item)
    except SQLAlchemyError as exc:
        raise _unavailable(exc) from None
    counts = {d.value: sum(1 for i in items if i["decision"] == d.value) for d in Decision}
    facets = {
        "charge_type": sorted({i["charge_type"] for i in items}),
        "rule_id": sorted({i["rule_id"] for i in items}),
    }
    shown = [
        i
        for i in items
        if (decision is None or i["decision"] == decision.value)
        and (charge_type is None or i["charge_type"] == charge_type.value)
        and (rule_id is None or i["rule_id"] == rule_id)
    ]
    return {
        "run": {
            "run_id": run.run_id,
            "decided_at": run.decided_at.isoformat(),
            "charges": run.charges,
            "counts": run.counts,  # the engine's decisions, before any override
        },
        "counts": counts,
        "facets": facets,
        "filters": {
            "decision": decision.value if decision else None,
            "charge_type": charge_type.value if charge_type else None,
            "rule_id": rule_id,
        },
        "items": shown,
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
            cfg = load_engine_config()
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
                        "captured_at": _iso(body.captured_at) if body else None,
                        "custody_window": _custody_window(charge, body, rec, cfg),
                        "hash_at_decision": c.content_hash,
                        "hash_matches_decision": stored == c.content_hash,
                        "record_hash_verifies": body.verify_hash() if body else False,
                        "record": body.model_dump(mode="json") if body else None,
                    }
                )
            history = []
            line_decisions = repo.list_decisions_for_line(session, rec.subject.line_id)
            for d in line_decisions:
                ovs = repo.list_overrides(session, d.record_id)
                history.append(_summary(d, ovs, _problems(session, d, ovs)))
            problems = _problems(session, rec, overrides)
            is_newest = line_decisions[-1].record_id == rec.record_id
            rules = load_rules()
            today = datetime.now(UTC).date()
            claim_blocked = claim_refusal_now(session, rec, cfg, rules, today)
            deadline = _deadline(rec, charge, rules, today)
    except SQLAlchemyError as exc:
        raise _unavailable(exc) from None
    return {
        "record": effective_record(rec, overrides).model_dump(mode="json"),
        "engine_record": rec.model_dump(mode="json"),
        "overrides": [o.model_dump(mode="json") for o in overrides],
        "integrity_problems": problems,
        # Whether the override form may be used, and why CLAIM is not offered (D-021).
        "overridable": is_newest,
        "claim_refusal": claim_blocked,
        "deadline": deadline,
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

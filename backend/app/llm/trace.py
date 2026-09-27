"""The decision trace: everything an explanation may say, taken from the decision record.

IDs that change on every run (run_id, record_id, decision time) are left out, so the same
charge and evidence give the same trace, and the explanation cache hits on a re-run."""

from typing import Any

from app.core.hashing import content_hash
from app.models.decision import DecisionRecord


def _s(v: object) -> str | None:
    return None if v is None else str(v)


def build_trace(d: DecisionRecord) -> dict[str, Any]:
    s = d.subject
    return {
        "line_id": s.line_id,
        "unit_id": s.unit_id,
        "charge_type": s.charge_type.value,
        "report_type": s.report_type.value,
        "fba_shipment_id": s.fba_shipment_id,
        "order_id": s.order_id,
        "defect_category": s.defect_category,
        "decision": d.decision.value,
        "status": d.status.value,
        "evidence_status": d.evidence_status.value,
        "reason_code": d.reason_code.value if d.reason_code else None,
        "rule_id": d.rule_id,
        "reason": d.reason,
        "next_action": d.next_action,
        "warnings": list(d.warnings),
        "amount_charged": str(d.amount_charged),
        "amount_reimbursed": str(d.amount_reimbursed),
        "currency": d.currency,
        "claim": (
            {"amount": str(d.claim.amount), "computation": list(d.claim.computation)}
            if d.claim
            else None
        ),
        "routing_confidence": str(d.confidence),
        "coverage": _s(d.coverage),
        "checks": [
            {"check_key": c.check_key, "verdict": c.verdict.value, "detail": c.detail}
            for c in d.checks
        ],
        "cited": [
            {
                "kind": c.kind,
                "id": c.id,
                "agent": c.agent,
                "role": c.role,
                "check_keys": c.check_keys,
            }
            for c in d.citations
        ],
        "records_read": [
            {"agent": r.agent, "record_id": r.record_id, "usable": r.usable, "why": r.reason}
            for r in d.evidence_considered
        ],
    }


def trace_hash(trace: dict[str, Any], prompt_version: str, model_id: str | None) -> str:
    return content_hash({"trace": trace, "prompt_version": prompt_version, "model": model_id})


def corpus(value: Any) -> str:
    """Every key and scalar of the trace as text: what an explanation may quote."""
    out: list[str] = []

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            for k, x in v.items():
                out.append(str(k))
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif v is not None:
            out.append(str(v))

    walk(value)
    return "\n".join(out)

"""Select the upstream records relevant to a charge and place each in or out of its
custody window. No verdicts here.

Relevance (which pods can speak to a charge type) and custody windows come from
config/engine.yaml. Every record from a relevant pod is returned with the reason it is in
or out of scope and in or out of window, so the decision trace can show what was read and
why it was or was not used.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

from app.core.rules import EngineConfig, PodRelevance
from app.models.charge import Charge
from app.models.contract import EvidenceRecord
from app.resolution import Resolution


@dataclass(frozen=True)
class Candidate:
    record: EvidenceRecord
    in_scope: bool
    in_window: bool
    reason: str

    @property
    def usable(self) -> bool:
        return self.in_scope and self.in_window


def _posted_start(charge: Charge) -> datetime:
    return datetime.combine(charge.posted_date, time.min, tzinfo=UTC)


def custody_window(charge: Charge, rel: PodRelevance) -> tuple[datetime, datetime]:
    """[start, end) in UTC for records that can speak to this charge."""
    posted = _posted_start(charge)
    day = timedelta(days=1)
    if rel.window == "before_posting":
        assert rel.max_days_before is not None
        return posted - rel.max_days_before * day, posted
    if rel.window == "after_posting":
        assert rel.max_days_after is not None
        return posted, posted + (rel.max_days_after + 1) * day
    assert rel.max_days_before is not None and rel.max_days_after is not None
    return posted - rel.max_days_before * day, posted + (rel.max_days_after + 1) * day


def _scope(charge: Charge, record: EvidenceRecord, rel: PodRelevance) -> str | None:
    """None if in scope, else the reason it is not."""
    for key in rel.match_keys:
        ours, theirs = getattr(charge, key), getattr(record.subject, key)
        if ours is None:
            return f"charge has no {key} to match {record.record_id}"
        if theirs is None:
            return f"{record.record_id} has no {key}"
        if ours != theirs:
            return f"{key} differs: charge {ours}, {record.record_id} {theirs}"
    return None


def in_custody_window(charge: Charge, record: EvidenceRecord, cfg: EngineConfig) -> bool:
    rel = cfg.charge_types[charge.charge_type].pods.get(record.agent)  # type: ignore[call-overload]
    if rel is None:
        return False
    start, end = custody_window(charge, rel)
    return start <= record.captured_at < end


def retrieve(charge: Charge, resolution: Resolution, cfg: EngineConfig) -> tuple[Candidate, ...]:
    pods = cfg.charge_types[charge.charge_type].pods
    out: list[Candidate] = []
    for r in resolution.records:
        rel = pods.get(r.agent)  # type: ignore[call-overload]
        if rel is None:
            continue
        start, end = custody_window(charge, rel)
        scope_problem = _scope(charge, r, rel)
        in_window = start <= r.captured_at < end
        window_text = (
            f"captured {r.captured_at:%Y-%m-%dT%H:%MZ} "
            f"{'inside' if in_window else 'outside'} custody window "
            f"[{start:%Y-%m-%d}, {end:%Y-%m-%d}) ({rel.window})"
        )
        reason = window_text if scope_problem is None else f"{scope_problem}; {window_text}"
        out.append(Candidate(r, scope_problem is None, in_window, reason))
    return tuple(out)

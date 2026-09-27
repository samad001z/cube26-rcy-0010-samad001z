"""Adds an explanation to each decision (D-022).

With LLM_ENABLED=false, or on a fail-open record, the standard template is used and no
model is called. Otherwise: cache lookup by trace hash, else exactly one model call; the
text is validated against the trace; any failure (config, call, timeout, rejected text)
falls back to the template with `fallback_reason`. The decision itself is never changed
here: only `explanation` and, when a model's text is used, `model_version`."""

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db import repo
from app.llm.client import LLMError, LLMProvider, LLMResponse, make_provider
from app.llm.config import LLMConfig, LLMConfigError, llm_config
from app.llm.prompt import PROMPT_VERSION, build_request
from app.llm.template import template_text
from app.llm.trace import build_trace, trace_hash
from app.llm.validate import ExplanationRejected, validate_explanation
from app.models.decision import DecisionRecord, Explanation
from app.models.vocab import RecordStatus

MTOK = Decimal(1_000_000)
COST_QUANTUM = Decimal("0.000001")
PRICE_NOT_CONFIGURED = (
    "price not configured (LLM_PRICE_INPUT_USD_PER_MTOK, LLM_PRICE_OUTPUT_USD_PER_MTOK)"
)


def estimate_cost(
    cfg: LLMConfig | None, input_tokens: int, output_tokens: int
) -> tuple[Decimal | None, str | None]:
    """Token-based estimate in USD from operator-supplied prices; None when not configured."""
    if cfg is None or cfg.price_input_per_mtok is None or cfg.price_output_per_mtok is None:
        return None, PRICE_NOT_CONFIGURED
    cost = (
        Decimal(input_tokens) * cfg.price_input_per_mtok
        + Decimal(output_tokens) * cfg.price_output_per_mtok
    ) / MTOK
    return cost.quantize(COST_QUANTUM), None


@dataclass
class Explainer:
    provider: LLMProvider | None = None
    cfg: LLMConfig | None = None
    # Why the model is not used at all (bad config); None when LLM is simply off.
    unavailable: str | None = None
    calls: int = field(default=0)  # model calls made, for tests and the run summary
    # A wall-clock deadline (time.monotonic()) for model calls across this run (D-022,
    # guardian finding 4): once passed, remaining charges get the template with no further
    # call, so one slow run cannot exceed the deploy's own request timeout and roll back
    # every charge, including already-decided pending ones (rule 5). None means no budget
    # (LLM off, or misconfigured).
    deadline: float | None = None

    @classmethod
    def from_settings(cls, s: Settings) -> "Explainer":
        if not s.llm_enabled:
            return cls()
        try:
            cfg = llm_config(s)
            deadline = time.monotonic() + cfg.run_budget_s
            return cls(provider=make_provider(cfg), cfg=cfg, deadline=deadline)
        except (LLMConfigError, LLMError) as exc:
            return cls(unavailable=f"model not configured: {exc}")

    # -- building blocks ---------------------------------------------------------------

    def _template(
        self,
        trace: dict[str, object],
        thash: str,
        fallback: str | None,
        resp: LLMResponse | None = None,
    ) -> Explanation:
        cost, note = (None, None)
        if resp is not None:  # a call was made and paid for, even though its text is not used
            cost, note = estimate_cost(self.cfg, resp.input_tokens, resp.output_tokens)
        return Explanation(
            text=template_text(trace),
            source="template",
            prompt_version=PROMPT_VERSION,
            trace_hash=thash,
            model_id=resp.model_id if resp else None,
            latency_ms=resp.latency_ms if resp else None,
            input_tokens=resp.input_tokens if resp else None,
            output_tokens=resp.output_tokens if resp else None,
            cost_estimate_usd=cost,
            cost_note=note,
            fallback_reason=fallback,
        )

    def _cached(self, session: Session, thash: str) -> repo.CachedExplanation | None:
        try:
            with session.begin_nested():
                return repo.get_cached_explanation(session, thash)
        except SQLAlchemyError:
            return None  # a cache problem only costs a model call

    def _store(self, session: Session, org: str, c: repo.CachedExplanation) -> None:
        try:
            with session.begin_nested():
                repo.insert_cached_explanation(session, org, c, datetime.now(UTC))
        except SQLAlchemyError:
            pass  # next run makes the call again

    # -- the one entry point -------------------------------------------------------------

    def explanation_for(self, session: Session | None, d: DecisionRecord) -> Explanation:
        trace = build_trace(d)
        if self.provider is None:
            return self._template(trace, trace_hash(trace, PROMPT_VERSION, None), self.unavailable)
        thash = trace_hash(trace, PROMPT_VERSION, self.provider.model_id)
        if d.status == RecordStatus.PENDING:
            return self._template(trace, thash, "not sent to the model: the record is pending")

        if session is not None:
            started = time.perf_counter()
            hit = self._cached(session, thash)
            if hit is not None:
                try:
                    text = validate_explanation(_as_json(hit.explanation), trace)
                    return Explanation(
                        text=text,
                        source="model",
                        prompt_version=hit.prompt_version,
                        trace_hash=thash,
                        model_id=hit.model_id,
                        cached=True,
                        latency_ms=round((time.perf_counter() - started) * 1000),
                        input_tokens=0,
                        output_tokens=0,
                        cost_estimate_usd=Decimal("0.000000"),
                    )
                except ExplanationRejected:
                    pass  # validator tightened since it was cached: ask the model again

        if self.deadline is not None and time.monotonic() > self.deadline:
            return self._template(trace, thash, "time budget exhausted for this run")

        self.calls += 1
        try:
            resp = self.provider.generate(build_request(trace))
        except LLMError as exc:
            return self._template(trace, thash, f"model call failed: {exc}")
        try:
            text = validate_explanation(resp.text, trace)
        except ExplanationRejected as exc:
            return self._template(trace, thash, f"model text rejected: {exc}", resp)
        if session is not None:
            self._store(
                session,
                d.organization_id,
                repo.CachedExplanation(
                    trace_hash=thash,
                    prompt_version=PROMPT_VERSION,
                    model_id=resp.model_id,
                    explanation=text,
                    input_tokens=resp.input_tokens,
                    output_tokens=resp.output_tokens,
                ),
            )
        cost, note = estimate_cost(self.cfg, resp.input_tokens, resp.output_tokens)
        return Explanation(
            text=text,
            source="model",
            prompt_version=PROMPT_VERSION,
            trace_hash=thash,
            model_id=resp.model_id,
            latency_ms=resp.latency_ms,
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
            cost_estimate_usd=cost,
            cost_note=note,
        )

    def explain(self, session: Session | None, d: DecisionRecord) -> DecisionRecord:
        """The decision with its explanation, re-hashed. Nothing else changes."""
        try:
            e = self.explanation_for(session, d)
        except Exception as exc:  # an explanation must never cost a decision
            trace = build_trace(d)
            e = self._template(
                trace,
                trace_hash(trace, PROMPT_VERSION, None),
                f"explanation step failed: {type(exc).__name__}: {exc}",
            )
        update: dict[str, object] = {"explanation": e}
        if e.source == "model":
            update["model_version"] = e.model_id
        return d.model_copy(update=update).with_hash()


def _as_json(text: str) -> str:
    return json.dumps({"explanation": text})

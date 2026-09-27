"""LLM layer through the real pipeline and Postgres (D-022): one model call per decision,
the cache on a re-run, what is stored on the record, and that decisions do not move."""

from decimal import Decimal
from typing import Any

from app.db import repo
from app.db.session import org_session
from app.llm.client import LLMRequest, LLMResponse
from app.llm.config import LLMConfig
from app.llm.explain import Explainer
from app.llm.prompt import DECISION_WORDS
from app.models.vocab import RecordStatus
from app.pipeline import run_org
from tests.conftest import AS_OF
from tests.test_pipeline_db import _load_synthetic

ORG = "org_test_llm"


class TraceEcho:
    """A provider that answers from the trace in the prompt, like a well-behaved model."""

    model_id = "fixture-model"

    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
        import json

        self.requests.append(request)
        trace: dict[str, Any] = json.loads(request.prompt.split("TRACE:\n", 1)[1])
        text = (
            f"{DECISION_WORDS[trace['decision']]}. Rule {trace['rule_id']} fired for "
            f"{trace['line_id']} on unit {trace['unit_id']}."
        )
        return LLMResponse(json.dumps({"explanation": text}), "fixture-model-001", 900, 40, 12)


def _cfg() -> LLMConfig:
    return LLMConfig(
        provider="vertex",
        project="proj-test",
        location="europe-west4",
        model="fixture-model",
        credentials_file=None,
        timeout_s=5,
        max_output_tokens=256,
        price_input_per_mtok=Decimal("0.10"),
        price_output_per_mtok=Decimal("0.40"),
    )


def test_one_call_per_decision_then_the_cache_on_a_rerun(app_engine, loaded):
    _load_synthetic(app_engine, ORG)
    provider = TraceEcho()
    explainer = Explainer(provider=provider, cfg=_cfg())
    baseline = {d.subject.line_id: d for d in run_org(app_engine, ORG, AS_OF).decisions}

    first = run_org(app_engine, ORG, AS_OF, explainer=explainer)
    assert len(provider.requests) == len(first.decisions) == 2  # exactly one call each
    for d in first.decisions:
        x = d.explanation
        assert x is not None and x.source == "model" and not x.cached
        assert d.model_version == "fixture-model-001"
        assert (x.input_tokens, x.output_tokens, x.latency_ms) == (900, 40, 12)
        # (900 * 0.10 + 40 * 0.40) / 1e6
        assert x.cost_estimate_usd == Decimal("0.000106")
        b = baseline[d.subject.line_id]
        assert (d.decision, d.rule_id, d.claim) == (b.decision, b.rule_id, b.claim)
        assert d.citations == b.citations

    second = run_org(app_engine, ORG, AS_OF, explainer=explainer)
    assert len(provider.requests) == 2  # no new call: every trace was cached
    for d in second.decisions:
        x = d.explanation
        assert x is not None and x.source == "model" and x.cached
        assert (x.input_tokens, x.output_tokens, x.cost_estimate_usd) == (0, 0, Decimal("0.000000"))

    # What was stored is what was returned, and its hash still verifies.
    with org_session(app_engine, ORG) as s:
        stored = {d.record_id: d for d in repo.list_decisions(s, second.run_id)}
    for d in second.decisions:
        assert stored[d.record_id] == d and stored[d.record_id].verify_hash()


def test_llm_off_stores_the_template_and_no_model_version(app_engine, loaded):
    org = "org_test_llm_off"
    _load_synthetic(app_engine, org)
    for d in run_org(app_engine, org, AS_OF, explainer=Explainer()).decisions:
        assert d.explanation is not None and d.explanation.source == "template"
        assert d.explanation.fallback_reason is None and d.model_version is None
        assert d.status == RecordStatus.FINAL and d.verify_hash()

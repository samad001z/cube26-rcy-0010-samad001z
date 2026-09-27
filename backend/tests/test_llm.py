"""LLM layer (D-022), without a database or the network: settings, the Vertex adapter over
recorded-shape responses, the validator, fallback to the template, cost, and hashing."""

import json
import socket
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from google import genai
from google.genai import types
from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.config import REPO_ROOT, Settings
from app.llm import vertex
from app.llm.client import LLMError, LLMRequest, LLMResponse
from app.llm.config import LLMConfig, LLMConfigError, llm_config
from app.llm.explain import PRICE_NOT_CONFIGURED, Explainer, estimate_cost
from app.llm.prompt import PROMPT_VERSION, build_request
from app.llm.template import template_text
from app.llm.trace import build_trace, corpus, trace_hash
from app.llm.validate import ExplanationRejected, validate_explanation
from app.models.decision import DecisionRecord
from app.models.vocab import Decision, RecordStatus
from tests.factories import charge, check, record
from tests.test_engine import run

FIXTURES = Path(__file__).parent / "fixtures" / "llm"
BASE = {
    "database_url": "postgresql+psycopg://x@localhost/x",
    "migration_database_url": "postgresql+psycopg://x@localhost/x",
    "attachment_key_secret": "s",
}


def _settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, **{**BASE, **kw})


def _enabled(**kw: Any) -> Settings:
    defaults: dict[str, Any] = {
        "llm_enabled": True,
        "llm_provider": "vertex",
        "google_cloud_project": "proj-test",
        "google_cloud_location": "europe-west4",
        "llm_model": "fixture-model",
    }
    return _settings(**{**defaults, **kw})


def _cfg(**kw: Any) -> LLMConfig:
    return replace(llm_config(_enabled()), **kw)


def _claim() -> DecisionRecord:
    """CLAIM: label defect stated, prep shows both label checks passed before posting."""
    c = charge("L-1", defect_category="label")
    r = record(
        "PRP-1",
        checks=[check("fnsku_label_placement", "PASS"), check("original_barcode_covered", "PASS")],
    )
    d = run(c, [r])
    assert d.decision == Decision.CLAIM, d.reason
    return d


def _fixture(name: str) -> types.GenerateContentResponse:
    data = json.loads((FIXTURES / f"{name}.json").read_text())
    return types.GenerateContentResponse.model_validate(data["response"])


class FakeModels:
    def __init__(self, answer: types.GenerateContentResponse | Exception):
        self.answer = answer
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, **kw: Any) -> types.GenerateContentResponse:
        self.calls.append(kw)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


class FakeClient:
    def __init__(self, answer: types.GenerateContentResponse | Exception):
        self.models = FakeModels(answer)


def _explainer(answer: types.GenerateContentResponse | Exception, **cfg: Any) -> Explainer:
    c = _cfg(**cfg)
    return Explainer(provider=vertex.VertexProvider(c, client=FakeClient(answer)), cfg=c)


def _model_json(text: str) -> str:
    return json.dumps({"explanation": text})


# -- settings ---------------------------------------------------------------------------


def test_disabled_by_default_makes_no_provider():
    e = Explainer.from_settings(_settings())
    assert e.provider is None and e.unavailable is None


@pytest.mark.parametrize(
    ("field", "name"),
    [
        ("llm_provider", "LLM_PROVIDER"),
        ("google_cloud_project", "GOOGLE_CLOUD_PROJECT"),
        ("google_cloud_location", "GOOGLE_CLOUD_LOCATION"),
        ("llm_model", "LLM_MODEL"),
    ],
)
def test_enabled_requires_each_setting(field, name):
    with pytest.raises(LLMConfigError, match=name):
        llm_config(_enabled(**{field: None}))


@pytest.mark.parametrize("provider", ["anthropic", "bedrock", "openai"])
def test_only_vertex_is_implemented(provider):
    with pytest.raises(LLMConfigError, match=r"not implemented|unknown"):
        llm_config(_enabled(llm_provider=provider))


def test_credentials_file_inside_the_repo_is_refused(tmp_path):
    inside = REPO_ROOT / "backend" / "pyproject.toml"  # any existing file in the repo
    with pytest.raises(LLMConfigError, match="inside the repository"):
        llm_config(_enabled(google_application_credentials=str(inside)))
    outside = tmp_path / "key.json"
    outside.write_text("{}")
    cfg = llm_config(_enabled(google_application_credentials=str(outside)))
    assert cfg.credentials_file == outside
    with pytest.raises(LLMConfigError, match="not found"):
        llm_config(_enabled(google_application_credentials=str(tmp_path / "missing.json")))


def test_misconfigured_falls_back_to_template_with_reason():
    e = Explainer.from_settings(_enabled(llm_model=""))
    assert e.provider is None and e.unavailable and "LLM_MODEL" in e.unavailable
    out = e.explain(None, _claim())
    assert out.explanation is not None and out.explanation.source == "template"
    assert "LLM_MODEL" in (out.explanation.fallback_reason or "")


# -- Vertex adapter ----------------------------------------------------------------------


def test_vertex_client_uses_vertexai_project_location_timeout_and_no_retries(monkeypatch):
    seen: dict[str, Any] = {}
    monkeypatch.setattr(genai, "Client", lambda **kw: seen.update(kw) or object())
    vertex._client(_cfg(timeout_s=7))
    assert seen["vertexai"] is True
    assert (seen["project"], seen["location"]) == ("proj-test", "europe-west4")
    assert seen["credentials"] is None  # no key file: Application Default Credentials
    assert seen["http_options"].timeout == 7000
    assert seen["http_options"].retry_options.attempts == 1


def test_vertex_request_uses_configured_model_json_and_temperature_zero():
    fake = FakeClient(_fixture("claim_ok"))
    p = vertex.VertexProvider(_cfg(max_output_tokens=321), client=fake)
    p.generate(build_request(build_trace(_claim())))
    (call,) = fake.models.calls
    assert call["model"] == "fixture-model"
    cfg = call["config"]
    assert cfg.temperature == 0
    assert cfg.max_output_tokens == 321
    assert cfg.response_mime_type == "application/json"
    assert cfg.response_json_schema["required"] == ["explanation"]


def test_vertex_reads_tokens_including_thinking_and_the_served_model():
    resp = vertex.VertexProvider(_cfg(), client=FakeClient(_fixture("claim_ok"))).generate(
        LLMRequest("s", "p", {})
    )
    assert (resp.input_tokens, resp.output_tokens) == (1234, 56 + 100)
    assert resp.model_id == "fixture-model-001"
    assert resp.latency_ms >= 0


def test_vertex_empty_text_and_sdk_errors_become_llm_error():
    with pytest.raises(LLMError, match="MAX_TOKENS"):
        vertex.VertexProvider(_cfg(), client=FakeClient(_fixture("max_tokens_empty"))).generate(
            LLMRequest("s", "p", {})
        )
    with pytest.raises(LLMError, match="ConnectionError"):
        vertex.VertexProvider(_cfg(), client=FakeClient(ConnectionError("down"))).generate(
            LLMRequest("s", "p", {})
        )


# -- explanation flow --------------------------------------------------------------------


def _same_decision(a: DecisionRecord, b: DecisionRecord) -> None:
    fields = ("decision", "rule_id", "reason", "claim", "citations", "checks", "status")
    for f in (*fields, "confidence"):
        assert getattr(a, f) == getattr(b, f), f


def test_model_explanation_is_used_recorded_and_hashed():
    d = _claim()
    e = _explainer(
        _fixture("claim_ok"),
        price_input_per_mtok=Decimal("0.30"),
        price_output_per_mtok=Decimal("2.50"),
    )
    out = e.explain(None, d)
    x = out.explanation
    assert x is not None and x.source == "model" and x.fallback_reason is None
    assert x.text.startswith("CLAIM. Prep record PRP-1")
    assert out.model_version == x.model_id == "fixture-model-001"
    assert (x.input_tokens, x.output_tokens) == (1234, 156)
    # (1234 * 0.30 + 156 * 2.50) / 1e6 = 0.0007602
    assert x.cost_estimate_usd == Decimal("0.000760")
    assert x.prompt_version == PROMPT_VERSION
    assert x.trace_hash == trace_hash(build_trace(d), PROMPT_VERSION, "fixture-model")
    assert out.verify_hash() and out.content_hash != d.content_hash
    _same_decision(d, out)
    assert e.calls == 1


def test_cost_is_null_without_prices():
    out = _explainer(_fixture("claim_ok")).explain(None, _claim())
    assert out.explanation is not None
    assert out.explanation.cost_estimate_usd is None
    assert out.explanation.cost_note == PRICE_NOT_CONFIGURED
    assert estimate_cost(None, 1, 1) == (None, PRICE_NOT_CONFIGURED)


def test_failed_call_falls_back_to_template_and_keeps_the_decision():
    d = _claim()
    out = _explainer(ConnectionError("unreachable")).explain(None, d)
    x = out.explanation
    assert x is not None and x.source == "template"
    assert x.fallback_reason and x.fallback_reason.startswith("model call failed")
    assert x.text == template_text(build_trace(d))
    assert out.model_version is None and out.verify_hash()
    _same_decision(d, out)


def test_rejected_text_falls_back_but_records_the_paid_call():
    d = _claim()
    out = _explainer(
        _fixture("claim_invented_amount"),
        price_input_per_mtok=Decimal("1"),
        price_output_per_mtok=Decimal("1"),
    ).explain(None, d)
    x = out.explanation
    assert x is not None and x.source == "template"
    assert x.fallback_reason == "model text rejected: number 7.35 is not in the trace"
    assert (x.input_tokens, x.output_tokens, x.model_id) == (1200, 40, "fixture-model-001")
    assert x.cost_estimate_usd == Decimal("0.001240")
    assert out.model_version is None
    _same_decision(d, out)


def test_unexpected_error_in_the_explanation_step_keeps_the_decision():
    class Broken:
        model_id = "fixture-model"

        def generate(self, request: LLMRequest) -> LLMResponse:
            raise KeyError("bug")

    d = _claim()
    out = Explainer(provider=Broken(), cfg=_cfg()).explain(None, d)
    assert out.explanation is not None and out.explanation.source == "template"
    assert "explanation step failed: KeyError" in (out.explanation.fallback_reason or "")
    _same_decision(d, out)


def test_pending_record_is_never_sent_to_the_model():
    d = _claim().model_copy(update={"status": RecordStatus.PENDING, "decision": Decision.REVIEW})
    e = _explainer(_fixture("claim_ok"))
    out = e.explain(None, d)
    assert e.calls == 0
    assert out.explanation is not None and out.explanation.source == "template"


def test_disabled_explainer_never_calls_and_has_no_fallback_reason():
    out = Explainer().explain(None, _claim())
    assert out.explanation is not None
    assert (out.explanation.source, out.explanation.fallback_reason) == ("template", None)
    assert out.model_version is None


def test_record_stored_before_explanations_still_verifies():
    d = _claim()  # hashed by the engine, no explanation
    body = d.model_dump(mode="json")
    assert body.pop("explanation") is None
    again = DecisionRecord.model_validate(body)
    assert again.verify_hash()


# -- validator ---------------------------------------------------------------------------

GOOD = (
    "CLAIM. Prep record PRP-1 shows fnsku_label_placement and original_barcode_covered "
    "passed before the fee on L-1 was posted. The full 2.00 USD can be claimed."
)


def test_good_text_passes():
    assert validate_explanation(_model_json(GOOD), build_trace(_claim())) == GOOD


@pytest.mark.parametrize(
    ("text", "why"),
    [
        (GOOD.replace("PRP-1", "PRP-9"), "ID PRP-9 is not in the trace"),
        (GOOD.replace("2.00", "2.50"), "number 2.50 is not in the trace"),
        (GOOD + " It was posted 2026-07-19.", "date 2026-07-19 is not in the trace"),
        (GOOD + " It was posted 18 Jul 2026.", "not YYYY-MM-DD"),
        (GOOD + " It was posted 07/18/2026.", "not YYYY-MM-DD"),
        (GOOD.replace("CLAIM.", "REVIEW."), "decision words"),
        (GOOD + " Otherwise REVIEW it.", "decision words"),
        (GOOD.replace("CLAIM. ", ""), "decision words"),
        (GOOD + " The engine is highly accurate.", "forbidden phrase"),
        (GOOD + " See https://example.com.", "link"),
        (GOOD.replace("fnsku_label_placement", "weight_check"), "name weight_check"),
        ("CLAIM.", "length"),
        ("CLAIM. " + "x" * 1300, "length"),
    ],
)
def test_validator_rejects(text, why):
    with pytest.raises(ExplanationRejected, match=why):
        validate_explanation(_model_json(text), build_trace(_claim()))


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        json.dumps(["CLAIM"]),
        json.dumps({"explanation": GOOD, "extra": 1}),
        json.dumps({"explanation": 3}),
    ],
)
def test_validator_rejects_malformed_answers(raw):
    with pytest.raises(ExplanationRejected):
        validate_explanation(raw, build_trace(_claim()))


TRACE = build_trace(_claim())
SOURCE_NUMBERS = corpus(TRACE)


@settings(max_examples=200, deadline=None)
@given(st.decimals(min_value=0, max_value=100000, places=3, allow_nan=False, allow_infinity=False))
def test_any_number_not_in_the_trace_is_rejected(n):
    s = str(n)
    if s in SOURCE_NUMBERS:
        return
    with pytest.raises(ExplanationRejected, match="number"):
        validate_explanation(_model_json(f"{GOOD} Also {s} USD."), TRACE)


def test_do_not_claim_wording_is_its_own_decision():
    d = _claim().model_copy(update={"decision": Decision.DO_NOT_CLAIM, "claim": None})
    tr = build_trace(d)
    ok = "DO NOT CLAIM. Prep record PRP-1 was read for L-1 before the fee was posted."
    assert validate_explanation(_model_json(ok), tr) == ok
    with pytest.raises(ExplanationRejected, match="decision words"):
        validate_explanation(_model_json(ok + " A CLAIM is not possible."), tr)


def test_template_uses_only_trace_facts():
    tr = build_trace(_claim())
    text = template_text(tr)
    assert text.startswith("CLAIM. ")
    assert validate_explanation(_model_json(text), tr) == text


# -- no network --------------------------------------------------------------------------


def test_tests_cannot_reach_the_network():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(RuntimeError, match="network access blocked"):
            s.connect(("8.8.8.8", 443))
    finally:
        s.close()

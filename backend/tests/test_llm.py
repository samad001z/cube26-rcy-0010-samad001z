"""LLM layer (D-022), without a database or the network: settings, the Vertex adapter over
recorded-shape responses, the validator, fallback to the template, cost, and hashing."""

import json
import os
import socket
import time
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
from app.core.hashing import content_hash
from app.llm import vertex
from app.llm.client import LLMError, LLMRequest, LLMResponse
from app.llm.config import LLMConfig, LLMConfigError, llm_config
from app.llm.explain import CONSTANT_FALLBACK, PRICE_NOT_CONFIGURED, Explainer, estimate_cost
from app.llm.prompt import PROMPT_VERSION, build_request
from app.llm.template import template_text
from app.llm.trace import build_trace, corpus, trace_hash
from app.llm.validate import ExplanationRejected, _decision_signals, validate_explanation
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


def test_empty_values_as_in_env_example_mean_unset(monkeypatch):
    for name in (
        "LLM_PROVIDER",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "LLM_PRICE_INPUT_USD_PER_MTOK",
        "LLM_PRICE_OUTPUT_USD_PER_MTOK",
    ):
        monkeypatch.setenv(name, "")
    s = _settings()
    assert s.llm_provider is None and s.google_application_credentials is None
    assert s.llm_price_input_usd_per_mtok is None and s.llm_price_output_usd_per_mtok is None


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


def test_vertex_client_uses_the_key_files_credentials(monkeypatch, tmp_path):
    # Guardian finding 10: a mutant that silently ignored the key file and fell back to
    # other credentials (Application Default Credentials) survived.
    from google.oauth2 import service_account

    key_file = tmp_path / "key.json"
    key_file.write_text("{}")
    sentinel = object()

    def fake_from_file(filename: str, scopes: list[str] | None = None) -> object:
        assert filename == str(key_file)
        assert scopes == vertex.SCOPES
        return sentinel

    monkeypatch.setattr(
        service_account.Credentials, "from_service_account_file", staticmethod(fake_from_file)
    )
    seen: dict[str, Any] = {}
    monkeypatch.setattr(genai, "Client", lambda **kw: seen.update(kw) or object())
    vertex._client(_cfg(credentials_file=key_file))
    assert seen["credentials"] is sentinel


def test_prompt_marks_the_trace_as_data_not_instructions():
    # Guardian finding 16: report-supplied strings (reasons, labels) reach the trace, so the
    # prompt must say plainly that content is data to ignore, not instructions to follow.
    req = build_request(build_trace(_claim()))
    assert "<trace>" in req.prompt and "</trace>" in req.prompt
    assert "not instructions" in req.system
    assert "ignore it" in req.system


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


def test_run_budget_exhausted_falls_back_without_calling_the_model():
    # Guardian finding 4: a per-run time budget, so one slow model cannot exceed the
    # deploy's own request timeout and roll back the whole run.
    e = _explainer(_fixture("claim_ok"))
    e.deadline = time.monotonic() - 1  # already spent
    out = e.explain(None, _claim())
    assert e.calls == 0
    x = out.explanation
    assert x is not None and x.source == "template"
    assert x.fallback_reason == "time budget exhausted for this run"


def test_run_budget_is_set_from_settings():
    e = Explainer.from_settings(_enabled(llm_run_budget_s=5))
    assert e.deadline is not None and e.deadline <= time.monotonic() + 5


def test_double_failure_falls_back_to_a_constant_that_cannot_fail(monkeypatch):
    # Guardian finding 12: the fallback branch itself called build_trace() and _template()
    # unguarded, so if either of those failed too (not just the model), explain() raised,
    # which pipeline.run_org's fail-open path does not catch on its own second call.
    def boom(d: object) -> None:
        raise RuntimeError("trace boom")

    monkeypatch.setattr("app.llm.explain.build_trace", boom)
    out = Explainer().explain(None, _claim())
    assert out.explanation is not None
    assert out.explanation.text == CONSTANT_FALLBACK
    assert out.explanation.source == "template"
    assert "failed twice" in (out.explanation.fallback_reason or "")
    assert "trace boom" in (out.explanation.fallback_reason or "")


def test_disabled_explainer_never_calls_and_has_no_fallback_reason():
    out = Explainer().explain(None, _claim())
    assert out.explanation is not None
    assert (out.explanation.source, out.explanation.fallback_reason) == ("template", None)
    assert out.model_version is None


def test_changing_the_explanation_text_breaks_the_hash():
    # Guardian finding 7: a mutant that always left the explanation out of the hash payload
    # survived, because nothing edited a stored explanation and re-checked verify_hash().
    d = _claim()
    out = _explainer(_fixture("claim_ok")).explain(None, d)
    assert out.verify_hash()
    assert out.explanation is not None
    tampered = out.model_copy(
        update={"explanation": out.explanation.model_copy(update={"text": "a different text"})}
    )
    assert not tampered.verify_hash()


def test_record_stored_before_explanations_still_verifies():
    d = _claim()  # hashed by the engine, no explanation
    # The hash a record had before the field existed: its payload had no such key at all.
    before = content_hash(d.model_dump(mode="python", exclude={"content_hash", "explanation"}))
    assert d.content_hash == before
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


def test_id_that_is_a_prefix_of_a_real_one_is_not_accepted():
    # Guardian finding 1: a substring check would let "DEMO-F01-1" pass against a trace
    # that only has "DEMO-F01-12".
    trace = {"decision": "CLAIM", "cited": [{"id": "DEMO-F01-12"}]}
    text = "CLAIM. Evidence cited: DEMO-F01-1 supports full recovery of the stated fee amount."
    with pytest.raises(ExplanationRejected, match="ID DEMO-F01-1 is not in the trace"):
        validate_explanation(_model_json(text), trace)


def test_lower_case_id_is_checked_not_silently_skipped():
    trace = {"decision": "CLAIM", "cited": [{"id": "DEMO-F01-1"}]}
    text = "CLAIM. Evidence cited: demo-f01-9 supports full recovery of the stated fee amount."
    with pytest.raises(ExplanationRejected, match="ID demo-f01-9 is not in the trace"):
        validate_explanation(_model_json(text), trace)


def test_lower_case_id_matching_the_real_one_is_accepted():
    trace = {"decision": "CLAIM", "cited": [{"id": "DEMO-F01-1"}]}
    text = "CLAIM. Evidence cited: demo-f01-1 supports full recovery of the stated fee amount."
    assert "demo-f01-1" in validate_explanation(_model_json(text), trace)


def test_lower_case_wording_arguing_for_a_different_decision_is_rejected():
    # Guardian finding 2: the capitals-only check missed a REVIEW record whose text argues,
    # in lower case, that the charge should be claimed.
    d = _claim().model_copy(update={"decision": Decision.REVIEW, "claim": None})
    tr = build_trace(d)
    text = (
        "REVIEW. Prep record PRP-1 was read for L-1 before the fee was posted. You should "
        "claim the fee now."
    )
    with pytest.raises(ExplanationRejected, match=r"wording argues for .*CLAIM"):
        validate_explanation(_model_json(text), tr)


def test_real_engine_next_actions_do_not_trigger_a_false_decision_signal():
    # test-guardian follow-up (this session) to finding 2/16: the prompt asks the model to
    # relay next_action verbatim, and these are the engine's own real texts (rule
    # R_REIMBURSEMENT_AMBIGUOUS and R_PARTIAL_COVERAGE, app/engine/__init__.py, and
    # NEXT_UNIT_VALUE), all on REVIEW records. Checked against _decision_signals directly,
    # not the full validator, since a separate, pre-existing gap (the literal "(D-021)"
    # citations in this text are read as unrecognized IDs, tracked in docs/BACKLOG.md) would
    # otherwise reject these for a reason unrelated to what findings 2 and 6 touched.
    # A first version of the finding-2 fix wrongly flagged "close the line as do not claim"
    # as arguing for DO_NOT_CLAIM; fixed with a lookbehind excluding "as do not claim".
    real_next_actions = [
        "Match the refund to its fee (e.g. by reimbursement or case id in Seller Central) "
        "and re-run; until then an override can only close the line as do not claim "
        "(D-021).",
        "Find evidence for the remaining units and re-run, or file the covered part "
        "outside Alibi; an override cannot claim part of a charge (D-021).",
        "Find an authoritative unit value for this unit and file the claim outside Alibi; "
        "loss-event claims cannot be made through an override in this version (D-021).",
    ]
    for next_action in real_next_actions:
        assert _decision_signals(next_action) - {"REVIEW"} == set(), next_action


def test_lower_case_do_not_claim_wording_on_a_claim_record_is_rejected():
    tr = build_trace(_claim())
    text = GOOD + " Actually, do not claim this yet."
    with pytest.raises(ExplanationRejected, match=r"wording argues for .*DO_NOT_CLAIM"):
        validate_explanation(_model_json(text), tr)


@pytest.mark.parametrize(
    ("suffix", "why"),
    [
        (" It costs $2.00.", "currency symbol"),
        (" It costs €2.00.", "currency symbol"),
        (" Also 2.00 EUR was considered.", "currency EUR"),
        (" This is worth 50%.", "percentage"),
        (" It can be claimed twice.", "number word"),
    ],
)
def test_currency_and_number_word_wording_is_rejected(suffix, why):
    with pytest.raises(ExplanationRejected, match=why):
        validate_explanation(_model_json(GOOD + suffix), build_trace(_claim()))


def test_negative_number_is_rejected_but_a_hyphenated_id_is_not():
    with pytest.raises(ExplanationRejected, match="negative number"):
        validate_explanation(_model_json(GOOD + " A separate loss of -6.25 was noted."), TRACE)
    # PRP-1 in GOOD is a real ID, not a negative number: it must still pass.
    assert validate_explanation(_model_json(GOOD), TRACE) == GOOD


def test_amount_near_claim_must_be_the_claim_amount_not_some_other_trace_figure():
    # Guardian finding 6: "claim amount 12.50" passed when 12.50 was really the charge, not
    # the claim, because no check tied a number to what it claimed to be.
    d = _claim()
    tr = build_trace(d)
    assert tr["claim"] is not None and tr["claim"]["amount"] == "2.00"
    text = (
        "CLAIM. Prep record PRP-1 shows fnsku_label_placement and original_barcode_covered "
        "passed before the fee on L-1 was posted. The claim amount is 2.00 USD, the same as "
        "the fee charged."
    )
    # 2.00 is also the charge amount here, so this legitimate wording still passes.
    assert validate_explanation(_model_json(text), tr) == text
    bad = text.replace("The claim amount is 2.00", "The claim amount is 12.50")
    with pytest.raises(ExplanationRejected, match="is not the claim amount"):
        validate_explanation(_model_json(bad), tr)


def test_id_run_pattern_is_case_insensitive_and_exact():
    # Guardian finding 6: a mutant disabling the check on single-run alphanumeric IDs
    # (X00DEMO0001-style) survived because nothing exercised it.
    trace = {"decision": "CLAIM", "cited": [{"id": "X00DEMO0001"}]}
    good = "CLAIM. Evidence cited: X00DEMO0001 supports full recovery of the stated fee amount."
    assert validate_explanation(_model_json(good), trace) == good
    lower = "CLAIM. Evidence cited: x00demo0001 supports full recovery of the stated fee amount."
    assert "x00demo0001" in validate_explanation(_model_json(lower), trace)
    wrong = "CLAIM. Evidence cited: X00DEMO0002 supports full recovery of the stated fee amount."
    with pytest.raises(ExplanationRejected, match="ID X00DEMO0002 is not in the trace"):
        validate_explanation(_model_json(wrong), trace)


def test_trace_hash_changes_with_model_and_prompt_version():
    # Guardian finding 8: a mutant dropping model or prompt version from the cache key
    # survived, so a stale cached explanation from a different model or prompt could be
    # served under the wrong key.
    trace = build_trace(_claim())
    base = trace_hash(trace, "explain-v1", "model-a")
    assert trace_hash(trace, "explain-v2", "model-a") != base
    assert trace_hash(trace, "explain-v1", "model-b") != base
    assert trace_hash(trace, "explain-v1", None) != base


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


def test_connect_ex_is_blocked_too():
    # Guardian finding 3: only `connect` was guarded; a client using `connect_ex` (as some
    # HTTP libraries do for non-blocking sockets) could still reach out.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(RuntimeError, match="network access blocked"):
            s.connect_ex(("8.8.8.8", 443))
    finally:
        s.close()


def test_a_real_outbound_https_call_fails():
    # Guardian finding 3: a loopback HTTP proxy would otherwise let traffic through the
    # loopback allowance and out to the real internet from there.
    import urllib.error
    import urllib.request

    with pytest.raises((RuntimeError, OSError, urllib.error.URLError)):
        urllib.request.urlopen("https://oauth2.googleapis.com/token", timeout=2)


def test_llm_and_credentials_env_vars_are_forced_off():
    # Guardian finding 3, and fix 1 (isolation from the developer's real .env): a developer's
    # or CI's own environment, and their .env file, must never let a test reach a real model
    # or read a real price, even before any fixture in this file runs.
    for name in (
        "LLM_ENABLED",
        "LLM_PROVIDER",
        "LLM_MODEL",
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "LLM_PRICE_INPUT_USD_PER_MTOK",
        "LLM_PRICE_OUTPUT_USD_PER_MTOK",
    ):
        assert name not in os.environ
    assert os.environ.get("ALIBI_TESTS_NO_ENV_FILE") == "1"
    for proxy_var in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy"):
        assert proxy_var not in os.environ

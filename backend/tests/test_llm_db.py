"""LLM layer through the real pipeline and Postgres (D-022): one model call per decision,
the cache on a re-run, what is stored on the record, and that decisions do not move."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

from google.genai import types
from typer.testing import CliRunner

from app import cli
from app.core.config import get_settings
from app.db import repo
from app.db import tables as t
from app.db.session import org_session
from app.llm import vertex
from app.llm.client import LLMRequest, LLMResponse
from app.llm.config import LLMConfig
from app.llm.explain import Explainer
from app.llm.prompt import DECISION_WORDS
from app.models.charge import SourceRef
from app.models.vocab import RecordStatus
from app.pipeline import run_org
from tests.conftest import AS_OF
from tests.factories import charge, check, record
from tests.test_pipeline_db import _load_synthetic

ORG = "org_test_llm"


class TraceEcho:
    """A provider that answers from the trace in the prompt, like a well-behaved model."""

    model_id = "fixture-model"

    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> LLMResponse:
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
        run_budget_s=200,
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


# --- make llm-smoke (the CLI), with the SDK client replaced by recorded-shape fixtures ----

ORG_SMOKE = "org_test_llm_smoke"
FIXTURES = Path(__file__).parent / "fixtures" / "llm"


def _load_claim_matching_fixture(app_engine) -> None:
    """L-1 with PRP-1 (label checks passed): the case claim_ok.json explains."""
    c = charge("L-1", defect_category="label", org=ORG_SMOKE)
    r = record(
        "PRP-1",
        org=ORG_SMOKE,
        checks=[check("fnsku_label_placement", "PASS"), check("original_barcode_covered", "PASS")],
    )
    with org_session(app_engine, ORG_SMOKE) as s:
        fid = repo.upsert_ingest_file(s, ORG_SMOKE, "smoke.csv", "c" * 64, "fee_report")
        repo.insert_charges(s, [c], fid)
        repo.insert_records(
            s, [r], {(r.agent, r.record_id): SourceRef(file_sha256="d" * 64, row=1, raw={})}, fid
        )
    run_org(app_engine, ORG_SMOKE, AS_OF, explainer=Explainer())


def _smoke(app_engine, monkeypatch, fixture: str, *args: str, **env: str):
    response = types.GenerateContentResponse.model_validate(
        json.loads((FIXTURES / f"{fixture}.json").read_text())["response"]
    )

    class Models:
        def generate_content(self, **kw: Any) -> types.GenerateContentResponse:
            return response

    class Client:
        models = Models()

    monkeypatch.setattr(vertex, "_client", lambda cfg: Client())
    monkeypatch.setattr(cli, "get_engine", lambda: app_engine)
    settings = {
        "DATABASE_URL": "unused",
        "MIGRATION_DATABASE_URL": "unused",
        "ATTACHMENT_KEY_SECRET": "test-secret",
        "LLM_ENABLED": "false",  # llm-smoke calls the model whatever this says
        "LLM_PROVIDER": "vertex",
        "GOOGLE_CLOUD_PROJECT": "proj-test",
        "GOOGLE_CLOUD_LOCATION": "europe-west4",
        "LLM_MODEL": "fixture-model",
        **env,
    }
    for k, v in settings.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    try:
        return CliRunner().invoke(cli.app, ["llm-smoke", "--org", ORG_SMOKE, *args])
    finally:
        get_settings.cache_clear()


def test_llm_smoke_uses_the_model_text_and_records_the_response(
    app_engine, loaded, monkeypatch, tmp_path
):
    _load_claim_matching_fixture(app_engine)
    out = tmp_path / "recorded.json"
    res = _smoke(app_engine, monkeypatch, "claim_ok", "--line", "L-1", "--record", str(out))
    assert res.exit_code == 0, res.output
    assert "MODEL EXPLANATION USED (validated against the decision trace):" in res.output
    assert "CLAIM. Prep record PRP-1 shows" in res.output
    assert "tokens    in 1234  out 156" in res.output
    assert "price not configured" in res.output
    saved = json.loads(out.read_text())
    assert saved["response"]["usage_metadata"]["prompt_token_count"] == 1234
    # Nothing written: the cache for this org is still empty.
    with org_session(app_engine, ORG_SMOKE) as s:
        assert repo.count_rows(s, t.llm_explanations) == 0


def test_llm_smoke_says_clearly_when_it_fell_back(app_engine, loaded, monkeypatch):
    res = _smoke(app_engine, monkeypatch, "claim_invented_amount", "--line", "L-1")
    assert res.exit_code == 3, res.output
    assert "FELL BACK TO TEMPLATE: model text rejected: number 7.35 is not in" in res.output


def test_llm_smoke_stops_on_missing_settings(app_engine, loaded, monkeypatch):
    res = _smoke(app_engine, monkeypatch, "claim_ok", LLM_MODEL="")
    assert res.exit_code == 2

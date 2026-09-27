"""Gemini on Vertex AI through the google-genai SDK (vertexai=True).

Credentials: in production the Cloud Run service identity (Application Default
Credentials); locally, optionally a service-account key file outside the repo named by
GOOGLE_APPLICATION_CREDENTIALS. One attempt per call (no retries), with a timeout."""

import time
from typing import Any

from google import genai
from google.genai import types

from app.llm.client import LLMError, LLMRequest, LLMResponse
from app.llm.config import LLMConfig

SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]


def _client(cfg: LLMConfig) -> Any:
    credentials = None
    if cfg.credentials_file is not None:
        from google.oauth2 import service_account

        credentials = service_account.Credentials.from_service_account_file(  # type: ignore[no-untyped-call]
            str(cfg.credentials_file), scopes=SCOPES
        )
    return genai.Client(
        vertexai=True,
        project=cfg.project,
        location=cfg.location,
        credentials=credentials,
        http_options=types.HttpOptions(
            timeout=cfg.timeout_s * 1000,  # milliseconds
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )


class VertexProvider:
    def __init__(self, cfg: LLMConfig, client: Any | None = None):
        self.cfg = cfg
        self.model_id = cfg.model
        self._client = client  # injected in tests; built lazily otherwise

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = _client(self.cfg)
        return self._client

    def generate(self, request: LLMRequest) -> LLMResponse:
        config = types.GenerateContentConfig(
            system_instruction=request.system,
            temperature=0,
            max_output_tokens=self.cfg.max_output_tokens,
            response_mime_type="application/json",
            response_json_schema=request.response_schema,
        )
        started = time.perf_counter()
        try:
            response = self._get_client().models.generate_content(
                model=self.cfg.model, contents=request.prompt, config=config
            )
        except Exception as exc:  # SDK, auth, network or timeout errors all fall back
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc
        latency_ms = round((time.perf_counter() - started) * 1000)
        text = getattr(response, "text", None)
        if not text:
            reason = None
            candidates = getattr(response, "candidates", None) or []
            if candidates:
                reason = getattr(candidates[0], "finish_reason", None)
            raise LLMError(f"empty response (finish reason {reason})")
        usage = getattr(response, "usage_metadata", None)
        prompt_tokens = getattr(usage, "prompt_token_count", None) or 0
        output = (getattr(usage, "candidates_token_count", None) or 0) + (
            getattr(usage, "thoughts_token_count", None) or 0
        )
        return LLMResponse(
            text=text,
            model_id=getattr(response, "model_version", None) or self.cfg.model,
            input_tokens=int(prompt_tokens),
            output_tokens=int(output),
            latency_ms=latency_ms,
        )

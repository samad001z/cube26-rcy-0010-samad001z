"""LLM settings, checked only when LLM_ENABLED is true. Everything comes from the
environment (app.core.config.Settings); no model name or price is written in code."""

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from app.core.config import REPO_ROOT, Settings

IMPLEMENTED = ("vertex",)
KNOWN_NOT_IMPLEMENTED = ("anthropic", "bedrock")


class LLMConfigError(ValueError):
    """One line for the operator: what is missing or wrong."""


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    project: str
    location: str
    model: str
    credentials_file: Path | None
    timeout_s: int
    run_budget_s: int
    max_output_tokens: int
    price_input_per_mtok: Decimal | None
    price_output_per_mtok: Decimal | None


def llm_config(s: Settings) -> LLMConfig:
    provider = (s.llm_provider or "").strip().lower()
    if not provider:
        raise LLMConfigError("LLM_ENABLED is true but LLM_PROVIDER is not set (use: vertex)")
    if provider in KNOWN_NOT_IMPLEMENTED:
        raise LLMConfigError(f"LLM_PROVIDER={provider} is not implemented yet (use: vertex)")
    if provider not in IMPLEMENTED:
        raise LLMConfigError(f"unknown LLM_PROVIDER={provider!r} (use: vertex)")
    missing = [
        name
        for name, value in (
            ("GOOGLE_CLOUD_PROJECT", s.google_cloud_project),
            ("GOOGLE_CLOUD_LOCATION", s.google_cloud_location),
            ("LLM_MODEL", s.llm_model),
        )
        if not (value or "").strip()
    ]
    if missing:
        raise LLMConfigError(f"LLM_ENABLED is true but {', '.join(missing)} not set")
    creds = None
    if s.google_application_credentials:
        creds = Path(s.google_application_credentials).expanduser().resolve()
        if creds.is_relative_to(REPO_ROOT.resolve()):
            raise LLMConfigError(
                "GOOGLE_APPLICATION_CREDENTIALS points inside the repository; keep the key "
                "file outside it (for example ~/.config/alibi/)"
            )
        if not creds.is_file():
            raise LLMConfigError(f"GOOGLE_APPLICATION_CREDENTIALS file not found: {creds}")
    if s.llm_timeout_s < 1 or s.llm_max_output_tokens < 1 or s.llm_run_budget_s < 1:
        raise LLMConfigError(
            "LLM_TIMEOUT_S, LLM_RUN_BUDGET_S and LLM_MAX_OUTPUT_TOKENS must be positive"
        )
    return LLMConfig(
        provider=provider,
        project=str(s.google_cloud_project).strip(),
        location=str(s.google_cloud_location).strip(),
        model=str(s.llm_model).strip(),
        credentials_file=creds,
        timeout_s=s.llm_timeout_s,
        run_budget_s=s.llm_run_budget_s,
        max_output_tokens=s.llm_max_output_tokens,
        price_input_per_mtok=s.llm_price_input_usd_per_mtok,
        price_output_per_mtok=s.llm_price_output_usd_per_mtok,
    )

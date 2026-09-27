"""Provider interface. One `generate` call per decision; providers implement it.

Only Vertex AI (Gemini) is implemented. Another provider (Anthropic, Bedrock) would add a
module with a class that satisfies `LLMProvider` and a branch in `make_provider`."""

from dataclasses import dataclass
from typing import Protocol

from app.llm.config import LLMConfig


class LLMError(Exception):
    """The provider did not return usable text (network, auth, quota, timeout, empty)."""


@dataclass(frozen=True)
class LLMRequest:
    system: str
    prompt: str
    # JSON schema the answer must follow.
    response_schema: dict[str, object]


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model_id: str
    input_tokens: int
    # Output tokens billed, including any thinking tokens the model reports.
    output_tokens: int
    latency_ms: int


class LLMProvider(Protocol):
    model_id: str

    def generate(self, request: LLMRequest) -> LLMResponse: ...


def make_provider(cfg: LLMConfig) -> LLMProvider:
    if cfg.provider == "vertex":
        from app.llm.vertex import VertexProvider

        return VertexProvider(cfg)
    raise LLMError(f"LLM provider {cfg.provider!r} is not implemented")  # pragma: no cover

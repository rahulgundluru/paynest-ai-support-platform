"""Provider-neutral model interfaces. Business logic depends on these, never on a vendor SDK.

Every outbound payload passes through `assert_no_pii` first: the PII gate already redacted ticket
text at ingestion, and this is the second, independent check at the network boundary (G1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.services.pii.gate import contains_pii


class ProviderUnavailable(RuntimeError):
    """No provider configured, credentials missing, or the service is unreachable."""


class PiiLeakBlocked(RuntimeError):
    """A payload bound for an external model still matched a PII detector; the call was not made."""


@dataclass(frozen=True)
class StructuredResult:
    data: dict[str, Any]
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    model: str
    input_tokens: int
    latency_ms: int


class LLMProvider(Protocol):
    name: str

    async def structured(
        self, *, system: str, user: str, tool_name: str, tool_description: str, schema: dict[str, Any], max_tokens: int
    ) -> StructuredResult: ...


class EmbeddingProvider(Protocol):
    name: str
    dimensions: int

    async def embed(self, texts: list[str], *, purpose: str) -> EmbeddingResult: ...


def assert_no_pii(*parts: str) -> None:
    for part in parts:
        if contains_pii(part):
            raise PiiLeakBlocked("payload contains a PII pattern; external call blocked")

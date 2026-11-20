"""AWS Bedrock adapter (Converse API with forced tool use for typed output; Cohere-style embeddings).

Model ids and region are configuration, never defaults in code: the right model ids and their
in-region availability (India / UAE residency) must be confirmed before use. Credentials come from
the standard AWS chain (IAM role in ECS; local profile or env in development).
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from app.ai.providers.base import EmbeddingResult, ProviderUnavailable, StructuredResult, assert_no_pii


def _client(region: str) -> Any:
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise ProviderUnavailable("boto3 is not installed") from exc
    return boto3.client(
        "bedrock-runtime",
        region_name=region,
        config=Config(retries={"max_attempts": 3, "mode": "standard"}, read_timeout=30),
    )


class BedrockLLM:
    name = "bedrock"

    def __init__(self, region: str, model_id: str) -> None:
        self.region, self.model_id = region, model_id
        self._client = _client(region)

    async def structured(
        self, *, system: str, user: str, tool_name: str, tool_description: str, schema: dict[str, Any], max_tokens: int
    ) -> StructuredResult:
        assert_no_pii(system, user)
        request = {
            "modelId": self.model_id,
            "system": [{"text": system}],
            "messages": [{"role": "user", "content": [{"text": user}]}],
            "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0},
            "toolConfig": {
                "tools": [
                    {"toolSpec": {"name": tool_name, "description": tool_description, "inputSchema": {"json": schema}}}
                ],
                "toolChoice": {"tool": {"name": tool_name}},
            },
        }
        started = time.perf_counter()
        try:
            response = await asyncio.to_thread(self._client.converse, **request)
        except Exception as exc:  # botocore raises many types; surface them uniformly
            raise ProviderUnavailable(f"bedrock converse failed: {type(exc).__name__}") from exc
        latency = int((time.perf_counter() - started) * 1000)
        blocks = response.get("output", {}).get("message", {}).get("content", [])
        tool_use = next((b["toolUse"] for b in blocks if "toolUse" in b), None)
        if tool_use is None:
            raise ValueError("model did not return the requested tool call")
        usage = response.get("usage", {})
        return StructuredResult(
            data=dict(tool_use.get("input") or {}),
            model=self.model_id,
            input_tokens=int(usage.get("inputTokens", 0)),
            output_tokens=int(usage.get("outputTokens", 0)),
            latency_ms=latency,
        )


class BedrockEmbeddings:
    name = "bedrock"

    def __init__(self, region: str, model_id: str, dimensions: int) -> None:
        self.region, self.model_id, self.dimensions = region, model_id, dimensions
        self._client = _client(region)

    async def embed(self, texts: list[str], *, purpose: str) -> EmbeddingResult:
        assert_no_pii(*texts)
        body = json.dumps(
            {
                "texts": texts,
                "input_type": "search_query" if purpose == "query" else "search_document",
                "truncate": "END",
            }
        )
        started = time.perf_counter()
        try:
            response = await asyncio.to_thread(
                self._client.invoke_model,
                modelId=self.model_id,
                body=body,
                accept="application/json",
                contentType="application/json",
            )
        except Exception as exc:
            raise ProviderUnavailable(f"bedrock embeddings failed: {type(exc).__name__}") from exc
        payload = json.loads(response["body"].read())
        vectors = payload.get("embeddings")
        if isinstance(vectors, dict):  # newer response shape keyed by embedding type
            vectors = vectors.get("float")
        if not vectors or len(vectors[0]) != self.dimensions:
            raise ValueError("unexpected embedding response shape or dimensions")
        return EmbeddingResult(
            vectors=vectors,
            model=self.model_id,
            input_tokens=int(
                response.get("ResponseMetadata", {}).get("HTTPHeaders", {}).get("x-amzn-bedrock-input-token-count", 0)
            ),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )

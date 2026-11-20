"""OpenRouter adapter (OpenAI-compatible chat completions with forced tool calling).

Guarantees:
- `assert_no_pii` runs on every outbound payload before any network call (second, independent PII check).
- Every request asks for providers that neither collect nor retain prompts
  (`provider.data_collection = "deny"`, `provider.zdr = true`) and that support every parameter sent.
- The cost recorded is what OpenRouter reports it charged (`usage.cost`, in OpenRouter credits, which are
  US dollars). Nothing is estimated here.
- The API key is read from settings only; it is never logged or echoed in errors.
"""

from __future__ import annotations

import asyncio
import json
import time
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.ai.providers.base import ProviderUnavailable, StructuredResult, assert_no_pii

APP_TITLE = "PayNest Support Platform"
# Privacy routing only. (require_parameters is NOT set: it filters on parameter metadata and excluded every
# endpoint for some models; outputs are schema-validated anyway.)
PRIVACY = {"data_collection": "deny", "zdr": True}
_RETRYABLE = {408, 429, 500, 502, 503, 504}


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _error_code(status: int, body: str) -> str:
    text = body.lower()
    if status == 401:
        return "auth_failed"
    if status == 402:
        return "insufficient_credits"
    if status == 404 and "tool_choice" in text:
        return "tool_choice_unsupported"
    if status == 404 and ("data policy" in text or "no endpoints" in text or "zdr" in text):
        return "no_private_endpoint"
    if status == 404:
        return "model_not_found"
    if status == 429:
        return "rate_limited"
    if status == 400:
        return "bad_request"
    return f"http_{status}"


def _message(status: int, body: str) -> str:
    try:
        detail = json.loads(body).get("error", {}).get("message", "")
    except (ValueError, AttributeError):
        detail = ""
    return f"OpenRouter returned {status}" + (f": {str(detail)[:200]}" if detail else "")


class OpenRouterLLM:
    name = "openrouter"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout_seconds: float = 45.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ProviderUnavailable("OpenRouter API key is not configured", code="no_api_key", model=model)
        self.model = model
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base,
            timeout=self._timeout,
            transport=self._transport,
            headers={"Authorization": f"Bearer {self._key}", "X-Title": APP_TITLE},
        )

    async def structured(
        self, *, system: str, user: str, tool_name: str, tool_description: str, schema: dict[str, Any], max_tokens: int
    ) -> StructuredResult:
        assert_no_pii(system, user)
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "tools": [
                {
                    "type": "function",
                    "function": {"name": tool_name, "description": tool_description, "parameters": schema},
                }
            ],
            "temperature": 0,
            "max_tokens": max_tokens,
            "provider": PRIVACY,
        }
        started = time.perf_counter()
        # Force the one tool by name; endpoints that cannot do that get "required" (equivalent with a single
        # tool), then "auto" (the prompt asks for the tool, and _parse also accepts JSON content).
        choices: list[Any] = [{"type": "function", "function": {"name": tool_name}}, "required", "auto"]
        for i, choice in enumerate(choices):
            try:
                body = await self._post_with_retry("/chat/completions", {**payload, "tool_choice": choice})
                break
            except ProviderUnavailable as exc:
                if exc.code != "tool_choice_unsupported" or i == len(choices) - 1:
                    raise
        latency_ms = int((time.perf_counter() - started) * 1000)
        return self._parse(body, tool_name, latency_ms)

    async def _post_with_retry(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        last: ProviderUnavailable | None = None
        async with self._client() as client:
            for attempt in range(2):
                try:
                    response = await client.post(path, json=payload)
                except httpx.TimeoutException:
                    last = ProviderUnavailable("OpenRouter request timed out", code="timeout", model=self.model)
                except httpx.HTTPError as exc:
                    last = ProviderUnavailable(
                        f"OpenRouter unreachable ({type(exc).__name__})", code="network_error", model=self.model
                    )
                else:
                    if response.status_code == 200:
                        data = response.json()
                        if isinstance(data, dict) and "error" in data and "choices" not in data:
                            err = data.get("error") or {}
                            code = _error_code(int(err.get("code") or 502), json.dumps(data))
                            raise ProviderUnavailable(_message(int(err.get("code") or 502), json.dumps(data)),
                                                      code=code, model=self.model)  # fmt: skip
                        return data  # type: ignore[no-any-return]
                    text = response.text
                    last = ProviderUnavailable(
                        _message(response.status_code, text),
                        code=_error_code(response.status_code, text),
                        model=self.model,
                    )
                    if response.status_code not in _RETRYABLE:
                        raise last
                if attempt == 0:
                    await asyncio.sleep(1.0)
        assert last is not None  # noqa: S101 - loop always sets it before falling through
        raise last

    def _parse(self, body: dict[str, Any], tool_name: str, latency_ms: int) -> StructuredResult:
        usage = body.get("usage") or {}
        choice = (body.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        arguments: Any = None
        for call in message.get("tool_calls") or []:
            fn = call.get("function") or {}
            if fn.get("name") == tool_name:
                arguments = fn.get("arguments")
                break
        if arguments is None and message.get("content"):
            arguments = message["content"]  # some models answer in content despite tool_choice
        if isinstance(arguments, str):
            text = arguments.strip()
            if text.startswith("```"):
                text = text.strip("`").removeprefix("json").strip()
            try:
                arguments = json.loads(text)
            except ValueError as exc:
                raise ValueError("model returned arguments that are not valid JSON") from exc
        if not isinstance(arguments, dict):
            raise ValueError("model did not return the requested tool call")
        return StructuredResult(
            data=arguments,
            model=str(body.get("model") or self.model),
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            latency_ms=latency_ms,
            cost_usd=_decimal(usage.get("cost")),
            request_id=body.get("id"),
            upstream_provider=body.get("provider"),
        )


# ----------------------------------------------------------------------------- account and catalogue
async def fetch_models(base_url: str, transport: httpx.AsyncBaseTransport | None = None) -> list[dict[str, Any]]:
    """Public model catalogue with per-token prices. Only models that support tool calling are useful here."""
    async with httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=20, transport=transport) as client:
        response = await client.get("/models")
    if response.status_code != 200:
        raise ProviderUnavailable(_message(response.status_code, response.text), code=f"http_{response.status_code}")
    models: list[dict[str, Any]] = []
    for m in response.json().get("data", []):
        params = m.get("supported_parameters") or []
        if "tools" not in params or "tool_choice" not in params:
            continue
        pricing = m.get("pricing") or {}
        prompt, completion = _decimal(pricing.get("prompt")), _decimal(pricing.get("completion"))
        if prompt is None or completion is None or prompt < 0 or completion < 0:
            continue  # variable-price routers ("-1") cannot be capped reliably
        models.append(
            {
                "id": m.get("id"),
                "name": m.get("name") or m.get("id"),
                "context_length": m.get("context_length"),
                "input_usd_per_mtok": float(prompt * 1_000_000),
                "output_usd_per_mtok": float(completion * 1_000_000),
            }
        )
    models.sort(key=lambda x: (x["input_usd_per_mtok"] + x["output_usd_per_mtok"], x["id"]))
    return models


async def fetch_key_info(
    api_key: str, base_url: str, transport: httpx.AsyncBaseTransport | None = None
) -> dict[str, Any]:
    """Usage and limits OpenRouter reports for this key (USD). Never returns the key itself."""
    async with httpx.AsyncClient(
        base_url=base_url.rstrip("/"), timeout=20, transport=transport,
        headers={"Authorization": f"Bearer {api_key}"},
    ) as client:  # fmt: skip
        response = await client.get("/key")
    if response.status_code != 200:
        raise ProviderUnavailable(
            _message(response.status_code, response.text), code=_error_code(response.status_code, response.text)
        )
    d = response.json().get("data", {})
    return {
        "is_free_tier": d.get("is_free_tier"),
        "limit_usd": d.get("limit"),
        "limit_remaining_usd": d.get("limit_remaining"),
        "usage_usd": d.get("usage"),
        "usage_daily_usd": d.get("usage_daily"),
        "usage_monthly_usd": d.get("usage_monthly"),
    }

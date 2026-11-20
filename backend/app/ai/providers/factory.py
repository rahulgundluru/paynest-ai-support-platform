"""Builds the configured providers. LLM_PROVIDER=none (the default) means "no model available":
classification then records status `unavailable` and routes the ticket to a person."""

from __future__ import annotations

from app.ai.providers.base import EmbeddingProvider, LLMProvider
from app.core.config import Settings


def classifier_provider(settings: Settings) -> LLMProvider | None:
    if settings.llm_provider == "bedrock" and settings.bedrock_classifier_model_id:
        from app.ai.providers.bedrock import BedrockLLM

        return BedrockLLM(settings.bedrock_region, settings.bedrock_classifier_model_id)
    return None


def embedding_provider(settings: Settings) -> EmbeddingProvider | None:
    if settings.embedding_provider == "bedrock" and settings.bedrock_embedding_model_id:
        from app.ai.providers.bedrock import BedrockEmbeddings

        return BedrockEmbeddings(
            settings.bedrock_region, settings.bedrock_embedding_model_id, settings.embedding_dimensions
        )
    return None

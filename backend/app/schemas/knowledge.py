from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class VersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: int
    content_complete: bool
    effective_from: date | None
    effective_to: date | None
    validity_source: str
    superseded_by: str | None
    approval_status: str
    indexed_at: datetime | None
    content: str


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    doc_type: str
    title: str
    region: str
    topic: str | None
    owner: str | None
    source_file: str
    last_reviewed: date | None
    status: str
    version_count: int = 0
    in_force_today: bool = False
    content_complete: bool = False


class DocumentDetail(DocumentOut):
    metadata: dict[str, Any]
    versions: list[VersionOut]


class ChunkOut(BaseModel):
    id: int
    version: int
    seq: int
    heading: str | None
    text: str
    has_embedding: bool


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    region: str = Field(pattern="^(IN|UAE)$")
    as_of: date
    doc_types: list[str] | None = None
    limit: int = Field(default=5, ge=1, le=20)


class SearchHit(BaseModel):
    rank: int
    document_id: str
    doc_type: str
    title: str
    version: int
    heading: str | None
    text: str
    content_complete: bool
    effective_from: date | None
    effective_to: date | None
    validity_source: str
    score: float


class SearchResponse(BaseModel):
    retrieval_id: uuid.UUID
    query_redacted: str
    mode: str
    hits: list[SearchHit]


class RateOut(BaseModel):
    rule_id: str
    topic: str
    title: str
    value: str
    in_force_since: date | None
    in_force_until: date | None
    source: str

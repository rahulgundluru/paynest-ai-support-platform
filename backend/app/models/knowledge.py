"""Knowledge base: documents, versions with effective-date windows, chunks (full-text + vector), retrieval logs.

Effective dates are first-class: retrieval filters on `effective_from <= as_of <= effective_to`, never on
`last_reviewed` (which only records when someone last looked at an article).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

EMBEDDING_DIMENSIONS = 1024
DOC_TYPES = ("kb_article", "statutory_rule", "process_document")


class StatutoryRule(Base):
    """Mirror of integrations/statutory_rules.json (the engine's /statutory/rates is the source of truth)."""

    __tablename__ = "statutory_rules"

    rule_id: Mapped[str] = mapped_column(String(30), primary_key=True)
    region: Mapped[str] = mapped_column(String(3), nullable=False)
    topic: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    old_value: Mapped[str] = mapped_column(Text, nullable=False)
    new_value: Mapped[str] = mapped_column(Text, nullable=False)
    affects_kb_topics: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    __table_args__ = (CheckConstraint("region IN ('IN', 'UAE')", name="region"),)


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # KB-0142, R-IN-PF-2026-08, SOP-...
    doc_type: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str] = mapped_column(String(3), nullable=False)  # IN | UAE | ALL
    topic: Mapped[str | None] = mapped_column(String(40), index=True)
    owner: Mapped[str | None] = mapped_column(String(60))
    source_file: Mapped[str] = mapped_column(String(200), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    last_reviewed: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="active")  # active | retired
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    versions: Mapped[list[KnowledgeDocumentVersion]] = relationship(
        back_populates="document", order_by="KnowledgeDocumentVersion.version", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("doc_type IN ('kb_article', 'statutory_rule', 'process_document')", name="doc_type"),
        CheckConstraint("region IN ('IN', 'UAE', 'ALL')", name="region"),
        CheckConstraint("status IN ('active', 'retired')", name="status"),
    )


class KnowledgeDocumentVersion(Base):
    __tablename__ = "knowledge_document_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[str] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_complete: Mapped[bool] = mapped_column(Boolean, nullable=False)  # False = title/metadata only
    effective_from: Mapped[date | None] = mapped_column(Date)  # None = not known / since inception
    effective_to: Mapped[date | None] = mapped_column(Date)  # None = still in force
    validity_source: Mapped[str] = mapped_column(String(80), nullable=False)
    superseded_by: Mapped[str | None] = mapped_column(String(40))
    approval_status: Mapped[str] = mapped_column(String(12), nullable=False)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    document: Mapped[KnowledgeDocument] = relationship(back_populates="versions")
    chunks: Mapped[list[KnowledgeChunk]] = relationship(order_by="KnowledgeChunk.seq", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("document_id", "version", name="uq_knowledge_document_versions_doc_version"),
        CheckConstraint("approval_status IN ('approved', 'pending', 'rejected')", name="approval_status"),
        CheckConstraint(
            "effective_from IS NULL OR effective_to IS NULL OR effective_from <= effective_to", name="window"
        ),
    )


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_document_versions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    heading: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # 'simple' config: no language-specific stemming, so Hindi/Arabic/English tokens are kept as written.
    search: Mapped[Any] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple', coalesce(heading, '') || ' ' || text)", persisted=True)
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    embedding_model: Mapped[str | None] = mapped_column(String(80))

    __table_args__ = (
        UniqueConstraint("version_id", "seq", name="uq_knowledge_chunks_version_seq"),
        Index("ix_knowledge_chunks_search", "search", postgresql_using="gin"),
    )


class RetrievalLog(Base):
    __tablename__ = "retrieval_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tickets.id", ondelete="SET NULL"), index=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    query_redacted: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str] = mapped_column(String(3), nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    mode: Mapped[str] = mapped_column(String(20), nullable=False)  # fulltext | hybrid
    result_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RetrievalResult(Base):
    __tablename__ = "retrieval_results"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    retrieval_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("retrieval_logs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_id: Mapped[int] = mapped_column(ForeignKey("knowledge_chunks.id", ondelete="CASCADE"), nullable=False)
    document_id: Mapped[str] = mapped_column(String(40), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)

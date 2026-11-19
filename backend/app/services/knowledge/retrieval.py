"""Date- and region-aware retrieval.

Filters are applied in SQL BEFORE ranking, so a chunk outside its effective window can never be
returned, however similar it is (this is what stops KB-0142's INR 15,000 being cited in September).
Ranking: PostgreSQL full-text search today; vector similarity is fused in (reciprocal rank fusion)
once an embedding provider is configured. Exact identifiers (KB-0202, R-UAE-WPS-2026-07) are boosted.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import Float, and_, case, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    RetrievalLog,
    RetrievalResult,
    StatutoryRule,
)

_STOPWORDS = set(
    "a an and are as at be by can do does for from has have how i in is it its me my of on or our please "
    "should the their them there this to us was we what when which who why will with you your".split()
)
_IDENT = re.compile(r"\b(?:KB-\d{4}|R-[A-Z]{2,3}-[A-Z]+-\d{4}-\d{2}|SOP-[A-Z-]+|SLA-SCHEDULE-3)\b")


@dataclass(frozen=True)
class RetrievedChunk:
    rank: int
    chunk_id: int
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


def _tsquery_terms(query: str) -> list[str]:
    words = re.findall(r"[\w؀-ۿऀ-ॿ]+", query.lower())
    return [w for w in words if w not in _STOPWORDS and len(w) > 1 and not w.startswith("<")][:30]


def valid_on(as_of: date):  # type: ignore[no-untyped-def]
    v = KnowledgeDocumentVersion
    return and_(
        or_(v.effective_from.is_(None), v.effective_from <= as_of),
        or_(v.effective_to.is_(None), v.effective_to >= as_of),
    )


async def retrieve(
    session: AsyncSession,
    query: str,
    *,
    region: str,
    as_of: date,
    doc_types: list[str] | None = None,
    topics: list[str] | None = None,
    limit: int = 5,
    ticket_id: uuid.UUID | None = None,
    requested_by: uuid.UUID | None = None,
) -> tuple[uuid.UUID, list[RetrievedChunk]]:
    """`query` must already be PII-redacted (callers pass ticket text from the redacted columns)."""
    terms = _tsquery_terms(query)
    identifiers = set(_IDENT.findall(query.upper()))
    v, d, c = KnowledgeDocumentVersion, KnowledgeDocument, KnowledgeChunk

    tsquery = func.to_tsquery("simple", " | ".join(terms)) if terms else None
    rank = func.ts_rank_cd(c.search, tsquery) if tsquery is not None else literal(0.0, Float)
    boost = case((d.id.in_(identifiers), 1.0), else_=0.0) if identifiers else literal(0.0, Float)
    score = (rank + boost).label("score")

    stmt = (
        select(c, v, d, score)
        .join(v, v.id == c.version_id)
        .join(d, d.id == v.document_id)
        .where(
            d.status == "active",
            v.approval_status == "approved",
            d.region.in_([region, "ALL"]),
            valid_on(as_of),
        )
    )
    if tsquery is not None or identifiers:
        conditions = []
        if tsquery is not None:
            conditions.append(c.search.op("@@")(tsquery))
        if identifiers:
            conditions.append(d.id.in_(identifiers))
        stmt = stmt.where(or_(*conditions))
    else:
        stmt = stmt.where(literal(False))
    if doc_types:
        stmt = stmt.where(d.doc_type.in_(doc_types))
    if topics:
        stmt = stmt.where(d.topic.in_(topics))
    rows = (await session.execute(stmt.order_by(score.desc(), c.id).limit(limit))).all()

    results = [
        RetrievedChunk(
            rank=i + 1,
            chunk_id=chunk.id,
            document_id=doc.id,
            doc_type=doc.doc_type,
            title=doc.title,
            version=ver.version,
            heading=chunk.heading,
            text=chunk.text,
            content_complete=ver.content_complete,
            effective_from=ver.effective_from,
            effective_to=ver.effective_to,
            validity_source=ver.validity_source,
            score=float(s),
        )
        for i, (chunk, ver, doc, s) in enumerate(rows)
    ]
    log = RetrievalLog(
        ticket_id=ticket_id,
        requested_by=requested_by,
        query_redacted=query[:2000],
        region=region,
        as_of=as_of,
        filters={"doc_types": doc_types, "topics": topics, "limit": limit},
        mode="fulltext",
        result_count=len(results),
    )
    session.add(log)
    await session.flush()
    session.add_all(
        RetrievalResult(
            retrieval_id=log.id,
            rank=r.rank,
            chunk_id=r.chunk_id,
            document_id=r.document_id,
            score=r.score,
            effective_from=r.effective_from,
            effective_to=r.effective_to,
        )
        for r in results
    )
    return log.id, results


@dataclass(frozen=True)
class RateInForce:
    rule_id: str
    topic: str
    title: str
    value: str
    in_force_since: date | None
    in_force_until: date | None
    source: str


async def statutory_rates(session: AsyncSession, region: str, as_of: date) -> list[RateInForce]:
    """Mirror of the engine's /statutory/rates?region&as_of for the rules in the source data."""
    out: list[RateInForce] = []
    for r in await session.scalars(
        select(StatutoryRule).where(StatutoryRule.region == region).order_by(StatutoryRule.topic)
    ):
        if as_of >= r.effective_from:
            out.append(RateInForce(r.rule_id, r.topic, r.title, r.new_value, r.effective_from, None, r.source))
        else:
            until = r.effective_from - timedelta(days=1)
            out.append(RateInForce(r.rule_id, r.topic, r.title, r.old_value, None, until, r.source))
    return out

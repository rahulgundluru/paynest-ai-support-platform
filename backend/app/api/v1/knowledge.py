from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import Principal, SessionDep, SettingsDep, require
from app.core.rbac import Permission
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeDocumentVersion
from app.schemas.common import Page
from app.schemas.knowledge import (
    ChunkOut,
    DocumentDetail,
    DocumentOut,
    RateOut,
    SearchHit,
    SearchRequest,
    SearchResponse,
    VersionOut,
)
from app.services import audit
from app.services.knowledge.ingest import index_knowledge
from app.services.knowledge.retrieval import retrieve, statutory_rates
from app.services.pii.gate import PiiGate

router = APIRouter(tags=["knowledge"])
Reader = Annotated[Principal, Depends(require(Permission.KNOWLEDGE_READ))]
Manager = Annotated[Principal, Depends(require(Permission.KNOWLEDGE_MANAGE))]


def _in_force(v: KnowledgeDocumentVersion, day: date) -> bool:
    return (v.effective_from is None or v.effective_from <= day) and (v.effective_to is None or v.effective_to >= day)


def _doc_out(doc: KnowledgeDocument, today: date) -> DocumentOut:
    out = DocumentOut.model_validate(doc)
    out.version_count = len(doc.versions)
    current = [v for v in doc.versions if _in_force(v, today) and v.approval_status == "approved"]
    out.in_force_today = doc.status == "active" and bool(current)
    out.content_complete = any(v.content_complete for v in current)
    return out


@router.get("/knowledge/documents", response_model=Page[DocumentOut])
async def list_documents(
    session: SessionDep,
    _: Reader,
    doc_type: str | None = None,
    region: Annotated[str | None, Query(pattern="^(IN|UAE|ALL)$")] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> Page[DocumentOut]:
    query = select(KnowledgeDocument).options(selectinload(KnowledgeDocument.versions))
    if doc_type:
        query = query.where(KnowledgeDocument.doc_type == doc_type)
    if region:
        query = query.where(KnowledgeDocument.region == region)
    if q:
        query = query.where(KnowledgeDocument.title.ilike(f"%{q}%") | KnowledgeDocument.id.ilike(f"%{q}%"))
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    docs = await session.scalars(query.order_by(KnowledgeDocument.id).offset((page - 1) * page_size).limit(page_size))
    today = date.today()
    return Page[DocumentOut](items=[_doc_out(d, today) for d in docs], total=total, page=page, page_size=page_size)


async def _get_doc(session: SessionDep, document_id: str) -> KnowledgeDocument:
    doc = await session.scalar(
        select(KnowledgeDocument)
        .options(selectinload(KnowledgeDocument.versions))
        .where(KnowledgeDocument.id == document_id)
    )
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("/knowledge/documents/{document_id}", response_model=DocumentDetail)
async def get_document(document_id: str, session: SessionDep, _: Reader) -> DocumentDetail:
    doc = await _get_doc(session, document_id)
    return DocumentDetail(
        **_doc_out(doc, date.today()).model_dump(),
        metadata=doc.metadata_,
        versions=[VersionOut.model_validate(v) for v in doc.versions],
    )


@router.get("/knowledge/documents/{document_id}/chunks", response_model=list[ChunkOut])
async def get_chunks(document_id: str, session: SessionDep, _: Reader) -> list[ChunkOut]:
    rows = await session.execute(
        select(KnowledgeChunk, KnowledgeDocumentVersion.version)
        .join(KnowledgeDocumentVersion, KnowledgeDocumentVersion.id == KnowledgeChunk.version_id)
        .where(KnowledgeDocumentVersion.document_id == document_id)
        .order_by(KnowledgeDocumentVersion.version, KnowledgeChunk.seq)
    )
    return [
        ChunkOut(id=c.id, version=v, seq=c.seq, heading=c.heading, text=c.text, has_embedding=c.embedding is not None)
        for c, v in rows.all()
    ]


@router.post("/knowledge/index")
async def reindex(session: SessionDep, settings: SettingsDep, principal: Manager) -> dict[str, int]:
    counts = await index_knowledge(session, Path(settings.data_source_dir))
    await audit.record(session, "knowledge.indexed", actor_user_id=principal.user.id, details=counts)
    await session.commit()
    return counts


@router.post("/knowledge/documents/{document_id}/retire", response_model=DocumentOut)
async def retire(document_id: str, session: SessionDep, principal: Manager) -> DocumentOut:
    doc = await _get_doc(session, document_id)
    doc.status = "retired"
    await audit.record(
        session,
        "knowledge.retired",
        actor_user_id=principal.user.id,
        entity_type="knowledge_document",
        entity_id=doc.id,
    )
    await session.commit()
    return _doc_out(doc, date.today())


@router.post("/knowledge/search", response_model=SearchResponse)
async def search(body: SearchRequest, session: SessionDep, principal: Reader) -> SearchResponse:
    """Retrieval tester. The query is PII-redacted before it is searched or logged."""
    redacted = PiiGate().redact({"q": body.query}).fields["q"] or ""
    retrieval_id, hits = await retrieve(
        session,
        redacted,
        region=body.region,
        as_of=body.as_of,
        doc_types=body.doc_types,
        limit=body.limit,
        requested_by=principal.user.id,
    )
    await session.commit()
    return SearchResponse(
        retrieval_id=retrieval_id,
        query_redacted=redacted,
        mode="fulltext",
        hits=[SearchHit(**{k: getattr(h, k) for k in SearchHit.model_fields}) for h in hits],
    )


@router.get("/statutory/rates", response_model=list[RateOut])
async def rates(
    session: SessionDep,
    _: Reader,
    region: Annotated[str, Query(pattern="^(IN|UAE)$")],
    as_of: date | None = None,
) -> list[RateOut]:
    """Statutory parameters in force on `as_of` (default today), mirroring the engine's /statutory/rates."""
    return [RateOut(**r.__dict__) for r in await statutory_rates(session, region, as_of or date.today())]

"""Builds the knowledge base from the source mirror: KB article metadata, statutory rules, process documents.

Effective-date policy (docs/architecture/knowledge.md):
- Statutory rules carry their own effective dates. Each rule becomes two versions: the old value
  (valid until the day before `effective_from`) and the new value (valid from `effective_from`).
- A KB article whose topic is affected by a rule, and which was last reviewed BEFORE that rule took
  effect, cannot describe the new rule. Its validity therefore ends the day before the rule's
  effective date (validity_source = derived:<rule_id>). `last_reviewed` is used only to decide whether
  the article predates the change; it is never used as an effective date.
- Everything else has an unknown start (None) and no end (still in force).
Nothing is invented: articles without a body in the source are stored title-only and flagged
`content_complete = False`, which the answer engine treats as insufficient evidence.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.knowledge import KnowledgeChunk, KnowledgeDocument, KnowledgeDocumentVersion, StatutoryRule

KB_FILE = "data-room/data/kb_articles.json"
RULES_FILE = "data-room/integrations/statutory_rules.json"
PROCESS_DOCS = {
    "SOP-TRIAGE": "data-room/process/ticket_triage_sop.md",
    "SOP-ESCALATION": "data-room/process/escalation_policy.md",
    "SOP-PAYROLL-WEEK": "data-room/process/payroll_week_runbook.md",
    "SLA-SCHEDULE-3": "data-room/process/sla_contract_excerpt.md",
}
PLACEHOLDER_EXCERPT = "See full article in Confluence space SUP-KB."
MONTHS = {
    m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)
}


@dataclass
class VersionSpec:
    content: str
    content_complete: bool
    chunks: list[tuple[str | None, str]]
    effective_from: date | None = None
    effective_to: date | None = None
    validity_source: str = "not_stated_in_source"
    superseded_by: str | None = None


@dataclass
class DocSpec:
    id: str
    doc_type: str
    title: str
    region: str
    topic: str | None
    owner: str | None
    source_file: str
    source_sha256: str
    last_reviewed: date | None
    versions: list[VersionSpec]
    metadata: dict[str, Any] = field(default_factory=dict)


def _sha(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def _parse_day_month_year(text: str) -> date | None:
    m = re.search(r"(\d{1,2}) ([A-Za-z]{3})[a-z]* (\d{4})", text)
    if not m or m.group(2).lower() not in MONTHS:
        return None
    return date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))


def _markdown_chunks(markdown: str) -> list[tuple[str | None, str]]:
    chunks: list[tuple[str | None, str]] = []
    heading: str | None = None
    lines: list[str] = []
    for line in markdown.splitlines():
        if line.startswith("## "):
            if "".join(lines).strip():
                chunks.append((heading, "\n".join(lines).strip()))
            heading, lines = line[3:].strip(), []
        elif not line.startswith("# "):
            lines.append(line)
    if "".join(lines).strip():
        chunks.append((heading, "\n".join(lines).strip()))
    return chunks


def build_specs(source_dir: Path) -> tuple[list[DocSpec], list[dict[str, Any]]]:
    rules_bytes = (source_dir / RULES_FILE).read_bytes()
    rules = json.loads(rules_bytes)["rules"]
    specs: list[DocSpec] = []

    # 1. Statutory rules: two dated versions each.
    for r in rules:
        eff = date.fromisoformat(r["effective_from"])
        title = r["title"]
        before = f"{title} ({r['region']}). Value before {eff.isoformat()}: {r['old_value']}. Source: {r['source']}."
        after = (
            f"{title} ({r['region']}). In force from {eff.isoformat()}: {r['new_value']} "
            f"(previously {r['old_value']}). Source: {r['source']}. Rule {r['rule_id']}."
        )
        specs.append(
            DocSpec(
                id=r["rule_id"],
                doc_type="statutory_rule",
                title=title,
                region=r["region"],
                topic=r["topic"],
                owner="Compliance",
                source_file=RULES_FILE,
                source_sha256=_sha(rules_bytes),
                last_reviewed=None,
                metadata={"affects_kb_topics": r["affects_kb_topics"], "status": r["status"]},
                versions=[
                    VersionSpec(before, True, [(title, before)], None, eff - timedelta(days=1), "rule_effective_date"),
                    VersionSpec(after, True, [(title, after)], eff, None, "rule_effective_date"),
                ],
            )
        )

    # 2. KB article metadata (bodies are not in the source; excerpts exist for four articles).
    kb_bytes = (source_dir / KB_FILE).read_bytes()
    for a in json.loads(kb_bytes):
        excerpt = (a.get("excerpt") or "").strip()
        complete = bool(excerpt) and excerpt != PLACEHOLDER_EXCERPT
        content = f"{a['title']}. {excerpt}" if complete else a["title"]
        reviewed = date.fromisoformat(a["last_reviewed"]) if a.get("last_reviewed") else None
        version = VersionSpec(content, complete, [(a["title"], content)])
        for r in rules:
            eff = date.fromisoformat(r["effective_from"])
            if a["topic"] in r["affects_kb_topics"] and reviewed is not None and reviewed < eff:
                version.effective_to = eff - timedelta(days=1)
                version.validity_source = f"derived:{r['rule_id']}"
                version.superseded_by = r["rule_id"]
        specs.append(
            DocSpec(
                id=a["id"],
                doc_type="kb_article",
                title=a["title"],
                region=a["region"],
                topic=a["topic"],
                owner=a.get("owner"),
                source_file=KB_FILE,
                source_sha256=_sha(kb_bytes),
                last_reviewed=reviewed,
                metadata={"source_status": a.get("status"), "views_90d": a.get("views_90d")},
                versions=[version],
            )
        )

    # 3. Process documents (SOPs, runbook, SLA schedule).
    for doc_id, rel in PROCESS_DOCS.items():
        raw = (source_dir / rel).read_text(encoding="utf-8")
        title = raw.splitlines()[0].lstrip("# ").strip()
        reviewed_m = re.search(r"Last reviewed:\*\*\s*([^|\n]+)", raw)
        effective_m = re.search(r"on or after (\d{1,2} [A-Za-z]+ \d{4})", raw)
        version = VersionSpec(raw, True, _markdown_chunks(raw))
        if effective_m:
            version.effective_from = _parse_day_month_year(effective_m.group(1))
            version.validity_source = "document_header"
        specs.append(
            DocSpec(
                id=doc_id,
                doc_type="process_document",
                title=title,
                region="ALL",
                topic="process",
                owner=None,
                source_file=rel,
                source_sha256=_sha(raw),
                last_reviewed=_parse_day_month_year(reviewed_m.group(1)) if reviewed_m else None,
                versions=[version],
            )
        )
    return specs, rules


async def index_knowledge(session: AsyncSession, source_dir: Path) -> dict[str, int]:
    """Idempotent: a version is (re)created only when its content or validity window changes."""
    specs, rules = await asyncio.to_thread(build_specs, source_dir)
    rule_rows = [
        {
            "rule_id": r["rule_id"],
            "region": r["region"],
            "topic": r["topic"],
            "title": r["title"],
            "effective_from": date.fromisoformat(r["effective_from"]),
            "old_value": r["old_value"],
            "new_value": r["new_value"],
            "affects_kb_topics": r["affects_kb_topics"],
            "source": r["source"],
            "status": r["status"],
        }
        for r in rules
    ]
    stmt = insert(StatutoryRule).values(rule_rows)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[StatutoryRule.rule_id], set_={k: stmt.excluded[k] for k in rule_rows[0] if k != "rule_id"}
        )
    )
    counts = {"documents": 0, "versions_created": 0, "versions_unchanged": 0, "chunks_created": 0}
    existing = {
        d.id: d
        for d in await session.scalars(select(KnowledgeDocument).options(selectinload(KnowledgeDocument.versions)))
    }
    now = datetime.now(tz=UTC)
    for spec in specs:
        counts["documents"] += 1
        doc = existing.get(spec.id)
        if doc is None:
            doc = KnowledgeDocument(id=spec.id, versions=[])
            session.add(doc)
        doc.doc_type, doc.title, doc.region, doc.topic, doc.owner = (
            spec.doc_type, spec.title, spec.region, spec.topic, spec.owner,
        )  # fmt: skip
        doc.source_file, doc.source_sha256, doc.last_reviewed, doc.metadata_ = (
            spec.source_file, spec.source_sha256, spec.last_reviewed, spec.metadata,
        )  # fmt: skip
        known = {(v.content_sha256, v.effective_from, v.effective_to) for v in doc.versions}
        next_version = max((v.version for v in doc.versions), default=0)
        for vs in spec.versions:
            key = (_sha(vs.content), vs.effective_from, vs.effective_to)
            if key in known:
                counts["versions_unchanged"] += 1
                continue
            next_version += 1
            version = KnowledgeDocumentVersion(
                document=doc,
                version=next_version,
                content=vs.content,
                content_sha256=key[0],
                content_complete=vs.content_complete,
                effective_from=vs.effective_from,
                effective_to=vs.effective_to,
                validity_source=vs.validity_source,
                superseded_by=vs.superseded_by,
                approval_status="approved",  # published in the client's source systems
                indexed_at=now,
                chunks=[KnowledgeChunk(seq=i, heading=h, text=t) for i, (h, t) in enumerate(vs.chunks)],
            )
            session.add(version)
            counts["versions_created"] += 1
            counts["chunks_created"] += len(vs.chunks)
    await session.commit()
    return counts

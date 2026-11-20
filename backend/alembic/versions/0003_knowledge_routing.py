"""knowledge routing incidents

Revision ID: 0003_knowledge_routing
Revises: 0002_ticket_pipeline
Create Date: 2026-11-19 16:37:50.364162
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_knowledge_routing"
down_revision: str | None = "0002_ticket_pipeline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("doc_type", sa.String(length=20), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("region", sa.String(length=3), nullable=False),
        sa.Column("topic", sa.String(length=40), nullable=True),
        sa.Column("owner", sa.String(length=60), nullable=True),
        sa.Column("source_file", sa.String(length=200), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("last_reviewed", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "doc_type IN ('kb_article', 'statutory_rule', 'process_document')",
            name=op.f("ck_knowledge_documents_doc_type"),
        ),
        sa.CheckConstraint("region IN ('IN', 'UAE', 'ALL')", name=op.f("ck_knowledge_documents_region")),
        sa.CheckConstraint("status IN ('active', 'retired')", name=op.f("ck_knowledge_documents_status")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_documents")),
    )
    op.create_index(op.f("ix_knowledge_documents_topic"), "knowledge_documents", ["topic"], unique=False)
    op.create_table(
        "statutory_rules",
        sa.Column("rule_id", sa.String(length=30), nullable=False),
        sa.Column("region", sa.String(length=3), nullable=False),
        sa.Column("topic", sa.String(length=40), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=False),
        sa.Column("new_value", sa.Text(), nullable=False),
        sa.Column("affects_kb_topics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.CheckConstraint("region IN ('IN', 'UAE')", name=op.f("ck_statutory_rules_region")),
        sa.PrimaryKeyConstraint("rule_id", name=op.f("pk_statutory_rules")),
    )
    op.create_index(op.f("ix_statutory_rules_topic"), "statutory_rules", ["topic"], unique=False)
    op.create_table(
        "knowledge_document_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.String(length=40), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("content_complete", sa.Boolean(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("validity_source", sa.String(length=80), nullable=False),
        sa.Column("superseded_by", sa.String(length=40), nullable=True),
        sa.Column("approval_status", sa.String(length=12), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "approval_status IN ('approved', 'pending', 'rejected')",
            name=op.f("ck_knowledge_document_versions_approval_status"),
        ),
        sa.CheckConstraint(
            "effective_from IS NULL OR effective_to IS NULL OR effective_from <= effective_to",
            name=op.f("ck_knowledge_document_versions_window"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["knowledge_documents.id"],
            name=op.f("fk_knowledge_document_versions_document_id_knowledge_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_document_versions")),
        sa.UniqueConstraint("document_id", "version", name="uq_knowledge_document_versions_doc_version"),
    )
    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("version_id", sa.UUID(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("heading", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "search",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', coalesce(heading, '') || ' ' || text)", persisted=True),
            nullable=False,
        ),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=1024), nullable=True),
        sa.Column("embedding_model", sa.String(length=80), nullable=True),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["knowledge_document_versions.id"],
            name=op.f("fk_knowledge_chunks_version_id_knowledge_document_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_chunks")),
        sa.UniqueConstraint("version_id", "seq", name="uq_knowledge_chunks_version_seq"),
    )
    op.create_index("ix_knowledge_chunks_search", "knowledge_chunks", ["search"], unique=False, postgresql_using="gin")
    op.create_index(op.f("ix_knowledge_chunks_version_id"), "knowledge_chunks", ["version_id"], unique=False)
    op.create_table(
        "classifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ticket_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("prompt_version", sa.String(length=40), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=True),
        sa.Column("subcategory", sa.String(length=80), nullable=True),
        sa.Column("intent", sa.String(length=120), nullable=True),
        sa.Column("priority", sa.String(length=2), nullable=True),
        sa.Column("language", sa.String(length=12), nullable=True),
        sa.Column("is_injection", sa.Boolean(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("requires_human", sa.Boolean(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=True),
        sa.Column("error", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status IN ('ok', 'invalid', 'failed', 'unavailable')", name=op.f("ck_classifications_status")
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["tickets.id"], name=op.f("fk_classifications_ticket_id_tickets"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_classifications")),
    )
    op.create_index(op.f("ix_classifications_ticket_id"), "classifications", ["ticket_id"], unique=False)
    op.create_table(
        "incidents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("customer_id", sa.String(length=10), nullable=True),
        sa.Column("region", sa.String(length=3), nullable=True),
        sa.Column("master_ticket_id", sa.UUID(), nullable=False),
        sa.Column("owner_queue", sa.String(length=40), nullable=True),
        sa.Column("category", sa.String(length=20), nullable=True),
        sa.Column("rule_id", sa.String(length=10), nullable=False),
        sa.Column("rule_version", sa.String(length=30), nullable=False),
        sa.Column("first_ticket_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("declared_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('resubmission', 'incident')", name=op.f("ck_incidents_kind")),
        sa.CheckConstraint("status IN ('open', 'closed', 'dissolved')", name=op.f("ck_incidents_status")),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["customers.customer_id"], name=op.f("fk_incidents_customer_id_customers")
        ),
        sa.ForeignKeyConstraint(
            ["master_ticket_id"], ["tickets.id"], name=op.f("fk_incidents_master_ticket_id_tickets"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incidents")),
    )
    op.create_index(op.f("ix_incidents_customer_id"), "incidents", ["customer_id"], unique=False)
    op.create_index(op.f("ix_incidents_region"), "incidents", ["region"], unique=False)
    op.create_table(
        "model_usage",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("operation", sa.String(length=30), nullable=False),
        sa.Column("ticket_id", sa.UUID(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["tickets.id"], name=op.f("fk_model_usage_ticket_id_tickets"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_usage")),
    )
    op.create_index(op.f("ix_model_usage_ticket_id"), "model_usage", ["ticket_id"], unique=False)
    op.create_table(
        "retrieval_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ticket_id", sa.UUID(), nullable=True),
        sa.Column("requested_by", sa.UUID(), nullable=True),
        sa.Column("query_redacted", sa.Text(), nullable=False),
        sa.Column("region", sa.String(length=3), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("filters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], name=op.f("fk_retrieval_logs_requested_by_users")),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["tickets.id"], name=op.f("fk_retrieval_logs_ticket_id_tickets"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_retrieval_logs")),
    )
    op.create_index(op.f("ix_retrieval_logs_ticket_id"), "retrieval_logs", ["ticket_id"], unique=False)
    op.create_table(
        "routing_decisions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("ticket_id", sa.UUID(), nullable=False),
        sa.Column("lane", sa.String(length=20), nullable=False),
        sa.Column("queue", sa.String(length=40), nullable=False),
        sa.Column("support_level", sa.String(length=12), nullable=False),
        sa.Column("rule_id", sa.String(length=10), nullable=False),
        sa.Column("rule_version", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False),
        sa.Column("inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("inputs_sha256", sa.String(length=64), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "lane IN ('auto_answer', 'draft_for_agent', 'route_queue', 'incident', 'human_review', 'block')",
            name=op.f("ck_routing_decisions_lane"),
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["tickets.id"], name=op.f("fk_routing_decisions_ticket_id_tickets"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_routing_decisions")),
    )
    op.create_index(op.f("ix_routing_decisions_ticket_id"), "routing_decisions", ["ticket_id"], unique=False)
    op.create_table(
        "incident_links",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("incident_id", sa.UUID(), nullable=False),
        sa.Column("ticket_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=10), nullable=False),
        sa.Column("rule_id", sa.String(length=10), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("linked_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role IN ('master', 'member', 'resubmit')", name=op.f("ck_incident_links_role")),
        sa.ForeignKeyConstraint(
            ["incident_id"], ["incidents.id"], name=op.f("fk_incident_links_incident_id_incidents"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["linked_by"], ["users.id"], name=op.f("fk_incident_links_linked_by_users")),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["tickets.id"], name=op.f("fk_incident_links_ticket_id_tickets"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incident_links")),
        sa.UniqueConstraint("incident_id", "ticket_id", name="uq_incident_links_incident_ticket"),
    )
    op.create_index(op.f("ix_incident_links_ticket_id"), "incident_links", ["ticket_id"], unique=False)
    op.create_table(
        "retrieval_results",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("retrieval_id", sa.UUID(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.BigInteger(), nullable=False),
        sa.Column("document_id", sa.String(length=40), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["knowledge_chunks.id"],
            name=op.f("fk_retrieval_results_chunk_id_knowledge_chunks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["retrieval_id"],
            ["retrieval_logs.id"],
            name=op.f("fk_retrieval_results_retrieval_id_retrieval_logs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_retrieval_results")),
    )
    op.create_index(op.f("ix_retrieval_results_retrieval_id"), "retrieval_results", ["retrieval_id"], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    op.drop_index(op.f("ix_retrieval_results_retrieval_id"), table_name="retrieval_results")
    op.drop_table("retrieval_results")
    op.drop_index(op.f("ix_incident_links_ticket_id"), table_name="incident_links")
    op.drop_table("incident_links")
    op.drop_index(op.f("ix_routing_decisions_ticket_id"), table_name="routing_decisions")
    op.drop_table("routing_decisions")
    op.drop_index(op.f("ix_retrieval_logs_ticket_id"), table_name="retrieval_logs")
    op.drop_table("retrieval_logs")
    op.drop_index(op.f("ix_model_usage_ticket_id"), table_name="model_usage")
    op.drop_table("model_usage")
    op.drop_index(op.f("ix_incidents_region"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_customer_id"), table_name="incidents")
    op.drop_table("incidents")
    op.drop_index(op.f("ix_classifications_ticket_id"), table_name="classifications")
    op.drop_table("classifications")
    op.drop_index(op.f("ix_knowledge_chunks_version_id"), table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_search", table_name="knowledge_chunks", postgresql_using="gin")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_document_versions")
    op.drop_index(op.f("ix_statutory_rules_topic"), table_name="statutory_rules")
    op.drop_table("statutory_rules")
    op.drop_index(op.f("ix_knowledge_documents_topic"), table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
    # ### end Alembic commands ###

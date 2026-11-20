"""ticket pipeline

Revision ID: 0002_ticket_pipeline
Revises: 0001_baseline
Create Date: 2026-11-19 16:08:15.491921
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_ticket_pipeline"
down_revision: str | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("agent_id", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("tier", sa.String(length=2), nullable=False),
        sa.Column("desk", sa.String(length=40), nullable=False),
        sa.Column("languages", postgresql.ARRAY(sa.String(length=8)), nullable=False),
        sa.Column("hire_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("left_date", sa.Date(), nullable=True),
        sa.CheckConstraint("status IN ('active', 'left')", name=op.f("ck_agents_status")),
        sa.CheckConstraint("tier IN ('L1', 'L2', 'L3')", name=op.f("ck_agents_tier")),
        sa.PrimaryKeyConstraint("agent_id", name=op.f("pk_agents")),
    )
    op.create_table(
        "customers",
        sa.Column("customer_id", sa.String(length=10), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("tier", sa.String(length=12), nullable=False),
        sa.Column("region", sa.String(length=3), nullable=False),
        sa.Column("monthly_fee_usd", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("employees_paid", sa.Integer(), nullable=True),
        sa.Column("source_file", sa.String(length=200), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.CheckConstraint("region IN ('IN', 'UAE')", name=op.f("ck_customers_region")),
        sa.CheckConstraint("tier IN ('Enterprise', 'Business', 'Standard')", name=op.f("ck_customers_tier")),
        sa.CheckConstraint("monthly_fee_usd >= 0", name=op.f("ck_customers_fee_non_negative")),
        sa.PrimaryKeyConstraint("customer_id", name=op.f("pk_customers")),
    )
    op.create_index(op.f("ix_customers_region"), "customers", ["region"], unique=False)
    op.create_table(
        "sla_terms",
        sa.Column("template_version", sa.String(length=8), nullable=False),
        sa.Column("tier", sa.String(length=12), nullable=False),
        sa.Column("priority", sa.String(length=2), nullable=False),
        sa.Column("first_response_h", sa.Numeric(precision=5, scale=1), nullable=False),
        sa.Column("resolution_h", sa.Numeric(precision=5, scale=1), nullable=False),
        sa.Column("credit_pct", sa.Numeric(precision=4, scale=1), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.CheckConstraint("priority IN ('P1', 'P2', 'P3')", name=op.f("ck_sla_terms_priority")),
        sa.CheckConstraint("tier IN ('Enterprise', 'Business', 'Standard')", name=op.f("ck_sla_terms_tier")),
        sa.PrimaryKeyConstraint("template_version", "tier", "priority", name=op.f("pk_sla_terms")),
    )
    op.create_table(
        "finance_sla_breaches",
        sa.Column("breach_id", sa.String(length=10), nullable=False),
        sa.Column("ticket_external_id", sa.String(length=12), nullable=False),
        sa.Column("customer_id", sa.String(length=10), nullable=False),
        sa.Column("tier", sa.String(length=12), nullable=False),
        sa.Column("priority", sa.String(length=2), nullable=False),
        sa.Column("target_h", sa.Numeric(precision=6, scale=1), nullable=False),
        sa.Column("actual_resolution_h", sa.Numeric(precision=8, scale=1), nullable=False),
        sa.Column("credit_pct", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("monthly_fee_usd", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("credit_usd", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("invoice_month", sa.String(length=7), nullable=False),
        sa.Column("agent_noted_reason", sa.String(length=100), nullable=True),
        sa.Column("approved_by", sa.String(length=60), nullable=True),
        sa.Column("loaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["customers.customer_id"], name=op.f("fk_finance_sla_breaches_customer_id_customers")
        ),
        sa.PrimaryKeyConstraint("breach_id", name=op.f("pk_finance_sla_breaches")),
    )
    op.create_index(
        op.f("ix_finance_sla_breaches_ticket_external_id"), "finance_sla_breaches", ["ticket_external_id"], unique=False
    )
    op.create_table(
        "ingestion_batches",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("triggered_by", sa.UUID(), nullable=True),
        sa.Column("source_commit", sa.String(length=40), nullable=True),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint("status IN ('running', 'completed', 'failed')", name=op.f("ck_ingestion_batches_status")),
        sa.ForeignKeyConstraint(["triggered_by"], ["users.id"], name=op.f("fk_ingestion_batches_triggered_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_batches")),
    )
    op.create_table(
        "source_records",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=False),
        sa.Column("source_file", sa.String(length=200), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("record_index", sa.Integer(), nullable=False),
        sa.Column("record_hash", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=20), nullable=True),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("region", sa.String(length=3), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("status_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("duplicate_of_record_id", sa.BigInteger(), nullable=True),
        sa.Column("raw_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "channel IN ('email', 'widget', 'partner_portal', 'whatsapp', 'phone')",
            name=op.f("ck_source_records_channel"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'processed', 'failed', 'requires_review', 'duplicate', 'skipped')",
            name=op.f("ck_source_records_status"),
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["ingestion_batches.id"], name=op.f("fk_source_records_batch_id_ingestion_batches")
        ),
        sa.ForeignKeyConstraint(
            ["duplicate_of_record_id"],
            ["source_records.id"],
            name=op.f("fk_source_records_duplicate_of_record_id_source_records"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_records")),
        sa.UniqueConstraint("source_file", "record_index", name="uq_source_records_file_index"),
    )
    op.create_index(op.f("ix_source_records_batch_id"), "source_records", ["batch_id"], unique=False)
    op.create_index(op.f("ix_source_records_external_id"), "source_records", ["external_id"], unique=False)
    op.create_table(
        "pii_vault",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("source_record_id", sa.BigInteger(), nullable=False),
        sa.Column("token", sa.String(length=30), nullable=False),
        sa.Column("entity_type", sa.String(length=20), nullable=False),
        sa.Column("region", sa.String(length=3), nullable=True),
        sa.Column("value_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_record_id"], ["source_records.id"], name=op.f("fk_pii_vault_source_record_id_source_records")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pii_vault")),
        sa.UniqueConstraint("source_record_id", "token", name="uq_pii_vault_record_token"),
    )
    op.create_table(
        "tickets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=20), nullable=True),
        sa.Column("source_record_id", sa.BigInteger(), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("customer_id", sa.String(length=10), nullable=True),
        sa.Column("customer_resolution", sa.String(length=32), nullable=False),
        sa.Column("region", sa.String(length=3), nullable=True),
        sa.Column("region_source", sa.String(length=32), nullable=True),
        sa.Column("partner_id", sa.String(length=10), nullable=True),
        sa.Column("subject_redacted", sa.Text(), nullable=True),
        sa.Column("body_redacted", sa.Text(), nullable=True),
        sa.Column("language_hint", sa.String(length=12), nullable=True),
        sa.Column("priority", sa.String(length=2), nullable=True),
        sa.Column("customer_category", sa.String(length=20), nullable=True),
        sa.Column("final_category_label", sa.String(length=20), nullable=True),
        sa.Column("first_queue", sa.String(length=40), nullable=True),
        sa.Column("final_queue", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_response_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reassignment_count", sa.Integer(), nullable=False),
        sa.Column("reopen_count", sa.Integer(), nullable=False),
        sa.Column("in_payroll_window", sa.Boolean(), nullable=False),
        sa.Column("ingestion_status", sa.String(length=16), nullable=False),
        sa.Column("review_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "channel IN ('email', 'widget', 'partner_portal', 'whatsapp', 'phone')", name=op.f("ck_tickets_channel")
        ),
        sa.CheckConstraint(
            "customer_category IS NULL OR customer_category IN ('payroll', 'statutory', 'how_to', 'reports', 'leave_attendance', 'integration', 'billing', 'access_login', 'onboarding')",
            name=op.f("ck_tickets_category"),
        ),
        sa.CheckConstraint(
            "customer_resolution IN ('direct', 'partner_end_customer_name', 'whatsapp_customer_hint', 'unresolved')",
            name=op.f("ck_tickets_customer_resolution"),
        ),
        sa.CheckConstraint(
            "ingestion_status IN ('pending', 'processing', 'processed', 'failed', 'requires_review', 'duplicate', 'skipped')",
            name=op.f("ck_tickets_ingestion_status"),
        ),
        sa.CheckConstraint("priority IS NULL OR priority IN ('P1', 'P2', 'P3')", name=op.f("ck_tickets_priority")),
        sa.CheckConstraint("region IS NULL OR region IN ('IN', 'UAE')", name=op.f("ck_tickets_region")),
        sa.ForeignKeyConstraint(
            ["customer_id"], ["customers.customer_id"], name=op.f("fk_tickets_customer_id_customers")
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"], ["source_records.id"], name=op.f("fk_tickets_source_record_id_source_records")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tickets")),
        sa.UniqueConstraint("external_id", name=op.f("uq_tickets_external_id")),
    )
    op.create_index(op.f("ix_tickets_channel"), "tickets", ["channel"], unique=False)
    op.create_index(op.f("ix_tickets_created_at"), "tickets", ["created_at"], unique=False)
    op.create_index(op.f("ix_tickets_customer_category"), "tickets", ["customer_category"], unique=False)
    op.create_index(op.f("ix_tickets_customer_id"), "tickets", ["customer_id"], unique=False)
    op.create_index(op.f("ix_tickets_final_queue"), "tickets", ["final_queue"], unique=False)
    op.create_index(op.f("ix_tickets_ingestion_status"), "tickets", ["ingestion_status"], unique=False)
    op.create_index(op.f("ix_tickets_priority"), "tickets", ["priority"], unique=False)
    op.create_index(op.f("ix_tickets_region"), "tickets", ["region"], unique=False)
    op.create_table(
        "normalization_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("source_record_id", sa.BigInteger(), nullable=False),
        sa.Column("ticket_id", sa.UUID(), nullable=True),
        sa.Column("field", sa.String(length=40), nullable=False),
        sa.Column("original_value", sa.String(length=200), nullable=True),
        sa.Column("normalized_value", sa.String(length=200), nullable=True),
        sa.Column("rule", sa.String(length=60), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["source_records.id"],
            name=op.f("fk_normalization_log_source_record_id_source_records"),
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["tickets.id"], name=op.f("fk_normalization_log_ticket_id_tickets"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_normalization_log")),
    )
    op.create_index(
        op.f("ix_normalization_log_source_record_id"), "normalization_log", ["source_record_id"], unique=False
    )
    op.create_index(op.f("ix_normalization_log_ticket_id"), "normalization_log", ["ticket_id"], unique=False)
    op.create_table(
        "pii_detections",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("source_record_id", sa.BigInteger(), nullable=False),
        sa.Column("ticket_id", sa.UUID(), nullable=True),
        sa.Column("field", sa.String(length=60), nullable=False),
        sa.Column("entity_type", sa.String(length=20), nullable=False),
        sa.Column("token", sa.String(length=30), nullable=False),
        sa.Column("start", sa.Integer(), nullable=False),
        sa.Column("end", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(length=30), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("checksum_valid", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(
            ["source_record_id"], ["source_records.id"], name=op.f("fk_pii_detections_source_record_id_source_records")
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["tickets.id"], name=op.f("fk_pii_detections_ticket_id_tickets"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pii_detections")),
    )
    op.create_index(op.f("ix_pii_detections_entity_type"), "pii_detections", ["entity_type"], unique=False)
    op.create_index(op.f("ix_pii_detections_source_record_id"), "pii_detections", ["source_record_id"], unique=False)
    op.create_index(op.f("ix_pii_detections_ticket_id"), "pii_detections", ["ticket_id"], unique=False)
    op.create_table(
        "sla_tracking",
        sa.Column("ticket_id", sa.UUID(), nullable=False),
        sa.Column("applicable", sa.Boolean(), nullable=False),
        sa.Column("not_applicable_reason", sa.String(length=60), nullable=True),
        sa.Column("template_version", sa.String(length=8), nullable=True),
        sa.Column("tier", sa.String(length=12), nullable=True),
        sa.Column("priority", sa.String(length=2), nullable=True),
        sa.Column("first_response_target_h", sa.Numeric(precision=5, scale=1), nullable=True),
        sa.Column("resolution_target_h", sa.Numeric(precision=5, scale=1), nullable=True),
        sa.Column("first_response_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_response_hours", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("resolution_hours", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("first_response_breached", sa.Boolean(), nullable=True),
        sa.Column("resolution_breached", sa.Boolean(), nullable=True),
        sa.Column("severity_multiplier", sa.Numeric(precision=3, scale=1), nullable=True),
        sa.Column("credit_pct", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("credit_usd", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("rule_version", sa.String(length=20), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["tickets.id"], name=op.f("fk_sla_tracking_ticket_id_tickets"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("ticket_id", name=op.f("pk_sla_tracking")),
    )
    op.create_index(op.f("ix_sla_tracking_resolution_breached"), "sla_tracking", ["resolution_breached"], unique=False)
    op.create_table(
        "ticket_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("ticket_id", sa.UUID(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=12), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(length=20), nullable=True),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('created', 'assigned', 'replied', 'reassigned', 'escalated', 'reopened', 'resolved')",
            name=op.f("ck_ticket_events_event_type"),
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["tickets.id"], name=op.f("fk_ticket_events_ticket_id_tickets"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_events")),
        sa.UniqueConstraint("ticket_id", "seq", name="uq_ticket_events_ticket_seq"),
    )
    op.create_index(op.f("ix_ticket_events_ticket_id"), "ticket_events", ["ticket_id"], unique=False)
    op.create_table(
        "ticket_messages",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("ticket_id", sa.UUID(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("author_type", sa.String(length=10), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("body_redacted", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "author_type IN ('customer', 'agent', 'system')", name=op.f("ck_ticket_messages_author_type")
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["tickets.id"], name=op.f("fk_ticket_messages_ticket_id_tickets"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ticket_messages")),
        sa.UniqueConstraint("ticket_id", "seq", name="uq_ticket_messages_ticket_seq"),
    )
    op.create_index(op.f("ix_ticket_messages_ticket_id"), "ticket_messages", ["ticket_id"], unique=False)
    # Contract Schedule 3, template v3.2 (data-room/process/sla_contract_excerpt.md). Standard tier is
    # "best effort" with no credits, so it has no numeric targets and no rows here.
    sla_terms = sa.table(
        "sla_terms",
        sa.column("template_version", sa.String),
        sa.column("tier", sa.String),
        sa.column("priority", sa.String),
        sa.column("first_response_h", sa.Numeric),
        sa.column("resolution_h", sa.Numeric),
        sa.column("credit_pct", sa.Numeric),
        sa.column("source", sa.Text),
    )
    src = "data-room/process/sla_contract_excerpt.md §3.1, §3.4 (template v3.2)"
    op.bulk_insert(
        sla_terms,
        [
            {
                "template_version": "v3.2",
                "tier": t,
                "priority": p,
                "first_response_h": fr,
                "resolution_h": rs,
                "credit_pct": cr,
                "source": src,
            }
            for t, p, fr, rs, cr in [
                ("Enterprise", "P1", 1, 8, 10),
                ("Enterprise", "P2", 4, 24, 5),
                ("Enterprise", "P3", 8, 72, 2),
                ("Business", "P1", 2, 12, 5),
                ("Business", "P2", 8, 48, 3),
                ("Business", "P3", 24, 96, 1),
            ]
        ],
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    op.drop_index(op.f("ix_ticket_messages_ticket_id"), table_name="ticket_messages")
    op.drop_table("ticket_messages")
    op.drop_index(op.f("ix_ticket_events_ticket_id"), table_name="ticket_events")
    op.drop_table("ticket_events")
    op.drop_index(op.f("ix_sla_tracking_resolution_breached"), table_name="sla_tracking")
    op.drop_table("sla_tracking")
    op.drop_index(op.f("ix_pii_detections_ticket_id"), table_name="pii_detections")
    op.drop_index(op.f("ix_pii_detections_source_record_id"), table_name="pii_detections")
    op.drop_index(op.f("ix_pii_detections_entity_type"), table_name="pii_detections")
    op.drop_table("pii_detections")
    op.drop_index(op.f("ix_normalization_log_ticket_id"), table_name="normalization_log")
    op.drop_index(op.f("ix_normalization_log_source_record_id"), table_name="normalization_log")
    op.drop_table("normalization_log")
    op.drop_index(op.f("ix_tickets_region"), table_name="tickets")
    op.drop_index(op.f("ix_tickets_priority"), table_name="tickets")
    op.drop_index(op.f("ix_tickets_ingestion_status"), table_name="tickets")
    op.drop_index(op.f("ix_tickets_final_queue"), table_name="tickets")
    op.drop_index(op.f("ix_tickets_customer_id"), table_name="tickets")
    op.drop_index(op.f("ix_tickets_customer_category"), table_name="tickets")
    op.drop_index(op.f("ix_tickets_created_at"), table_name="tickets")
    op.drop_index(op.f("ix_tickets_channel"), table_name="tickets")
    op.drop_table("tickets")
    op.drop_table("pii_vault")
    op.drop_index(op.f("ix_source_records_external_id"), table_name="source_records")
    op.drop_index(op.f("ix_source_records_batch_id"), table_name="source_records")
    op.drop_table("source_records")
    op.drop_table("ingestion_batches")
    op.drop_index(op.f("ix_finance_sla_breaches_ticket_external_id"), table_name="finance_sla_breaches")
    op.drop_table("finance_sla_breaches")
    op.drop_table("sla_terms")
    op.drop_index(op.f("ix_customers_region"), table_name="customers")
    op.drop_table("customers")
    op.drop_table("agents")
    # ### end Alembic commands ###

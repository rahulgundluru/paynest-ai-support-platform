"""ticket intake, pipeline runs and AI usage accounting

Revision ID: 0007_ticket_intake_ai
Revises: 0006_evaluation
Create Date: 2026-11-20 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_ticket_intake_ai"
down_revision: str | None = "0006_evaluation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Tickets entered in the app get ids PN-200001 upward, far from the source data's PN-100001..PN-101526.
    op.execute("CREATE SEQUENCE app_ticket_seq START WITH 200001 MINVALUE 200001 MAXVALUE 999999")

    op.add_column("tickets", sa.Column("origin", sa.String(length=8), server_default="import", nullable=False))
    op.create_check_constraint(op.f("ck_tickets_origin"), "tickets", "origin IN ('import', 'app')")
    op.create_index(op.f("ix_tickets_origin"), "tickets", ["origin"], unique=False)

    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ticket_id", sa.UUID(), nullable=False),
        sa.Column("trigger", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("steps", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ai_enabled", sa.Boolean(), nullable=False),
        sa.Column("total_cost_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("error", sa.String(length=200), nullable=True),
        sa.Column("started_by", sa.UUID(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("trigger IN ('create', 'rerun')", name=op.f("ck_pipeline_runs_trigger")),
        sa.CheckConstraint("status IN ('running', 'completed', 'failed')", name=op.f("ck_pipeline_runs_status")),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["tickets.id"], name=op.f("fk_pipeline_runs_ticket_id_tickets"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["started_by"], ["users.id"], name=op.f("fk_pipeline_runs_started_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pipeline_runs")),
    )
    op.create_index(op.f("ix_pipeline_runs_ticket_id"), "pipeline_runs", ["ticket_id"], unique=False)

    op.add_column("model_usage", sa.Column("pipeline_run_id", sa.UUID(), nullable=True))
    op.add_column("model_usage", sa.Column("prompt_version", sa.String(length=40), nullable=True))
    op.add_column("model_usage", sa.Column("cost_source", sa.String(length=20), nullable=True))
    op.add_column("model_usage", sa.Column("error", sa.String(length=40), nullable=True))
    op.add_column("model_usage", sa.Column("request_id", sa.String(length=80), nullable=True))
    op.add_column("model_usage", sa.Column("upstream_provider", sa.String(length=60), nullable=True))
    op.create_foreign_key(
        op.f("fk_model_usage_pipeline_run_id_pipeline_runs"), "model_usage", "pipeline_runs",
        ["pipeline_run_id"], ["id"], ondelete="SET NULL",
    )  # fmt: skip
    op.create_index(op.f("ix_model_usage_pipeline_run_id"), "model_usage", ["pipeline_run_id"], unique=False)
    op.create_index(op.f("ix_model_usage_created_at"), "model_usage", ["created_at"], unique=False)
    # Existing rows were priced from configured per-token prices.
    op.execute("UPDATE model_usage SET cost_source = 'price_table' WHERE estimated_cost_usd IS NOT NULL")


def downgrade() -> None:
    op.drop_index(op.f("ix_model_usage_created_at"), table_name="model_usage")
    op.drop_index(op.f("ix_model_usage_pipeline_run_id"), table_name="model_usage")
    op.drop_constraint(op.f("fk_model_usage_pipeline_run_id_pipeline_runs"), "model_usage", type_="foreignkey")
    for column in ("upstream_provider", "request_id", "error", "cost_source", "prompt_version", "pipeline_run_id"):
        op.drop_column("model_usage", column)
    op.drop_index(op.f("ix_pipeline_runs_ticket_id"), table_name="pipeline_runs")
    op.drop_table("pipeline_runs")
    op.drop_index(op.f("ix_tickets_origin"), table_name="tickets")
    op.drop_constraint(op.f("ck_tickets_origin"), "tickets", type_="check")
    op.drop_column("tickets", "origin")
    op.execute("DROP SEQUENCE app_ticket_seq")

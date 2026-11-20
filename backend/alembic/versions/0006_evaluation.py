"""evaluation costs

Revision ID: 0006_evaluation
Revises: 0005_system_configurations
Create Date: 2026-11-19 18:20:20.545777
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_evaluation"
down_revision: str | None = "0005_system_configurations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "monthly_costs",
        sa.Column("month", sa.String(length=7), nullable=False),
        sa.Column("tickets_received_all_customers", sa.Integer(), nullable=False),
        sa.Column("tickets_in_ops_extract", sa.Integer(), nullable=True),
        sa.Column("agent_fte", sa.Integer(), nullable=False),
        sa.Column("agent_loaded_cost_usd", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("tooling_usd", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("vendor_pilot_usd", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("sla_credits_paid_usd", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("cost_per_ticket_excl_credits_usd", sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column("cost_per_ticket_incl_credits_usd", sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("month", name=op.f("pk_monthly_costs")),
    )
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("gate", sa.String(length=4), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("dataset", sa.Text(), nullable=False),
        sa.Column("dataset_size", sa.Integer(), nullable=False),
        sa.Column("target", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("notes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("critical", sa.Boolean(), nullable=False),
        sa.Column("source_commit", sa.String(length=40), nullable=True),
        sa.Column("triggered_by", sa.UUID(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('pass', 'fail', 'partial', 'not_run')", name=op.f("ck_evaluation_runs_status")),
        sa.ForeignKeyConstraint(["triggered_by"], ["users.id"], name=op.f("fk_evaluation_runs_triggered_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation_runs")),
    )
    op.create_index(op.f("ix_evaluation_runs_gate"), "evaluation_runs", ["gate"], unique=False)
    op.create_table(
        "evaluation_results",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("case_id", sa.String(length=80), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["evaluation_runs.id"],
            name=op.f("fk_evaluation_results_run_id_evaluation_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation_results")),
    )
    op.create_index(op.f("ix_evaluation_results_run_id"), "evaluation_results", ["run_id"], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    op.drop_index(op.f("ix_evaluation_results_run_id"), table_name="evaluation_results")
    op.drop_table("evaluation_results")
    op.drop_index(op.f("ix_evaluation_runs_gate"), table_name="evaluation_runs")
    op.drop_table("evaluation_runs")
    op.drop_table("monthly_costs")
    # ### end Alembic commands ###

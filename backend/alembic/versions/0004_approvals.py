"""approvals memory

Revision ID: 0004_approvals
Revises: 0003_knowledge_routing
Create Date: 2026-11-19 17:03:31.472696
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_approvals"
down_revision: str | None = "0003_knowledge_routing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ticket_id", sa.UUID(), nullable=False),
        sa.Column("routing_decision_id", sa.BigInteger(), nullable=True),
        sa.Column("region", sa.String(length=3), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("lane", sa.String(length=20), nullable=False),
        sa.Column("queue", sa.String(length=40), nullable=False),
        sa.Column("rule_id", sa.String(length=10), nullable=False),
        sa.Column("escalation_reason", sa.Text(), nullable=False),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("draft_text", sa.Text(), nullable=True),
        sa.Column("draft_source", sa.String(length=10), nullable=False),
        sa.Column("validation", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("decided_by", sa.UUID(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("draft_source IN ('none', 'ai', 'human')", name=op.f("ck_approvals_draft_source")),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'escalated', 'resolved')", name=op.f("ck_approvals_status")
        ),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], name=op.f("fk_approvals_decided_by_users")),
        sa.ForeignKeyConstraint(
            ["routing_decision_id"],
            ["routing_decisions.id"],
            name=op.f("fk_approvals_routing_decision_id_routing_decisions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["tickets.id"], name=op.f("fk_approvals_ticket_id_tickets"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approvals")),
    )
    op.create_index(op.f("ix_approvals_queue"), "approvals", ["queue"], unique=False)
    op.create_index(op.f("ix_approvals_region"), "approvals", ["region"], unique=False)
    op.create_index(op.f("ix_approvals_status"), "approvals", ["status"], unique=False)
    op.create_index(op.f("ix_approvals_ticket_id"), "approvals", ["ticket_id"], unique=False)
    op.create_table(
        "approval_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("approval_id", sa.UUID(), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("from_status", sa.String(length=12), nullable=True),
        sa.Column("to_status", sa.String(length=12), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name=op.f("fk_approval_events_actor_user_id_users")),
        sa.ForeignKeyConstraint(
            ["approval_id"], ["approvals.id"], name=op.f("fk_approval_events_approval_id_approvals"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_events")),
    )
    op.create_index(op.f("ix_approval_events_approval_id"), "approval_events", ["approval_id"], unique=False)
    op.create_table(
        "learned_memory",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("approval_id", sa.UUID(), nullable=False),
        sa.Column("ticket_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.String(length=10), nullable=True),
        sa.Column("region", sa.String(length=3), nullable=True),
        sa.Column("category", sa.String(length=20), nullable=True),
        sa.Column("resolution_text", sa.Text(), nullable=False),
        sa.Column("cited_versions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("approved_by", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["approval_id"], ["approvals.id"], name=op.f("fk_learned_memory_approval_id_approvals"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], name=op.f("fk_learned_memory_approved_by_users")),
        sa.ForeignKeyConstraint(
            ["ticket_id"], ["tickets.id"], name=op.f("fk_learned_memory_ticket_id_tickets"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_learned_memory")),
        sa.UniqueConstraint("approval_id", name=op.f("uq_learned_memory_approval_id")),
    )
    op.create_index(op.f("ix_learned_memory_category"), "learned_memory", ["category"], unique=False)
    op.create_index(op.f("ix_learned_memory_region"), "learned_memory", ["region"], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    op.drop_index(op.f("ix_learned_memory_region"), table_name="learned_memory")
    op.drop_index(op.f("ix_learned_memory_category"), table_name="learned_memory")
    op.drop_table("learned_memory")
    op.drop_index(op.f("ix_approval_events_approval_id"), table_name="approval_events")
    op.drop_table("approval_events")
    op.drop_index(op.f("ix_approvals_ticket_id"), table_name="approvals")
    op.drop_index(op.f("ix_approvals_status"), table_name="approvals")
    op.drop_index(op.f("ix_approvals_region"), table_name="approvals")
    op.drop_index(op.f("ix_approvals_queue"), table_name="approvals")
    op.drop_table("approvals")
    # ### end Alembic commands ###

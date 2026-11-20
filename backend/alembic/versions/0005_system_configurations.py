"""system configurations

Revision ID: 0005_system_configurations
Revises: 0004_approvals
Create Date: 2026-11-19 17:24:29.811072
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_system_configurations"
down_revision: str | None = "0004_approvals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "system_configurations",
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], name=op.f("fk_system_configurations_updated_by_users")),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_system_configurations")),
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    op.drop_table("system_configurations")
    # ### end Alembic commands ###

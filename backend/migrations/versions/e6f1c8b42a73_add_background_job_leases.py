"""add background job leases

Revision ID: e6f1c8b42a73
Revises: d5e9a7c31b42
Create Date: 2026-09-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e6f1c8b42a73"
down_revision: Union[str, Sequence[str], None] = "d5e9a7c31b42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("background_jobs") as batch_op:
        batch_op.add_column(sa.Column("claimed_by", sa.String(length=200), nullable=True))
        batch_op.add_column(sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index(
            "ix_background_jobs_running_heartbeat", ["status", "heartbeat_at"]
        )


def downgrade() -> None:
    with op.batch_alter_table("background_jobs") as batch_op:
        batch_op.drop_index("ix_background_jobs_running_heartbeat")
        batch_op.drop_column("heartbeat_at")
        batch_op.drop_column("claimed_by")

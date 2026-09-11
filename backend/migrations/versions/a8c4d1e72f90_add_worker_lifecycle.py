"""add worker lifecycle

Revision ID: a8c4d1e72f90
Revises: f7b3c9d42e61
Create Date: 2026-09-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a8c4d1e72f90"
down_revision: Union[str, Sequence[str], None] = "f7b3c9d42e61"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workers",
        sa.Column("worker_id", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('RUNNING', 'STOPPED')", name="valid_status"),
        sa.PrimaryKeyConstraint("worker_id"),
    )
    op.create_index(
        "ix_workers_status_heartbeat", "workers", ["status", "heartbeat_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_workers_status_heartbeat", table_name="workers")
    op.drop_table("workers")

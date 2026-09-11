"""add background job priorities

Revision ID: d4a8c2f71e95
Revises: b7e3f9a21c64
Create Date: 2026-09-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4a8c2f71e95"
down_revision: Union[str, Sequence[str], None] = "b7e3f9a21c64"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_background_jobs_queue", table_name="background_jobs")
    with op.batch_alter_table("background_jobs") as batch:
        batch.add_column(sa.Column(
            "priority", sa.String(length=12), nullable=False, server_default="NORMAL"
        ))
        batch.create_check_constraint(
            "valid_priority", "priority IN ('LOW', 'NORMAL', 'HIGH')"
        )
    op.create_index(
        "ix_background_jobs_queue",
        "background_jobs",
        ["status", "priority", "scheduled_at", "retry_at", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_background_jobs_queue", table_name="background_jobs")
    with op.batch_alter_table("background_jobs") as batch:
        batch.drop_constraint("valid_priority", type_="check")
        batch.drop_column("priority")
    op.create_index(
        "ix_background_jobs_queue",
        "background_jobs",
        ["status", "scheduled_at", "retry_at", "created_at"],
    )

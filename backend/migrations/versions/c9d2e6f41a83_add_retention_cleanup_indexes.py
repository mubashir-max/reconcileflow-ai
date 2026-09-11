"""add retention cleanup indexes

Revision ID: c9d2e6f41a83
Revises: a8c4d1e72f90
Create Date: 2026-09-11
"""

from typing import Sequence, Union

from alembic import op


revision: str = "c9d2e6f41a83"
down_revision: Union[str, Sequence[str], None] = "a8c4d1e72f90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_background_jobs_terminal_completed",
        "background_jobs",
        ["status", "completed_at"],
    )
    op.create_index(
        "ix_workers_status_stopped", "workers", ["status", "stopped_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_workers_status_stopped", table_name="workers")
    op.drop_index(
        "ix_background_jobs_terminal_completed", table_name="background_jobs"
    )

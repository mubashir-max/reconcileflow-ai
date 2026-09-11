"""add job execution deadlines

Revision ID: b7e3f9a21c64
Revises: c9d2e6f41a83
Create Date: 2026-09-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7e3f9a21c64"
down_revision: Union[str, Sequence[str], None] = "c9d2e6f41a83"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("background_jobs") as batch:
        batch.add_column(sa.Column(
            "timeout_seconds", sa.Integer(), nullable=False, server_default="900"
        ))
        batch.add_column(sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_check_constraint("valid_timeout_seconds", "timeout_seconds >= 30")


def downgrade() -> None:
    with op.batch_alter_table("background_jobs") as batch:
        batch.drop_constraint("valid_timeout_seconds", type_="check")
        batch.drop_column("deadline_at")
        batch.drop_column("timeout_seconds")

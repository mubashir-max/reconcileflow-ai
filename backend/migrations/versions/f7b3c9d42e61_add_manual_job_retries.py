"""add manual job retries

Revision ID: f7b3c9d42e61
Revises: e6f1c8b42a73
Create Date: 2026-09-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7b3c9d42e61"
down_revision: Union[str, Sequence[str], None] = "e6f1c8b42a73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("background_jobs") as batch_op:
        batch_op.add_column(
            sa.Column("total_attempt_count", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column("manual_retry_count", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column("last_manual_retry_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_check_constraint(
            "nonnegative_total_attempt_count", "total_attempt_count >= 0"
        )
        batch_op.create_check_constraint(
            "nonnegative_manual_retry_count", "manual_retry_count >= 0"
        )
    op.execute("UPDATE background_jobs SET total_attempt_count = attempt_count")


def downgrade() -> None:
    with op.batch_alter_table("background_jobs") as batch_op:
        batch_op.drop_constraint("nonnegative_manual_retry_count", type_="check")
        batch_op.drop_constraint("nonnegative_total_attempt_count", type_="check")
        batch_op.drop_column("last_manual_retry_at")
        batch_op.drop_column("manual_retry_count")
        batch_op.drop_column("total_attempt_count")

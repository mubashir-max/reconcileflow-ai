"""add login attempt protection

Revision ID: a4c8d2e71f50
Revises: f3a7b91c4d20
Create Date: 2026-09-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a4c8d2e71f50"
down_revision: Union[str, Sequence[str], None] = "f3a7b91c4d20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("failed_login_attempts", sa.Integer(), server_default="0", nullable=False))
        batch_op.add_column(sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_check_constraint("nonnegative_failed_login_attempts", "failed_login_attempts >= 0")


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("nonnegative_failed_login_attempts", type_="check")
        batch_op.drop_column("locked_until")
        batch_op.drop_column("failed_login_attempts")

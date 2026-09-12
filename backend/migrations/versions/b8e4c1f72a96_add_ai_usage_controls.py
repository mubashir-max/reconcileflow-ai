"""Add tenant-scoped AI usage reservations and limits.

Revision ID: b8e4c1f72a96
Revises: a6d3f8c21e49
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8e4c1f72a96"
down_revision: Union[str, Sequence[str], None] = "a6d3f8c21e49"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("organizations") as batch:
        batch.add_column(sa.Column("hosted_ai_enabled", sa.Boolean(), server_default=sa.false(), nullable=False))
        batch.add_column(sa.Column("ai_daily_request_limit", sa.Integer(), server_default="100", nullable=False))
        batch.add_column(sa.Column("ai_monthly_request_limit", sa.Integer(), server_default="1000", nullable=False))
        batch.add_column(sa.Column("ai_daily_token_limit", sa.BigInteger(), server_default="100000", nullable=False))
        batch.add_column(sa.Column("ai_monthly_token_limit", sa.BigInteger(), server_default="1000000", nullable=False))
        batch.create_check_constraint("nonnegative_ai_daily_requests", "ai_daily_request_limit >= 0")
        batch.create_check_constraint("nonnegative_ai_monthly_requests", "ai_monthly_request_limit >= 0")
        batch.create_check_constraint("nonnegative_ai_daily_tokens", "ai_daily_token_limit >= 0")
        batch.create_check_constraint("nonnegative_ai_monthly_tokens", "ai_monthly_token_limit >= 0")
    op.create_table(
        "ai_usage_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), server_default="RESERVED", nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("model_version", sa.String(150), nullable=False),
        sa.Column("reserved_requests", sa.Integer(), server_default="1", nullable=False),
        sa.Column("reserved_tokens", sa.BigInteger(), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True)),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('RESERVED', 'FINALIZED', 'RELEASED')", name="valid_status"),
        sa.CheckConstraint("reserved_requests = 1", name="single_reserved_request"),
        sa.CheckConstraint("reserved_tokens >= 0", name="nonnegative_reserved_tokens"),
        sa.CheckConstraint("input_tokens >= 0", name="nonnegative_input_tokens"),
        sa.CheckConstraint("output_tokens >= 0", name="nonnegative_output_tokens"),
        sa.CheckConstraint("candidate_count >= 0", name="nonnegative_candidate_count"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["run_id"], ["reconciliation_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_usage_organization_created", "ai_usage_records", ["organization_id", "created_at"])
    op.create_index("ix_ai_usage_active_reservations", "ai_usage_records", ["organization_id", "status", "expires_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_usage_active_reservations", table_name="ai_usage_records")
    op.drop_index("ix_ai_usage_organization_created", table_name="ai_usage_records")
    op.drop_table("ai_usage_records")
    with op.batch_alter_table("organizations") as batch:
        batch.drop_constraint("nonnegative_ai_monthly_tokens", type_="check")
        batch.drop_constraint("nonnegative_ai_daily_tokens", type_="check")
        batch.drop_constraint("nonnegative_ai_monthly_requests", type_="check")
        batch.drop_constraint("nonnegative_ai_daily_requests", type_="check")
        batch.drop_column("ai_monthly_token_limit")
        batch.drop_column("ai_daily_token_limit")
        batch.drop_column("ai_monthly_request_limit")
        batch.drop_column("ai_daily_request_limit")
        batch.drop_column("hosted_ai_enabled")

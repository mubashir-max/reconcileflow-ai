"""Add privacy-safe AI inference operational events.

Revision ID: c7f2a9e41d63
Revises: b8e4c1f72a96
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "c7f2a9e41d63"
down_revision: Union[str, Sequence[str], None] = "b8e4c1f72a96"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        "ai_inference_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("outcome", sa.String(24), server_default="REQUESTED", nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("model_version", sa.String(150), nullable=False),
        sa.Column("prompt_version", sa.String(100), nullable=False),
        sa.Column("inference_config_version", sa.String(100), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("suggestion_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("error_code", sa.String(50)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("outcome IN ('REQUESTED','SUCCEEDED','FAILED','TIMED_OUT','DISABLED','QUOTA_REJECTED')", name="valid_outcome"),
        sa.CheckConstraint("candidate_count >= 0", name="nonnegative_candidate_count"),
        sa.CheckConstraint("suggestion_count >= 0", name="nonnegative_suggestion_count"),
        sa.CheckConstraint("input_tokens >= 0", name="nonnegative_input_tokens"),
        sa.CheckConstraint("output_tokens >= 0", name="nonnegative_output_tokens"),
        sa.CheckConstraint("duration_ms IS NULL OR duration_ms >= 0", name="nonnegative_duration_ms"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["run_id"], ["reconciliation_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_inference_events_org_created", "ai_inference_events", ["organization_id", "created_at"])
    op.create_index("ix_ai_inference_events_org_outcome", "ai_inference_events", ["organization_id", "outcome", "created_at"])

def downgrade() -> None:
    op.drop_index("ix_ai_inference_events_org_outcome", table_name="ai_inference_events")
    op.drop_index("ix_ai_inference_events_org_created", table_name="ai_inference_events")
    op.drop_table("ai_inference_events")

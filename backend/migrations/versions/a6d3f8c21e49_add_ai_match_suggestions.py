"""Add tenant-scoped advisory AI match suggestions.

Revision ID: a6d3f8c21e49
Revises: f2c6a9d81b43
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a6d3f8c21e49"
down_revision: Union[str, Sequence[str], None] = "f2c6a9d81b43"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_match_suggestions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="PENDING", nullable=False),
        sa.Column("confidence_score", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("candidate_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("bank_record_ids", sa.JSON(), nullable=False),
        sa.Column("erp_invoice_ids", sa.JSON(), nullable=False),
        sa.Column("gateway_record_ids", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.JSON(), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model_version", sa.String(length=150), nullable=False),
        sa.Column("prompt_template_version", sa.String(length=100), nullable=False),
        sa.Column("inference_config_version", sa.String(length=100), nullable=False),
        sa.Column("reviewed_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('PENDING', 'ACCEPTED', 'REJECTED', 'EXPIRED')", name="valid_status"),
        sa.CheckConstraint("confidence_score >= 0 AND confidence_score <= 1", name="valid_confidence"),
        sa.CheckConstraint("length(candidate_fingerprint) = 64", name="valid_candidate_fingerprint"),
        sa.CheckConstraint("length(trim(provider)) > 0", name="nonblank_provider"),
        sa.CheckConstraint("length(trim(model_version)) > 0", name="nonblank_model_version"),
        sa.CheckConstraint("length(trim(prompt_template_version)) > 0", name="nonblank_prompt_version"),
        sa.CheckConstraint("length(trim(inference_config_version)) > 0", name="nonblank_config_version"),
        sa.CheckConstraint("expires_at IS NULL OR expires_at > created_at", name="valid_expiration"),
        sa.CheckConstraint(
            "(reviewed_by_user_id IS NULL AND reviewed_at IS NULL) OR "
            "(reviewed_by_user_id IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="consistent_review_metadata",
        ),
        sa.CheckConstraint(
            "status NOT IN ('ACCEPTED', 'REJECTED') OR reviewed_by_user_id IS NOT NULL",
            name="resolved_suggestion_has_reviewer",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["run_id"], ["reconciliation_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reviewed_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "run_id", "candidate_fingerprint", name="uq_ai_suggestion_candidate"),
    )
    op.create_index(
        "ix_ai_match_suggestions_organization_status_created",
        "ai_match_suggestions", ["organization_id", "status", "created_at"], unique=False,
    )
    op.create_index(
        "ix_ai_match_suggestions_run_confidence",
        "ai_match_suggestions", ["run_id", "confidence_score"], unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_ai_match_suggestions_run_confidence", table_name="ai_match_suggestions")
    op.drop_index("ix_ai_match_suggestions_organization_status_created", table_name="ai_match_suggestions")
    op.drop_table("ai_match_suggestions")

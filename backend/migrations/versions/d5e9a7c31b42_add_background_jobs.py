"""add background jobs

Revision ID: d5e9a7c31b42
Revises: a4c8d2e71f50
Create Date: 2026-09-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5e9a7c31b42"
down_revision: Union[str, Sequence[str], None] = "a4c8d2e71f50"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "background_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="QUEUED", nullable=False),
        sa.Column("progress_percentage", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status_message", sa.String(length=500), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCEL_REQUESTED', 'CANCELLED')",
            name="valid_status",
        ),
        sa.CheckConstraint(
            "progress_percentage >= 0 AND progress_percentage <= 100",
            name="valid_progress_percentage",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="nonnegative_attempt_count"),
        sa.CheckConstraint("max_attempts >= 1", name="positive_max_attempts"),
        sa.CheckConstraint("attempt_count <= max_attempts", name="attempts_within_limit"),
        sa.CheckConstraint(
            "completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at",
            name="valid_execution_time_range",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["run_id"], ["reconciliation_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_background_jobs_run_id"),
    )
    op.create_index(
        "ix_background_jobs_queue",
        "background_jobs",
        ["status", "scheduled_at", "retry_at", "created_at"],
    )
    op.create_index(
        "ix_background_jobs_organization_status",
        "background_jobs",
        ["organization_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_background_jobs_organization_status", table_name="background_jobs")
    op.drop_index("ix_background_jobs_queue", table_name="background_jobs")
    op.drop_table("background_jobs")

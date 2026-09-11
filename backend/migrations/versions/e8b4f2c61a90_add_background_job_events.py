"""add background job lifecycle events

Revision ID: e8b4f2c61a90
Revises: d4a8c2f71e95
Create Date: 2026-09-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e8b4f2c61a90"
down_revision: Union[str, Sequence[str], None] = "d4a8c2f71e95"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "background_job_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('JOB_QUEUED', 'JOB_CLAIMED', 'JOB_PROGRESS_UPDATED', "
            "'JOB_RETRY_SCHEDULED', 'JOB_MANUAL_RETRY_REQUESTED', "
            "'JOB_CANCELLATION_REQUESTED', 'JOB_CANCELLED', 'JOB_TIMED_OUT', "
            "'JOB_SUCCEEDED', 'JOB_FAILED', 'JOB_RECOVERED')",
            name="ck_background_job_events_valid_event_type",
        ),
        sa.CheckConstraint(
            "sequence_number >= 1",
            name="ck_background_job_events_positive_sequence",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["background_jobs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            "sequence_number",
            name="uq_background_job_events_job_sequence",
        ),
    )
    op.create_index(
        "ix_background_job_events_organization_job",
        "background_job_events",
        ["organization_id", "job_id", "sequence_number"],
    )
    op.create_index(
        "ix_background_job_events_job_occurred_at",
        "background_job_events",
        ["job_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_background_job_events_job_occurred_at",
        table_name="background_job_events",
    )
    op.drop_index(
        "ix_background_job_events_organization_job",
        table_name="background_job_events",
    )
    op.drop_table("background_job_events")

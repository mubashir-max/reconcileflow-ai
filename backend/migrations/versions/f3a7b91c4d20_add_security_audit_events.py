"""add security audit events

Revision ID: f3a7b91c4d20
Revises: b6d7e3f2a841
Create Date: 2026-09-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3a7b91c4d20"
down_revision: Union[str, Sequence[str], None] = "b6d7e3f2a841"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "security_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name=op.f("fk_security_audit_events_actor_user_id_users"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name=op.f("fk_security_audit_events_organization_id_organizations"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_security_audit_events")),
    )
    op.create_index("ix_security_audit_events_actor_occurred_at", "security_audit_events", ["actor_user_id", "occurred_at"], unique=False)
    op.create_index("ix_security_audit_events_organization_occurred_at", "security_audit_events", ["organization_id", "occurred_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_security_audit_events_organization_occurred_at", table_name="security_audit_events")
    op.drop_index("ix_security_audit_events_actor_occurred_at", table_name="security_audit_events")
    op.drop_table("security_audit_events")

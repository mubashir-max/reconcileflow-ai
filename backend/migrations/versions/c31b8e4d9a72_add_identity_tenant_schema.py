"""add identity and tenant schema

Revision ID: c31b8e4d9a72
Revises: 7da9a8e2e1ef
Create Date: 2026-09-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c31b8e4d9a72"
down_revision: Union[str, Sequence[str], None] = "7da9a8e2e1ef"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(trim(name)) > 0", name=op.f("ck_organizations_nonblank_name")),
        sa.CheckConstraint("length(trim(slug)) > 0", name=op.f("ck_organizations_nonblank_slug")),
        sa.CheckConstraint("slug = lower(slug) AND slug NOT LIKE '% %'", name=op.f("ck_organizations_normalized_slug")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
        sa.UniqueConstraint("slug", name=op.f("uq_organizations_slug")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=150), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(trim(email)) > 3", name=op.f("ck_users_nonblank_email")),
        sa.CheckConstraint("email = lower(trim(email))", name=op.f("ck_users_normalized_email")),
        sa.CheckConstraint("email LIKE '_%@_%'", name=op.f("ck_users_email_has_at_sign")),
        sa.CheckConstraint("length(trim(password_hash)) > 0", name=op.f("ck_users_nonblank_password_hash")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "organization_memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("role IN ('OWNER', 'ADMIN', 'ANALYST', 'VIEWER')", name=op.f("ck_organization_memberships_valid_role")),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], name=op.f("fk_organization_memberships_organization_id_organizations"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_organization_memberships_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_memberships")),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_organization_memberships_organization_user"),
    )
    op.create_index("ix_organization_memberships_organization_role", "organization_memberships", ["organization_id", "role"], unique=False)
    op.create_index("ix_organization_memberships_user_active", "organization_memberships", ["user_id", "is_active"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_organization_memberships_user_active", table_name="organization_memberships")
    op.drop_index("ix_organization_memberships_organization_role", table_name="organization_memberships")
    op.drop_table("organization_memberships")
    op.drop_table("users")
    op.drop_table("organizations")

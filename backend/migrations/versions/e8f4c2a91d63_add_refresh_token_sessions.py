"""add refresh token sessions

Revision ID: e8f4c2a91d63
Revises: c31b8e4d9a72
Create Date: 2026-09-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e8f4c2a91d63"
down_revision: Union[str, Sequence[str], None] = "c31b8e4d9a72"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(token_hash) = 64", name=op.f("ck_refresh_tokens_valid_token_hash")),
        sa.CheckConstraint("expires_at > created_at", name=op.f("ck_refresh_tokens_valid_expiration")),
        sa.ForeignKeyConstraint(["replaced_by_id"], ["refresh_tokens.id"], name=op.f("fk_refresh_tokens_replaced_by_id_refresh_tokens"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_refresh_tokens_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index("ix_refresh_tokens_family_revoked_at", "refresh_tokens", ["family_id", "revoked_at"], unique=False)
    op.create_index("ix_refresh_tokens_user_expires_at", "refresh_tokens", ["user_id", "expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_user_expires_at", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_family_revoked_at", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")

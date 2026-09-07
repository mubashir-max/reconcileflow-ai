"""scope reconciliation runs to organizations

Revision ID: b6d7e3f2a841
Revises: e8f4c2a91d63
Create Date: 2026-09-07
"""

import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b6d7e3f2a841"
down_revision: Union[str, Sequence[str], None] = "e8f4c2a91d63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEGACY_ORGANIZATION_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def upgrade() -> None:
    organizations = sa.table(
        "organizations",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("slug", sa.String()),
    )
    op.bulk_insert(
        organizations,
        [{"id": LEGACY_ORGANIZATION_ID, "name": "Legacy Workspace", "slug": "legacy-workspace"}],
    )
    with op.batch_alter_table("reconciliation_runs") as batch:
        batch.add_column(sa.Column("organization_id", sa.Uuid(), nullable=True))
    op.execute(
        sa.update(sa.table("reconciliation_runs", sa.column("organization_id", sa.Uuid())))
        .values(organization_id=LEGACY_ORGANIZATION_ID)
    )
    with op.batch_alter_table("reconciliation_runs") as batch:
        batch.alter_column("organization_id", existing_type=sa.Uuid(), nullable=False)
        batch.create_foreign_key(
            "fk_reconciliation_runs_organization_id_organizations",
            "organizations",
            ["organization_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_index("ix_reconciliation_runs_organization_id", ["organization_id"])


def downgrade() -> None:
    with op.batch_alter_table("reconciliation_runs") as batch:
        batch.drop_index("ix_reconciliation_runs_organization_id")
        batch.drop_constraint("fk_reconciliation_runs_organization_id_organizations", type_="foreignkey")
        batch.drop_column("organization_id")
    op.execute(
        sa.delete(sa.table("organizations", sa.column("id", sa.Uuid())))
        .where(sa.column("id", sa.Uuid()) == LEGACY_ORGANIZATION_ID)
    )

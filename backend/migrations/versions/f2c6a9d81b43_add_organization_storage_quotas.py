"""Add organization storage quotas and usage counters.

Revision ID: f2c6a9d81b43
Revises: e8b4f2c61a90
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2c6a9d81b43"
down_revision: Union[str, Sequence[str], None] = "e8b4f2c61a90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("organizations") as batch:
        batch.add_column(sa.Column("storage_quota_bytes", sa.BigInteger(), nullable=True))
        batch.add_column(sa.Column("storage_used_bytes", sa.BigInteger(), server_default="0", nullable=False))
        batch.create_check_constraint(
            "nonnegative_storage_quota", "storage_quota_bytes IS NULL OR storage_quota_bytes >= 0"
        )
        batch.create_check_constraint("nonnegative_storage_usage", "storage_used_bytes >= 0")
    op.execute(
        "UPDATE organizations SET storage_quota_bytes = 10737418240, "
        "storage_used_bytes = COALESCE((SELECT SUM(source_files.size_bytes) "
        "FROM source_files JOIN reconciliation_runs ON reconciliation_runs.id = source_files.run_id "
        "WHERE reconciliation_runs.organization_id = organizations.id), 0)"
    )


def downgrade() -> None:
    with op.batch_alter_table("organizations") as batch:
        batch.drop_constraint("nonnegative_storage_usage", type_="check")
        batch.drop_constraint("nonnegative_storage_quota", type_="check")
        batch.drop_column("storage_used_bytes")
        batch.drop_column("storage_quota_bytes")

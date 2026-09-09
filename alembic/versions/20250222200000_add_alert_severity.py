"""Add severity column to alerts table.

Revision ID: 20250222200000
Revises: 20250222100000
Create Date: 2025-02-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20250222200000"
down_revision: Union[str, None] = "20250222100000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("alerts", sa.Column("severity", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("alerts", "severity")

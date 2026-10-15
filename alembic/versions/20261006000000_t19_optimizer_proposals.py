"""T19: optimizer_proposals (operator proposes, a different admin approves or rejects).

Revision ID: 20261006000000
Revises: 20261005000000
Create Date: 2026-10-06

Additive only: one new table. Every row carries ``origin`` (always ``simulated``: the prediction is a twin run).
Downgrade drops the table.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261006000000"
down_revision: Union[str, None] = "20261005000000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "optimizer_proposals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("proposer", sa.String(64), nullable=False),
        sa.Column("source", sa.String(48), nullable=False),
        sa.Column("chilled_water_temp_c", sa.Float(), nullable=False),
        sa.Column("cooling_mode", sa.String(16), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("predicted", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("decided_by", sa.String(64), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
    )
    op.create_index("ix_optimizer_proposals_status", "optimizer_proposals", ["status"])


def downgrade() -> None:
    op.drop_index("ix_optimizer_proposals_status", table_name="optimizer_proposals")
    op.drop_table("optimizer_proposals")

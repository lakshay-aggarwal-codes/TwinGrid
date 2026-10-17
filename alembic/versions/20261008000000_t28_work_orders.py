"""T28: maintenance work orders (work_orders + work_order_events).

Revision ID: 20261008000000
Revises: 20261007000000
Create Date: 2026-10-08

Additive only: two new tables, no change to an existing one. Every work order carries ``origin`` (``simulated`` when it
was raised from an alert or a health row, else ``manual``). Downgrade drops both tables.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261008000000"
down_revision: Union[str, None] = "20261007000000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "work_orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("assignee", sa.String(64), nullable=True),
        sa.Column("asset_external_id", sa.String(128), nullable=True),
        sa.Column("source_kind", sa.String(16), nullable=False),
        sa.Column("source_ref", sa.String(160), nullable=True),
        sa.Column("origin", sa.String(16), nullable=False),
    )
    op.create_index("ix_work_orders_status_created", "work_orders", ["status", "created_at", "id"])
    op.create_index("ix_work_orders_asset_external_id", "work_orders", ["asset_external_id"])
    op.create_table(
        "work_order_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("work_order_id", sa.Integer(), sa.ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("from_status", sa.String(16), nullable=True),
        sa.Column("to_status", sa.String(16), nullable=True),
        sa.Column("assignee", sa.String(64), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_index("ix_work_order_events_work_order_id", "work_order_events", ["work_order_id"])


def downgrade() -> None:
    op.drop_index("ix_work_order_events_work_order_id", table_name="work_order_events")
    op.drop_table("work_order_events")
    op.drop_index("ix_work_orders_asset_external_id", table_name="work_orders")
    op.drop_index("ix_work_orders_status_created", table_name="work_orders")
    op.drop_table("work_orders")

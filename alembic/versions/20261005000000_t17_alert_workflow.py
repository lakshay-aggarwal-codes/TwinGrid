"""T17: alert incident workflow (status, assignee, resolution columns + alert_events timeline).

Revision ID: 20261005000000
Revises: 20261004000000
Create Date: 2026-10-05

Additive only: four nullable columns on ``alerts`` (existing rows keep NULL and read as open/acknowledged from the
legacy ``acknowledged`` flag) and one new table ``alert_events``. Downgrade drops the table and the columns.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261005000000"
down_revision: Union[str, None] = "20261004000000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Plain ADD COLUMN (nullable): same style as M2 (20261001000001), no table rebuild on SQLite.
    op.add_column("alerts", sa.Column("status", sa.String(16), nullable=True))
    op.add_column("alerts", sa.Column("assignee", sa.String(64), nullable=True))
    op.add_column("alerts", sa.Column("resolved_by", sa.String(64), nullable=True))
    op.add_column("alerts", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "alert_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("alert_id", sa.Integer(), sa.ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("from_status", sa.String(16), nullable=True),
        sa.Column("to_status", sa.String(16), nullable=True),
        sa.Column("assignee", sa.String(64), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
    )
    op.create_index("ix_alert_events_alert_id", "alert_events", ["alert_id"])


def downgrade() -> None:
    op.drop_index("ix_alert_events_alert_id", table_name="alert_events")
    op.drop_table("alert_events")
    op.drop_column("alerts", "resolved_at")
    op.drop_column("alerts", "resolved_by")
    op.drop_column("alerts", "assignee")
    op.drop_column("alerts", "status")

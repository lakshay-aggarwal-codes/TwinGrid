"""T24: two composite indexes for the newest-first list queries.

Revision ID: 20261007000000
Revises: 20261006000000
Create Date: 2026-10-07

Additive only (indexes, no table or column change). ``alerts`` is read ``ORDER BY created_at DESC, id DESC`` by the
inbox and the recent-alerts list, and ``optimizer_proposals`` by ``status`` then the same order; neither had an
index that serves the ordering. Downgrade drops the two indexes.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261007000000"
down_revision: Union[str, None] = "20261006000000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_alerts_created_at_id", "alerts", ["created_at", "id"])
    op.create_index("ix_optimizer_proposals_status_created", "optimizer_proposals", ["status", "created_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_optimizer_proposals_status_created", table_name="optimizer_proposals")
    op.drop_index("ix_alerts_created_at_id", table_name="alerts")

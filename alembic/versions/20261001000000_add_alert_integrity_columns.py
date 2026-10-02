"""M2 (T3): alert identity and provenance columns.

Adds alerts.dedupe_key (UNIQUE, nullable), alerts.model_version, alerts.origin.
Existing alerts keep NULL in all three ("unlabelled legacy"); a unique index on a
nullable column allows any number of NULLs. Old application code ignores the columns.

NOTE: this revision currently follows 20250223000000. When M1 (T1b) is added to the
repository, re-point ``down_revision`` at M1's revision id so there is a single head.

Revision ID: 20261001000000
Revises: 20250223000000
Create Date: 2026-10-01

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261001000000"
down_revision: Union[str, None] = "20250223000000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("alerts", sa.Column("dedupe_key", sa.String(128), nullable=True))
    op.add_column("alerts", sa.Column("model_version", sa.String(64), nullable=True))
    op.add_column("alerts", sa.Column("origin", sa.String(16), nullable=True))
    op.create_index("ux_alerts_dedupe_key", "alerts", ["dedupe_key"], unique=True)


def downgrade() -> None:
    op.drop_index("ux_alerts_dedupe_key", table_name="alerts")
    op.drop_column("alerts", "origin")
    op.drop_column("alerts", "model_version")
    op.drop_column("alerts", "dedupe_key")

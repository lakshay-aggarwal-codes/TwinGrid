"""M2 (T3): alert identity and provenance columns.

Adds alerts.dedupe_key (UNIQUE, nullable), alerts.model_version, alerts.origin.
Existing alerts keep NULL in all three ("unlabelled legacy"); a unique index on a
nullable column allows any number of NULLs. Old application code ignores the columns.

NOTE (T10): this revision originally shared id 20261001000000 with M1 and revised
20250223000000, which gave two heads and a duplicate id. It now has its own id and
follows M1 (20261001000000): 20250223000000 -> M1 -> M2 -> M3. The migration body is
unchanged. If any shared database was already stamped with the old M2 identity, do not
rely on this renumbering -- see reports/postT9/T10_evidence.md.

Revision ID: 20261001000001
Revises: 20261001000000
Create Date: 2026-10-01

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261001000001"
down_revision: Union[str, None] = "20261001000000"
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

"""M1: minimal provenance columns (T1b).

Adds, additively:
  sensor_readings.origin            varchar(16) NOT NULL server_default 'simulated'
  sensor_readings.physics_version   varchar(32) NULL
  simulation_runs.physics_version   varchar(32) NULL
  optimization_results.physics_version varchar(32) NULL
  optimization_results.model_version   varchar(64) NULL
  index ix_sensor_readings_timestamp on sensor_readings(timestamp)

Backfill: every row written before this migration came from a simulator path,
so origin is 'simulated' (via the column default) and physics_version is
'legacy-0'. model_version stays NULL (unknown). The literals are frozen here on
purpose -- do not import them from application code.

Rollback: downgrade drops the index and the columns; only labels are lost and
they are derivable from the constants above.

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

_LEGACY_PHYSICS = "legacy-0"


def upgrade() -> None:
    # NOT NULL + constant server_default: existing rows get 'simulated'.
    op.add_column(
        "sensor_readings",
        sa.Column("origin", sa.String(16), nullable=False, server_default=sa.text("'simulated'")),
    )
    op.add_column("sensor_readings", sa.Column("physics_version", sa.String(32), nullable=True))
    op.add_column("simulation_runs", sa.Column("physics_version", sa.String(32), nullable=True))
    op.add_column("optimization_results", sa.Column("physics_version", sa.String(32), nullable=True))
    op.add_column("optimization_results", sa.Column("model_version", sa.String(64), nullable=True))

    for table in ("sensor_readings", "simulation_runs", "optimization_results"):
        op.execute(
            sa.text(f"UPDATE {table} SET physics_version = :v WHERE physics_version IS NULL").bindparams(
                v=_LEGACY_PHYSICS
            )
        )

    op.create_index(op.f("ix_sensor_readings_timestamp"), "sensor_readings", ["timestamp"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_sensor_readings_timestamp"), table_name="sensor_readings")
    with op.batch_alter_table("optimization_results") as batch:
        batch.drop_column("model_version")
        batch.drop_column("physics_version")
    with op.batch_alter_table("simulation_runs") as batch:
        batch.drop_column("physics_version")
    with op.batch_alter_table("sensor_readings") as batch:
        batch.drop_column("physics_version")
        batch.drop_column("origin")

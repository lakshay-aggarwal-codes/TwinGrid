"""Align the database schema with the ORM models.

Revision ID: 20250222300000
Revises: 20250222200000
Create Date: 2025-02-22 23:00:00

Why: the earlier migrations created `created_at` (5 tables) and
`sensor_readings.anomaly` as NULLable, while models/db_models.py declares them
non-Optional (NOT NULL) -- `alembic check` reported drift.

Decision on foreign keys: the migrations already use ON DELETE SET NULL for
sensor_readings.simulation_run_id / optimization_result_id and
alerts.sensor_reading_id. That is the schema existing deployments have, so the
ORM was aligned to it (ForeignKey(..., ondelete="SET NULL")) rather than
rewriting live constraints. No FK change is needed here.
"""

import sqlalchemy as sa
from alembic import op

revision = "20250222300000"
down_revision = "20250222200000"
branch_labels = None
depends_on = None

_CREATED_AT_TABLES = ("users", "simulation_runs", "optimization_results", "sensor_readings", "alerts")


# T10 portability note: this revision used ``now()`` and bare ``ALTER COLUMN``, which
# SQLite cannot run, so a full ``upgrade head`` from base was impossible on SQLite.
# CURRENT_TIMESTAMP is the SQL-standard spelling of the same value and
# ``batch_alter_table`` emits the identical plain ``ALTER TABLE ... ALTER COLUMN`` on
# PostgreSQL (table rebuild only on SQLite). Resulting PostgreSQL schema is unchanged.


def upgrade() -> None:
    # Backfill first: SET NOT NULL fails if any NULL rows exist.
    for table in _CREATED_AT_TABLES:
        op.execute(sa.text(f"UPDATE {table} SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"))
    op.execute(sa.text("UPDATE sensor_readings SET anomaly = 0 WHERE anomaly IS NULL"))

    for table in _CREATED_AT_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.alter_column("created_at", existing_type=sa.DateTime(timezone=True), nullable=False)
    with op.batch_alter_table("sensor_readings") as batch:
        batch.alter_column("anomaly", existing_type=sa.Integer(), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("sensor_readings") as batch:
        batch.alter_column("anomaly", existing_type=sa.Integer(), nullable=True)
    for table in reversed(_CREATED_AT_TABLES):
        with op.batch_alter_table(table) as batch:
            batch.alter_column("created_at", existing_type=sa.DateTime(timezone=True), nullable=True)

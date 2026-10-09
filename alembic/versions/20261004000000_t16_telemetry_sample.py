"""T16: telemetry_sample table + sensor.source_tz.

Revision ID: 20261004000000
Revises: 20261003000000
Create Date: 2026-10-04

Additive. Adds ``sensor.source_tz`` (NOT NULL, server default 'UTC') and creates ``telemetry_sample``
(roadmap §9.1). ``sensor_readings`` is untouched. Downgrade drops the table and the added column.

NOTE (chain, T10-fix): T16 originally shared revision id 20261003000000 with T15
(audit_log_completion), causing a duplicate-head error. It is now renumbered
20261004000000 and chains onto T15 (20261003000000). The upgrade/downgrade bodies
are unchanged.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261004000000"
down_revision: Union[str, None] = "20261003000000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("sensor") as batch:
        batch.add_column(sa.Column("source_tz", sa.String(64), nullable=False, server_default="UTC"))

    op.create_table(
        "telemetry_sample",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True, autoincrement=True),
        sa.Column("sensor_id", sa.Integer(), sa.ForeignKey("sensor.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("stream_id", sa.String(64), nullable=False),
        sa.Column("ts_event", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ts_ingest", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("quality", sa.String(8), nullable=False),
        sa.Column("invalid_reason", sa.String(16), nullable=True),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("sim_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("batch_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.UniqueConstraint("sensor_id", "stream_id", "ts_event", name="uq_telemetry_sensor_stream_event"),
        sa.CheckConstraint("origin IN ('simulated', 'measured', 'replay')", name="ck_telemetry_origin"),
        sa.CheckConstraint(
            "(origin = 'simulated') = (sim_time IS NOT NULL)", name="ck_telemetry_sim_time_iff_simulated"
        ),
        sa.CheckConstraint("quality IN ('ok', 'invalid')", name="ck_telemetry_quality"),
        sa.CheckConstraint(
            "(quality = 'ok' AND invalid_reason IS NULL) OR "
            "(quality = 'invalid' AND invalid_reason IS NOT NULL AND invalid_reason IN ('range', 'future'))",
            name="ck_telemetry_invalid_reason",
        ),
    )


def downgrade() -> None:
    op.drop_table("telemetry_sample")
    with op.batch_alter_table("sensor") as batch:
        batch.drop_column("source_tz")

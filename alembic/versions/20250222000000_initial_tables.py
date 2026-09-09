"""Initial tables: sensor_readings, simulation_runs, optimization_results, alerts.

Revision ID: 20250222000000
Revises:
Create Date: 2025-02-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20250222000000"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "simulation_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hours", sa.Integer(), nullable=False),
        sa.Column("utilisation", sa.Float(), nullable=False),
        sa.Column("stress", sa.Float(), nullable=False),
        sa.Column("result_snapshot", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "optimization_results",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("alpha", sa.Float(), nullable=False),
        sa.Column("beta", sa.Float(), nullable=False),
        sa.Column("gamma", sa.Float(), nullable=False),
        sa.Column("water_stress", sa.Float(), nullable=False),
        sa.Column("hours", sa.Integer(), nullable=False),
        sa.Column("mean_pue", sa.Float(), nullable=False),
        sa.Column("mean_wue", sa.Float(), nullable=False),
        sa.Column("mean_cooling_power_kw", sa.Float(), nullable=False),
        sa.Column("total_water_consumed_L", sa.Float(), nullable=False),
        sa.Column("total_reward", sa.Float(), nullable=False),
        sa.Column("safety_violations", sa.Integer(), nullable=False),
        sa.Column("results_json", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "sensor_readings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("server_utilisation", sa.Float(), nullable=False),
        sa.Column("outside_temp_C", sa.Float(), nullable=False),
        sa.Column("server_inlet_temp_C", sa.Float(), nullable=False),
        sa.Column("server_outlet_temp_C", sa.Float(), nullable=False),
        sa.Column("it_power_kw", sa.Float(), nullable=False),
        sa.Column("cooling_power_kw", sa.Float(), nullable=False),
        sa.Column("total_power_kw", sa.Float(), nullable=False),
        sa.Column("pue", sa.Float(), nullable=False),
        sa.Column("water_flow_lpm", sa.Float(), nullable=False),
        sa.Column("water_consumed_L", sa.Float(), nullable=False),
        sa.Column("wue", sa.Float(), nullable=False),
        sa.Column("humidity_pct", sa.Float(), nullable=False),
        sa.Column("water_pressure_bar", sa.Float(), nullable=False),
        sa.Column("cooling_mode", sa.String(32), nullable=False),
        sa.Column("anomaly", sa.Integer(), nullable=True),
        sa.Column("simulation_run_id", sa.Integer(), nullable=True),
        sa.Column("optimization_result_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["optimization_result_id"], ["optimization_results.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["simulation_run_id"], ["simulation_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_sensor_readings_optimization_result_id"), "sensor_readings", ["optimization_result_id"], unique=False)
    op.create_index(op.f("ix_sensor_readings_simulation_run_id"), "sensor_readings", ["simulation_run_id"], unique=False)
    op.create_index(op.f("ix_sensor_readings_source"), "sensor_readings", ["source"], unique=False)
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("alert", sa.Boolean(), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("sensor_reading_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["sensor_reading_id"], ["sensor_readings.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("alerts")
    op.drop_index(op.f("ix_sensor_readings_source"), table_name="sensor_readings")
    op.drop_index(op.f("ix_sensor_readings_simulation_run_id"), table_name="sensor_readings")
    op.drop_index(op.f("ix_sensor_readings_optimization_result_id"), table_name="sensor_readings")
    op.drop_table("sensor_readings")
    op.drop_table("optimization_results")
    op.drop_table("simulation_runs")

"""T9 / M3: facility, asset, asset_edge, asset_pose, sensor + facility_id ownership refs.

Revision ID: 20261002000000
Revises: 20250223000000
Create Date: 2026-10-02

Additive only. Creates five tables, adds a NULLABLE ``facility_id`` FK to
``sensor_readings``, ``alerts`` and ``simulation_runs``, inserts ONE default
facility row, and backfills the three new columns to it.

No assets, poses or edges are created here -- the 36-rack layout is seeded by
``scripts/seed_facility.py`` only after the owner signs off the scene-unit ->
metre factor (roadmap section 25, decision 5).

NOTE (chain): M1 (T1b) and M2 (T3) are not present in this snapshot, so this
revision chains onto the current head. When M1/M2 land, re-point
``down_revision`` (or add a merge revision); M3 touches none of their columns.

Partial unique indexes use both ``postgresql_where`` and ``sqlite_where`` so the
same constraints hold on production (PostgreSQL) and in the SQLite test engine.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261002000000"
down_revision: Union[str, None] = "20250223000000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_FACILITY_NAME = "Default Facility"

FRAME_NOTE = (
    "Unit: metre. Right-handed frame, Y up. +X runs along rack rows, +Z runs across rows. "
    "Origin: floor level; x=0 at the -X edge of the first rack of zone-1; z=0 on the centreline "
    "between row-1 (z<0) and row-2 (z>0). Pose (x,y,z) is the centre of the asset's bounding box "
    "(zones: plan-view centre at floor level, y=0). rotation_deg is about +Y, right-hand rule, "
    "0 = default orientation. No geographic (compass) orientation is asserted. "
    "Scene-unit -> metre factor: PENDING OWNER SIGN-OFF (written by scripts/seed_facility.py --apply)."
)

_OWNED_TABLES = ("sensor_readings", "alerts", "simulation_runs")


def upgrade() -> None:
    op.create_table(
        "facility",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("frame_unit", sa.String(8), server_default="m", nullable=False),
        sa.Column("frame_note", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
        sa.CheckConstraint("frame_unit = 'm'", name="ck_facility_frame_unit_metre"),
    )

    op.create_table(
        "asset",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("facility_id", sa.Integer(), nullable=False),
        sa.Column("asset_type", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["facility_id"], ["facility.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("facility_id", "external_id", name="uq_asset_facility_external_id"),
    )
    op.create_index("ix_asset_facility_type", "asset", ["facility_id", "asset_type"])

    op.create_table(
        "asset_edge",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("parent_asset_id", sa.Integer(), nullable=False),
        sa.Column("child_asset_id", sa.Integer(), nullable=False),
        sa.Column("relation", sa.String(16), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["parent_asset_id"], ["asset.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["child_asset_id"], ["asset.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_asset_edge_interval"),
        sa.CheckConstraint("parent_asset_id <> child_asset_id", name="ck_asset_edge_no_self"),
    )
    op.create_index(
        "uq_asset_edge_open_located_in",
        "asset_edge",
        ["child_asset_id"],
        unique=True,
        postgresql_where=sa.text("relation = 'located_in' AND valid_to IS NULL"),
        sqlite_where=sa.text("relation = 'located_in' AND valid_to IS NULL"),
    )
    op.create_index(
        "uq_asset_edge_open_triple",
        "asset_edge",
        ["child_asset_id", "parent_asset_id", "relation"],
        unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
        sqlite_where=sa.text("valid_to IS NULL"),
    )
    op.create_index("ix_asset_edge_child_rel_from", "asset_edge", ["child_asset_id", "relation", "valid_from"])
    op.create_index("ix_asset_edge_parent", "asset_edge", ["parent_asset_id"])

    op.create_table(
        "asset_pose",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("x", sa.Float(), nullable=False),
        sa.Column("y", sa.Float(), nullable=False),
        sa.Column("z", sa.Float(), nullable=False),
        sa.Column("rotation_deg", sa.Float(), server_default="0", nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", "valid_from", name="uq_asset_pose_asset_from"),
        sa.CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_asset_pose_interval"),
    )
    op.create_index(
        "uq_asset_pose_open",
        "asset_pose",
        ["asset_id"],
        unique=True,
        postgresql_where=sa.text("valid_to IS NULL"),
        sqlite_where=sa.text("valid_to IS NULL"),
    )

    op.create_table(
        "sensor",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("asset_id", sa.Integer(), nullable=False),
        sa.Column("measurand", sa.String(64), nullable=False),
        sa.Column("unit", sa.String(16), nullable=False),
        sa.Column("sampling_interval_s", sa.Float(), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("min_valid", sa.Float(), nullable=True),
        sa.Column("max_valid", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id"),
        sa.CheckConstraint("sampling_interval_s > 0", name="ck_sensor_sampling_positive"),
        sa.CheckConstraint(
            "min_valid IS NULL OR max_valid IS NULL OR min_valid <= max_valid",
            name="ck_sensor_valid_range",
        ),
    )
    op.create_index("ix_sensor_asset_id", "sensor", ["asset_id"])

    # Default facility (the only data this migration inserts).
    facility = sa.table(
        "facility",
        sa.column("name", sa.String),
        sa.column("frame_unit", sa.String),
        sa.column("frame_note", sa.Text),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    from datetime import datetime, timezone

    op.bulk_insert(
        facility,
        [
            {
                "name": DEFAULT_FACILITY_NAME,
                "frame_unit": "m",
                "frame_note": FRAME_NOTE,
                "created_at": datetime.now(timezone.utc),
            }
        ],
    )

    # Nullable ownership reference + backfill. batch_alter_table so the FK is
    # also addable on SQLite; on PostgreSQL it emits plain ALTER TABLE.
    for table in _OWNED_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("facility_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                f"fk_{table}_facility_id", "facility", ["facility_id"], ["id"], ondelete="RESTRICT"
            )
    for table in _OWNED_TABLES:
        op.execute(
            sa.text(
                f"UPDATE {table} SET facility_id = "  # noqa: S608 - table names are a fixed constant tuple
                "(SELECT id FROM facility WHERE name = :name) WHERE facility_id IS NULL"
            ).bindparams(name=DEFAULT_FACILITY_NAME)
        )


def downgrade() -> None:
    for table in reversed(_OWNED_TABLES):
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"fk_{table}_facility_id", type_="foreignkey")
            batch.drop_column("facility_id")

    op.drop_index("ix_sensor_asset_id", table_name="sensor")
    op.drop_table("sensor")

    op.drop_index("uq_asset_pose_open", table_name="asset_pose")
    op.drop_table("asset_pose")

    op.drop_index("ix_asset_edge_parent", table_name="asset_edge")
    op.drop_index("ix_asset_edge_child_rel_from", table_name="asset_edge")
    op.drop_index("uq_asset_edge_open_triple", table_name="asset_edge")
    op.drop_index("uq_asset_edge_open_located_in", table_name="asset_edge")
    op.drop_table("asset_edge")

    op.drop_index("ix_asset_facility_type", table_name="asset")
    op.drop_table("asset")

    op.drop_table("facility")

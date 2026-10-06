from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from src.timeutil import parse_timestamp, utc_now


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


# Allowed role values for RBAC
USER_ROLE_VIEWER = "viewer"
USER_ROLE_OPERATOR = "operator"


class User(Base):
    """
    User account for JWT auth. Roles: viewer (read-only, operator (can adjust controls).
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=USER_ROLE_VIEWER)  # viewer | operator

    def is_operator(self) -> bool:
        return self.role == USER_ROLE_OPERATOR


class RefreshToken(Base):
    """
    Opaque refresh token for a User, used to mint new short-lived JWT access
    tokens without re-authenticating. Only the SHA-256 hash of the token is
    stored (see api/auth.py) -- a DB dump never yields a usable token.

    Rotated on every use: ``replaced_by_id`` chains an old, revoked token to
    the new one it was exchanged for, which makes token-reuse (a revoked
    token presented again) detectable after the fact.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("refresh_tokens.id", ondelete="SET NULL"), nullable=True
    )

    user: Mapped["User"] = relationship("User")


class AuditLog(Base):
    """
    Append-only record of sensitive actions: operator account creation,
    POST /api/optimize triggers, and alert acknowledgment. See
    api/services/audit_service.py for the writer; nothing in this codebase
    updates or deletes a row here.
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)

    # Denormalized username: the row still reads sensibly if the user is later deleted.
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    details: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class SensorReading(Base):
    """
    Single sensor/state snapshot from the digital twin.

    Stored from /api/state, /api/simulate, WebSocket live, or optimization results.
    """

    __tablename__ = "sensor_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    # Source of this reading
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # api | ws | simulation | optimization

    # State fields (align with DataCentreState / API response)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    server_utilisation: Mapped[float] = mapped_column(Float, nullable=False)
    outside_temp_C: Mapped[float] = mapped_column(Float, nullable=False)
    server_inlet_temp_C: Mapped[float] = mapped_column(Float, nullable=False)
    server_outlet_temp_C: Mapped[float] = mapped_column(Float, nullable=False)
    it_power_kw: Mapped[float] = mapped_column(Float, nullable=False)
    cooling_power_kw: Mapped[float] = mapped_column(Float, nullable=False)
    total_power_kw: Mapped[float] = mapped_column(Float, nullable=False)
    pue: Mapped[float] = mapped_column(Float, nullable=False)
    water_flow_lpm: Mapped[float] = mapped_column(Float, nullable=False)
    water_consumed_L: Mapped[float] = mapped_column(Float, nullable=False)
    wue: Mapped[float] = mapped_column(Float, nullable=False)
    humidity_pct: Mapped[float] = mapped_column(Float, nullable=False)
    water_pressure_bar: Mapped[float] = mapped_column(Float, nullable=False)
    cooling_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    anomaly: Mapped[int] = mapped_column(Integer, default=0)

    # T9 / M3: facility ownership reference. Nullable and additive: existing writers
    # do not set it yet (backfilled to the default facility by migration M3).
    facility_id: Mapped[Optional[int]] = mapped_column(ForeignKey("facility.id", ondelete="RESTRICT"), nullable=True)

    # Optional: link to simulation or optimization run
    simulation_run_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("simulation_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    optimization_result_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("optimization_results.id", ondelete="SET NULL"), nullable=True, index=True
    )

    simulation_run: Mapped[Optional["SimulationRun"]] = relationship("SimulationRun", back_populates="readings")
    optimization_result: Mapped[Optional["OptimizationResult"]] = relationship(
        "OptimizationResult", back_populates="readings"
    )

    @classmethod
    def from_state_dict(
        cls,
        d: dict[str, Any],
        source: str,
        *,
        simulation_run_id: int | None = None,
        optimization_result_id: int | None = None,
    ) -> "SensorReading":
        """Build SensorReading from API/twin state dict (e.g. DataCentreState.to_dict())."""
        # T12: no substitution of "now" for a missing/unparseable timestamp, and no naive values.
        # Raises src.timeutil.TimeContractError (a ValueError) instead.
        ts = parse_timestamp(d.get("timestamp"))
        return cls(
            source=source,
            timestamp=ts,
            server_utilisation=float(d["server_utilisation"]),
            outside_temp_C=float(d["outside_temp_C"]),
            server_inlet_temp_C=float(d["server_inlet_temp_C"]),
            server_outlet_temp_C=float(d["server_outlet_temp_C"]),
            it_power_kw=float(d["it_power_kw"]),
            cooling_power_kw=float(d["cooling_power_kw"]),
            total_power_kw=float(d["total_power_kw"]),
            pue=float(d["pue"]),
            water_flow_lpm=float(d["water_flow_lpm"]),
            water_consumed_L=float(d["water_consumed_L"]),
            wue=float(d["wue"]),
            humidity_pct=float(d["humidity_pct"]),
            water_pressure_bar=float(d["water_pressure_bar"]),
            cooling_mode=str(d["cooling_mode"]),
            anomaly=int(d.get("anomaly", 0)),
            simulation_run_id=simulation_run_id,
            optimization_result_id=optimization_result_id,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to API-style dict."""
        return {
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "server_utilisation": self.server_utilisation,
            "outside_temp_C": self.outside_temp_C,
            "server_inlet_temp_C": self.server_inlet_temp_C,
            "server_outlet_temp_C": self.server_outlet_temp_C,
            "it_power_kw": self.it_power_kw,
            "cooling_power_kw": self.cooling_power_kw,
            "total_power_kw": self.total_power_kw,
            "pue": self.pue,
            "water_flow_lpm": self.water_flow_lpm,
            "water_consumed_L": self.water_consumed_L,
            "wue": self.wue,
            "humidity_pct": self.humidity_pct,
            "water_pressure_bar": self.water_pressure_bar,
            "cooling_mode": self.cooling_mode,
            "anomaly": self.anomaly,
        }


class SimulationRun(Base):
    """
    Metadata for a simulation request (e.g. /api/simulate/{hours}).

    Hourly snapshots can be stored as SensorReadings linked to this run.
    """

    __tablename__ = "simulation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    hours: Mapped[int] = mapped_column(Integer, nullable=False)
    utilisation: Mapped[float] = mapped_column(Float, nullable=False)
    stress: Mapped[float] = mapped_column(Float, nullable=False)

    # T9 / M3: facility ownership reference. Nullable and additive: existing writers
    # do not set it yet (backfilled to the default facility by migration M3).
    facility_id: Mapped[Optional[int]] = mapped_column(ForeignKey("facility.id", ondelete="RESTRICT"), nullable=True)

    # Optional: store full result as JSON for quick retrieval
    result_snapshot: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSON, nullable=True)

    readings: Mapped[list["SensorReading"]] = relationship(
        "SensorReading", back_populates="simulation_run", cascade="all, delete-orphan"
    )


class OptimizationResult(Base):
    """
    Result of a single /api/optimize run (RL optimization).

    Stores summary and optional per-step results.
    """

    __tablename__ = "optimization_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    alpha: Mapped[float] = mapped_column(Float, nullable=False)
    beta: Mapped[float] = mapped_column(Float, nullable=False)
    gamma: Mapped[float] = mapped_column(Float, nullable=False)
    water_stress: Mapped[float] = mapped_column(Float, nullable=False)
    hours: Mapped[int] = mapped_column(Integer, nullable=False)

    mean_pue: Mapped[float] = mapped_column(Float, nullable=False)
    mean_wue: Mapped[float] = mapped_column(Float, nullable=False)
    mean_cooling_power_kw: Mapped[float] = mapped_column(Float, nullable=False)
    total_water_consumed_L: Mapped[float] = mapped_column(Float, nullable=False)
    total_reward: Mapped[float] = mapped_column(Float, nullable=False)
    safety_violations: Mapped[int] = mapped_column(Integer, nullable=False)

    # Full results array as JSON (each element is a state dict)
    results_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)

    readings: Mapped[list["SensorReading"]] = relationship(
        "SensorReading", back_populates="optimization_result", cascade="all, delete-orphan"
    )


class Alert(Base):
    """
    Anomaly or system alert (e.g. from /api/anomaly_score or real-time alert system).
    """

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    score: Mapped[float] = mapped_column(Float, nullable=False)
    alert: Mapped[bool] = mapped_column(Boolean, nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # INFO | WARNING | CRITICAL

    # Optional link to sensor reading that triggered the alert
    sensor_reading_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sensor_readings.id", ondelete="SET NULL"), nullable=True
    )

    # T9 / M3: facility ownership reference. Nullable and additive: existing writers
    # do not set it yet (backfilled to the default facility by migration M3).
    facility_id: Mapped[Optional[int]] = mapped_column(ForeignKey("facility.id", ondelete="RESTRICT"), nullable=True)

    # Acknowledgment (operator-only, see POST /api/alerts/{id}/acknowledge). Who
    # acknowledged is stored as a username, not a user_id FK, for the same reason
    # as AuditLog.username: it should still read sensibly if the account is deleted.
    acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    acknowledged_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


# =============================================================================
# T9 -- Facility / asset model (migration M3)
#
# Conventions (see also facility.frame_note, written by M3 / scripts/seed_facility.py):
#   * One facility frame, metres. Right-handed, Y-up. Pose (x, y, z) is the
#     geometric centre of the asset; rotation_deg is about +Y (right-hand rule).
#   * Time-bounded rows (asset_edge, asset_pose) use HALF-OPEN intervals:
#     a row is in force at instant t iff valid_from <= t AND (valid_to IS NULL OR t < valid_to).
#   * An edge reads "child <relation> parent": rack located_in zone,
#     crac serves zone, rack powered_by pdu. The subject is always the child.
#   * asset_type / relation are validated TEXT (api/services/facility_service.py),
#     not DB enums, so new types need no migration.
#   * All timestamps are timezone-aware UTC (debt D-2: new code does not use utcnow).
# =============================================================================


_utcnow = utc_now  # backwards-compatible alias; the single clock is src.timeutil.utc_now


class Facility(Base):
    """A site with one metre-based coordinate frame."""

    __tablename__ = "facility"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    frame_unit: Mapped[str] = mapped_column(String(8), nullable=False, default="m", server_default="m")
    # Documents origin, axes, pose convention and the scene-unit -> metre factor.
    frame_note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (CheckConstraint("frame_unit = 'm'", name="ck_facility_frame_unit_metre"),)


class Asset(Base):
    """A typed physical thing (zone, rack, CRAC, PDU, ...). Identity never changes on a move."""

    __tablename__ = "asset"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    facility_id: Mapped[int] = mapped_column(ForeignKey("facility.id", ondelete="RESTRICT"), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(32), nullable=False)  # validated text, not an enum
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)  # e.g. "zone-1-row-1-rack-1"
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    retired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("facility_id", "external_id", name="uq_asset_facility_external_id"),
        Index("ix_asset_facility_type", "facility_id", "asset_type"),
    )


class AssetEdge(Base):
    """Time-bounded relationship. Reads: child <relation> parent. relation in located_in|serves|powered_by."""

    __tablename__ = "asset_edge"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    parent_asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id", ondelete="RESTRICT"), nullable=False)
    child_asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id", ondelete="RESTRICT"), nullable=False)
    relation: Mapped[str] = mapped_column(String(16), nullable=False)  # validated text, not an enum
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_asset_edge_interval"),
        CheckConstraint("parent_asset_id <> child_asset_id", name="ck_asset_edge_no_self"),
        # At most ONE open located_in edge per child (a rack is in one place at a time).
        Index(
            "uq_asset_edge_open_located_in",
            "child_asset_id",
            unique=True,
            postgresql_where=text("relation = 'located_in' AND valid_to IS NULL"),
            sqlite_where=text("relation = 'located_in' AND valid_to IS NULL"),
        ),
        # No two identical open edges (same child, parent, relation).
        Index(
            "uq_asset_edge_open_triple",
            "child_asset_id",
            "parent_asset_id",
            "relation",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
            sqlite_where=text("valid_to IS NULL"),
        ),
        Index("ix_asset_edge_child_rel_from", "child_asset_id", "relation", "valid_from"),
        Index("ix_asset_edge_parent", "parent_asset_id"),
    )


class AssetPose(Base):
    """Time-bounded pose in the facility frame (metres). Pose point = centre of the asset."""

    __tablename__ = "asset_pose"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id", ondelete="RESTRICT"), nullable=False)
    x: Mapped[float] = mapped_column(Float, nullable=False)
    y: Mapped[float] = mapped_column(Float, nullable=False)
    z: Mapped[float] = mapped_column(Float, nullable=False)
    rotation_deg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="ck_asset_pose_interval"),
        # Idempotency key for moves: (asset_id, valid_from).
        UniqueConstraint("asset_id", "valid_from", name="uq_asset_pose_asset_from"),
        # At most one open pose per asset.
        Index(
            "uq_asset_pose_open",
            "asset_id",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
            sqlite_where=text("valid_to IS NULL"),
        ),
    )


class Sensor(Base):
    """Sensor registry entry attached to an asset. Registry only in T9: no samples (T10)."""

    __tablename__ = "sensor"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("asset.id", ondelete="RESTRICT"), nullable=False, index=True)
    measurand: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g. "inlet_temperature"
    unit: Mapped[str] = mapped_column(String(16), nullable=False)  # canonical SI / degC
    sampling_interval_s: Mapped[float] = mapped_column(Float, nullable=False)
    # Globally unique (a facility is reachable only through asset_id; see report deviation D3).
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    min_valid: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_valid: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # T16 (§9.1): IANA zone in which the source writes naive timestamps. Informational for ingest: a naive
    # ts_event is rejected unless the caller opts in (see src/telemetry/ingest.py).
    source_tz: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC", server_default="UTC")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    retired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("sampling_interval_s > 0", name="ck_sensor_sampling_positive"),
        CheckConstraint(
            "min_valid IS NULL OR max_valid IS NULL OR min_valid <= max_valid",
            name="ck_sensor_valid_range",
        ),
    )


TELEMETRY_ORIGINS = ("simulated", "measured", "replay")
TELEMETRY_QUALITIES = ("ok", "invalid")
TELEMETRY_INVALID_REASONS = ("range", "future")


class TelemetrySample(Base):
    """One timestamped value from one sensor (T16, §9.1). Written ONLY by ``src.telemetry.ingest.ingest_samples``.

    The sensor fixes the asset and facility, so there is deliberately no ``facility_id`` here.
    """

    __tablename__ = "telemetry_sample"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    sensor_id: Mapped[int] = mapped_column(ForeignKey("sensor.id", ondelete="RESTRICT"), nullable=False)
    stream_id: Mapped[str] = mapped_column(String(64), nullable=False)  # live | replay:<uuid> | import:<dataset_id>
    ts_event: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ts_ingest: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)  # finite only
    quality: Mapped[str] = mapped_column(String(8), nullable=False)
    invalid_reason: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    origin: Mapped[str] = mapped_column(String(16), nullable=False)  # no default, by contract
    sim_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("sensor_id", "stream_id", "ts_event", name="uq_telemetry_sensor_stream_event"),
        CheckConstraint("origin IN ('simulated', 'measured', 'replay')", name="ck_telemetry_origin"),
        CheckConstraint("(origin = 'simulated') = (sim_time IS NOT NULL)", name="ck_telemetry_sim_time_iff_simulated"),
        CheckConstraint("quality IN ('ok', 'invalid')", name="ck_telemetry_quality"),
        CheckConstraint(
            "(quality = 'ok' AND invalid_reason IS NULL) OR "
            "(quality = 'invalid' AND invalid_reason IS NOT NULL AND invalid_reason IN ('range', 'future'))",
            name="ck_telemetry_invalid_reason",
        ),
    )

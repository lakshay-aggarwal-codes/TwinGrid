from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=USER_ROLE_VIEWER)  # viewer | operator

    def is_operator(self) -> bool:
        return self.role == USER_ROLE_OPERATOR


class SensorReading(Base):
    """
    Single sensor/state snapshot from the digital twin.

    Stored from /api/state, /api/simulate, WebSocket live, or optimization results.
    """

    __tablename__ = "sensor_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

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

    # Optional: link to simulation or optimization run
    simulation_run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("simulation_runs.id", ondelete="SET NULL"), nullable=True, index=True)
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
        ts = d.get("timestamp")
        if isinstance(ts, str) and ts:
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                ts = datetime.utcnow()
        elif ts is None or (isinstance(ts, str) and not ts):
            ts = datetime.utcnow()
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    hours: Mapped[int] = mapped_column(Integer, nullable=False)
    utilisation: Mapped[float] = mapped_column(Float, nullable=False)
    stress: Mapped[float] = mapped_column(Float, nullable=False)

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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    score: Mapped[float] = mapped_column(Float, nullable=False)
    alert: Mapped[bool] = mapped_column(Boolean, nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # INFO | WARNING | CRITICAL

    # Optional link to sensor reading that triggered the alert
    sensor_reading_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sensor_readings.id", ondelete="SET NULL"), nullable=True)


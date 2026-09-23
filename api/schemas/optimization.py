from __future__ import annotations

from pydantic import BaseModel, Field


class OptimizeRequest(BaseModel):
    """Request body for the optimization endpoint."""

    alpha: float = Field(0.5, ge=0, le=1, description="WUE weight")
    beta: float = Field(0.3, ge=0, le=1, description="(PUE-1) weight")
    gamma: float = Field(0.2, ge=0, le=1, description="Carbon-emissions weight")
    water_stress: float = Field(0.0, ge=0, le=1, description="Water stress level")
    hours: int = Field(24, ge=1, le=168, description="Simulation hours")


class AnomalyScoreResponse(BaseModel):
    """Response for anomaly detection."""

    score: float = Field(description="Reconstruction error score")
    threshold: float = Field(description="Model's trained alert threshold (95th percentile of training error)")
    alert: bool = Field(description="True if anomaly detected")
    type: str = Field(description="Anomaly type or 'normal'")
    message: str = Field(description="Human-readable message")
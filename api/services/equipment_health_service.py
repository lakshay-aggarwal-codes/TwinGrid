"""Serves the predictive-maintenance model's validated performance metrics.

NOTE: this does NOT serve live per-rack RUL predictions. The model is
trained on NASA C-MAPSS (aircraft engine sensors), which has no valid
mapping to the digital twin's live telemetry -- same structural issue as
the NAB/anomaly-detector mismatch in Phase 6. What's served here is the
model's own validated methodology performance (baseline vs. LSTM, from
its last training run), with the proxy-dataset caveat as a required field.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

METRICS_PATH = Path("models/predictive_maintenance/metrics.json")


def get_equipment_health_summary() -> dict[str, Any]:
    if not METRICS_PATH.exists():
        return {
            "available": False,
            "message": "No predictive-maintenance training run found. "
                        "Run `python -m src.predictive_maintenance.train` first.",
        }
    metrics = json.loads(METRICS_PATH.read_text())
    return {"available": True, **metrics}
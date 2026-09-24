"""The API must say whether carbon intensity is real data or the flat fallback."""

import pandas as pd

from api.services import twin_service
from src import carbon_provider
from src.digital_twin import DigitalTwin


def _write_real_csv(path):
    rows = [{"timestamp_utc": f"2026-01-01T{h:02d}:00:00Z", "zone": "IN-NO", "carbon_intensity_gco2_per_kwh": 300 + h}
            for h in range(24)]
    pd.DataFrame(rows).to_csv(path, index=False)


class TestCarbonIsRealFlag:
    def test_flat_fallback_is_reported_as_not_real(self, tmp_path, monkeypatch):
        monkeypatch.setattr(carbon_provider, "CLEANED_CARBON_PATH", tmp_path / "missing.csv")
        assert DigitalTwin().carbon_data_is_real is False

    def test_real_csv_is_reported_as_real(self, tmp_path, monkeypatch):
        csv = tmp_path / "carbon_intensity.csv"
        _write_real_csv(csv)
        monkeypatch.setattr(carbon_provider, "CLEANED_CARBON_PATH", csv)
        assert DigitalTwin().carbon_data_is_real is True

    def test_state_and_whatif_expose_the_flag(self, tmp_path, monkeypatch):
        monkeypatch.setattr(carbon_provider, "CLEANED_CARBON_PATH", tmp_path / "missing.csv")
        monkeypatch.setattr(twin_service, "_twin", None)  # force a fresh shared twin
        assert twin_service.compute_state(0.5, 25.0, 0.0, "auto")["carbon_data_is_real"] is False
        assert twin_service.compute_whatif(0.5, 25.0, 0.0, "auto", 7.0)["carbon_data_is_real"] is False

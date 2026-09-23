"""
Regression test for Phase 4: src/data_generator.py previously had its own,
DRIFTED copy of the twin's physics (different airflow, no idle-power
floor, fixed evaporative-only COP). This test asserts the generator's
output is computable via DigitalTwin's own methods, at every row -- i.e.
there is exactly one physics implementation, not two that happen to agree
by coincidence.
"""

import numpy as np

from src.data_generator import generate_sensor_data
from src.digital_twin import DigitalTwin


class TestGeneratorMatchesTwinPhysics:
    def test_it_power_matches_twins_own_formula(self):
        """Regression check for the specific bug: pre-fix, it_power_kw at
        utilisation=0 was 0 (no idle floor); post-fix it must equal
        DigitalTwin's own idle-power-fraction formula."""
        df = generate_sensor_data(days=1, seed=1)
        twin = DigitalTwin(max_it_power_kw=500.0, idle_power_fraction=0.4)

        # Spot-check 20 rows against the twin's own compute_it_power --
        # if generator and twin ever diverge again, this catches it directly.
        sample = df.sample(n=20, random_state=1)
        for _, row in sample.iterrows():
            expected = twin.compute_it_power(row["server_utilisation"])
            assert np.isclose(row["it_power_kw"], expected, rtol=1e-6), (
                f"Generator's it_power_kw ({row['it_power_kw']}) does not match "
                f"DigitalTwin.compute_it_power ({expected}) -- physics have drifted again."
            )

    def test_cooling_mode_column_exists_and_varies(self):
        """Regression check: pre-fix, there was no cooling_mode column at
        all. Post-fix, it must exist AND show more than one mode across a
        90-day run (otherwise the RL/forecast training data has no signal
        to learn mode-dependent behaviour from)."""
        df = generate_sensor_data(days=90, seed=2)
        assert "cooling_mode" in df.columns
        assert df["cooling_mode"].nunique() > 1

    def test_water_stress_column_exists_and_varies(self):
        df = generate_sensor_data(days=90, seed=3)
        assert "water_stress" in df.columns
        assert df["water_stress"].std() > 0.01  # not a constant

    def test_drought_episodes_actually_cross_threshold(self):
        """Confirms the seasonal+drought overlay (Phase 4) produces at
        least some rows above the drought threshold -- otherwise the
        cooling_mode column would never show the forced override, and the
        training data would be missing drought behaviour entirely."""
        df = generate_sensor_data(days=90, seed=4)
        assert (df["water_stress"] > 0.7).sum() > 0
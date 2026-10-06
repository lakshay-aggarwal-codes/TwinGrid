"""T25: leakage-safe datasets v2 (src/data_pipeline.py, src/data_generator.py, scripts/make_datasets.py).

The weather and water-stress files used here are TEST FIXTURES written into a temp directory (a smooth synthetic year
for every city of the real split). They exist so the generator and the leakage rules can be exercised; they are NOT
the cleaned Open-Meteo / Aqueduct inputs, and nothing generated from them is a dataset v2. The real configs
(configs/splits, configs/scenarios) are used as shipped, except that scenarios are shortened to 3 days.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src import data_generator as gen
from src import data_pipeline as dp

ROOT = Path(__file__).resolve().parents[1]


def _load_make_datasets():
    spec = importlib.util.spec_from_file_location("make_datasets_t25", ROOT / "scripts" / "make_datasets.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


make_datasets = _load_make_datasets()


# ----------------------------------------------------------------------------- fixtures
@pytest.fixture(scope="module")
def split_cfg():
    return dp.load_split_config()


@pytest.fixture(scope="module")
def short_scenario_cfg():
    cfg = dp.load_scenario_config()
    cfg = copy.deepcopy(cfg)
    cfg["days_per_scenario"] = 3
    cfg["scenarios_per_cell"] = {"train": 1, "val": 1, "test": 1}
    cfg.pop("scenario_set_id", None)
    cfg["scenario_set_id"] = dp.config_id(cfg)
    return cfg


@pytest.fixture(scope="module")
def inputs(tmp_path_factory, split_cfg):
    """TEST-FIXTURE cleaned inputs + a registry for them, in a temp directory."""
    root = tmp_path_factory.mktemp("cleaned")
    cities = sorted({c["city"] for cells in split_cfg["cells"].values() for c in cells})
    hours = pd.date_range("2025-01-01", "2025-12-31 23:00", freq="h")
    rows = []
    for k, city in enumerate(cities):
        doy = hours.dayofyear.to_numpy()
        hod = hours.hour.to_numpy()
        temp = 22 + 0.4 * k + 9 * np.sin(2 * np.pi * (doy - 100) / 365) + 4 * np.sin(2 * np.pi * (hod - 14) / 24)
        hum = 55 + 15 * np.sin(2 * np.pi * (doy - 200) / 365) + 5 * np.sin(2 * np.pi * (hod - 5) / 24)
        rows.append(pd.DataFrame({"timestamp_utc": hours, "city": city, "outside_temp_C": temp, "humidity_pct": hum}))
    weather = root / "weather_open_meteo.csv"
    pd.concat(rows).to_csv(weather, index=False)
    water = root / "water_stress_aqueduct.csv"
    pd.DataFrame({"name_0": ["India", "Norway", "Chile"], "bws_score": [4.0, 0.5, 2.5]}).to_csv(water, index=False)
    registry = root / "MANIFEST.json"
    manifest = {"schema": 1, "inputs": []}
    for path in (weather, water):
        with path.open("rb") as fh:
            n_rows = sum(1 for _ in fh) - 1
        manifest["inputs"].append({"path": _rel(path), "sha256": dp.sha256_file(path), "rows": n_rows})
    registry.write_text(json.dumps(manifest), encoding="utf-8")
    return {"weather": weather, "water": water, "registry": registry, "root": root}


def _rel(path: Path) -> str:
    """cleaned_input_entry() reports paths relative to the repo when possible; for temp files it falls back."""
    try:
        return path.relative_to(dp.REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


@pytest.fixture(scope="module")
def built(inputs, split_cfg, short_scenario_cfg, tmp_path_factory):
    out = tmp_path_factory.mktemp("datasets_a")
    ident, directory = _build(inputs, split_cfg, short_scenario_cfg, out)
    return {"id": ident, "dir": directory, "out": out}


def _build(inputs, split_cfg, scenario_cfg, out, **kw):
    return make_datasets.build_dataset(
        split_cfg,
        scenario_cfg,
        out_dir=out,
        weather_path=inputs["weather"],
        water_stress_path=inputs["water"],
        registry_path=inputs["registry"],
        **kw,
    )


def _read(built, name):
    return pd.read_csv(built["dir"] / name)


# ----------------------------------------------------------------------------- configs (no data needed)
def test_split_config_meets_the_section_13_3_rules(split_cfg):
    cells = {s: {(c["city"], c["month_block"]) for c in split_cfg["cells"][s]} for s in dp.SPLITS}
    for a, b in (("train", "val"), ("train", "test"), ("val", "test")):
        assert not (cells[a] & cells[b])
    seen_cities = {c for s in ("train", "val") for c, _ in cells[s]}
    seen_blocks = {b for s in ("train", "val") for _, b in cells[s]}
    assert {c for c, _ in cells["test"]} - seen_cities, "test needs an unseen city"
    assert {b for _, b in cells["test"]} - seen_blocks, "test needs an unseen month-block"
    held_out = (
        set(split_cfg["workload_regimes"]["test"])
        - set(split_cfg["workload_regimes"]["train"])
        - set(split_cfg["workload_regimes"]["val"])
    )
    assert held_out == {"burst"}


def test_seed_ranges_are_the_contract_ranges(split_cfg):
    r = split_cfg["scenario_seed_ranges"]
    assert r["train"][0] == 0 and r["train"][1] == 99_999
    assert r["val"][0] == 100_000 and r["test"][0] == 200_000
    assert r["train"][1] < r["val"][0] and r["val"][1] < r["test"][0]


def test_every_scenario_seed_lies_in_its_splits_range(split_cfg):
    scenario_cfg = dp.load_scenario_config()
    scenarios = dp.build_scenarios(split_cfg, scenario_cfg)
    assert len({s.seed for s in scenarios}) == len(scenarios)
    for s in scenarios:
        lo, hi = split_cfg["scenario_seed_ranges"][s.split]
        assert lo <= s.seed <= hi
        assert s.regime in split_cfg["workload_regimes"][s.split]


def test_configs_plan_at_least_thirty_test_events(split_cfg):
    scenario_cfg = dp.load_scenario_config()
    planned = dp.planned_event_counts(split_cfg, scenario_cfg)
    assert planned["test"] >= scenario_cfg["min_test_events"] >= 30


def test_config_ids_are_content_hashes(split_cfg):
    again = dp.load_split_config()
    assert again["split_id"] == split_cfg["split_id"] and len(split_cfg["split_id"]) == 64
    changed = copy.deepcopy(split_cfg)
    changed["year"] = 2024
    assert dp.config_id(changed) != split_cfg["split_id"]


def test_shared_cell_is_rejected(split_cfg):
    bad = copy.deepcopy(split_cfg)
    bad["cells"]["val"].append(bad["cells"]["train"][0])
    with pytest.raises(dp.DatasetConfigError, match="cells shared by train and val"):
        dp.validate_split(bad)


def test_overlapping_seed_ranges_are_rejected(split_cfg):
    bad = copy.deepcopy(split_cfg)
    bad["scenario_seed_ranges"]["val"] = [99_999, 199_999]
    with pytest.raises(dp.DatasetConfigError, match="overlap"):
        dp.validate_split(bad)


def test_test_without_an_unseen_city_is_rejected(split_cfg):
    bad = copy.deepcopy(split_cfg)
    seen = bad["cells"]["train"][0]["city"]
    bad["cells"]["test"] = [{"city": seen, "month_block": "D"}]
    with pytest.raises(dp.DatasetConfigError, match="unseen|absent from train and val"):
        dp.validate_split(bad)


def test_test_without_a_held_out_regime_is_rejected(split_cfg):
    bad = copy.deepcopy(split_cfg)
    bad["workload_regimes"]["test"] = ["diurnal", "high"]
    with pytest.raises(dp.DatasetConfigError, match="regime"):
        dp.validate_split(bad)


# ----------------------------------------------------------------------------- membership disjointness
def test_membership_is_disjoint_in_the_generated_data(built):
    rows = pd.concat([_read(built, f"{s}.csv")[["scenario_id", "split", "city", "month_block"]] for s in dp.SPLITS])
    dp.assert_membership_disjoint(rows)  # raises on any shared scenario or cell
    for s in dp.SPLITS:
        assert set(rows[rows["split"] == s]["split"]) == {s}
    cells = {}
    for s in dp.SPLITS:
        part = rows[rows["split"] == s][["city", "month_block"]].drop_duplicates()
        cells[s] = set(map(tuple, part.to_numpy()))
    for a, b in (("train", "val"), ("train", "test"), ("val", "test")):
        assert not (cells[a] & cells[b])


def test_generated_rows_match_the_split_config_cells_exactly(built, split_cfg):
    for s in dp.SPLITS:
        got = set(map(tuple, _read(built, f"{s}.csv")[["city", "month_block"]].drop_duplicates().to_numpy()))
        want = {(c["city"], c["month_block"]) for c in split_cfg["cells"][s]}
        assert got == want


def test_test_contains_an_unseen_city_month_block_and_regime(built):
    seen = pd.concat([_read(built, "train.csv"), _read(built, "val.csv")])
    test = _read(built, "test.csv")
    assert set(test["city"]) - set(seen["city"])
    assert set(test["month_block"]) - set(seen["month_block"])
    assert set(test["regime"]) - set(seen["regime"]) == {"burst"}


def test_membership_check_catches_a_leak():
    leaked = pd.DataFrame(
        {
            "scenario_id": ["a", "a"],
            "split": ["train", "test"],
            "city": ["X", "X"],
            "month_block": ["A", "A"],
        }
    )
    with pytest.raises(dp.DatasetConfigError):
        dp.assert_membership_disjoint(leaked)
    shared_cell = pd.DataFrame(
        {"scenario_id": ["a", "b"], "split": ["train", "val"], "city": ["X", "X"], "month_block": ["A", "A"]}
    )
    with pytest.raises(dp.DatasetConfigError, match="cells"):
        dp.assert_membership_disjoint(shared_cell)


# ----------------------------------------------------------------------------- scalers fit on train only
def test_scaler_recomputed_from_train_rows_equals_stored(built, split_cfg):
    manifest = json.loads((built["dir"] / "manifest.json").read_text(encoding="utf-8"))
    stored = manifest["preprocessing"]
    train = _read(built, "train.csv")
    dp.verify_preprocessing(stored, train, expected_fit_split_id=f"{split_cfg['split_id']}#train", rtol=1e-5)
    assert stored["fit_split_id"] == f"{split_cfg['split_id']}#train" and stored["fit_rows"] == len(train)


def test_scaler_is_not_fit_on_validation_or_test_rows(built, split_cfg):
    stored = json.loads((built["dir"] / "manifest.json").read_text(encoding="utf-8"))["preprocessing"]
    train, val, test = (_read(built, f"{s}.csv") for s in dp.SPLITS)
    with pytest.raises(dp.DatasetConfigError):
        dp.verify_preprocessing(stored, pd.concat([train, test]), expected_fit_split_id=stored["fit_split_id"])
    with pytest.raises(dp.DatasetConfigError):
        dp.verify_preprocessing(stored, val, expected_fit_split_id=stored["fit_split_id"])


def test_fit_preprocessing_refuses_non_train_rows_and_a_missing_fit_split_id(built):
    test = _read(built, "test.csv")
    with pytest.raises(dp.DatasetConfigError, match="non-train"):
        dp.fit_preprocessing(test, fit_split_id="x#train")
    with pytest.raises(dp.DatasetConfigError, match="fit_split_id"):
        dp.fit_preprocessing(_read(built, "train.csv"), fit_split_id="")


def test_verify_rejects_a_wrong_fit_split_id_and_a_tampered_statistic(built):
    stored = json.loads((built["dir"] / "manifest.json").read_text(encoding="utf-8"))["preprocessing"]
    train = _read(built, "train.csv")
    with pytest.raises(dp.DatasetConfigError, match="fit on"):
        dp.verify_preprocessing(stored, train, expected_fit_split_id="somewhere-else#train")
    tampered = copy.deepcopy(stored)
    tampered["mean"][0] += 0.5
    with pytest.raises(dp.DatasetConfigError, match="mean"):
        dp.verify_preprocessing(tampered, train, expected_fit_split_id=stored["fit_split_id"], rtol=1e-5)


# ----------------------------------------------------------------------------- determinism
def test_same_inputs_and_seeds_give_the_same_dataset_hash(inputs, split_cfg, short_scenario_cfg, built, tmp_path):
    ident2, directory2 = _build(inputs, split_cfg, short_scenario_cfg, tmp_path)
    assert ident2 == built["id"]
    for name in ("train.csv", "val.csv", "test.csv", "events.csv", "scenarios.csv", "manifest.json"):
        assert dp.sha256_file(directory2 / name) == dp.sha256_file(built["dir"] / name)


def test_dataset_id_is_the_sha256_of_the_manifest(built):
    manifest = json.loads((built["dir"] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dataset_id"] == built["id"] == dp.dataset_id(manifest)
    assert built["dir"].name == built["id"]
    for name, entry in manifest["files"].items():
        assert dp.sha256_file(built["dir"] / name) == entry["sha256"]


def test_a_different_seed_range_gives_a_different_dataset(inputs, split_cfg, short_scenario_cfg, built, tmp_path):
    other = copy.deepcopy(split_cfg)
    other["scenario_seed_ranges"]["train"] = [10, 99_999]
    other.pop("split_id")
    other["split_id"] = dp.config_id(other)
    ident, _ = _build(inputs, other, short_scenario_cfg, tmp_path)
    assert ident != built["id"]


def test_the_global_numpy_rng_neither_matters_nor_is_touched(split_cfg, short_scenario_cfg, inputs):
    weather = gen.load_cleaned_weather(inputs["weather"])
    scenario = dp.build_scenarios(split_cfg, short_scenario_cfg)[0]

    def run():
        return gen.generate_scenario(
            scenario, split_cfg, short_scenario_cfg, weather=weather, water_stress_baseline=0.8
        )

    np.random.seed(1)
    before = np.random.get_state()[1].copy()
    first, first_events, _ = run()
    assert np.array_equal(np.random.get_state()[1], before), "generation advanced the global RNG"
    np.random.seed(999)
    second, second_events, _ = run()
    pd.testing.assert_frame_equal(first, second)
    pd.testing.assert_frame_equal(first_events, second_events)


def test_rng_streams_are_independent_and_reproducible():
    a1, a2 = gen.make_rng(5, gen.STREAM_WORKLOAD), gen.make_rng(5, gen.STREAM_WORKLOAD)
    b = gen.make_rng(5, gen.STREAM_EVENTS)
    assert np.array_equal(a1.random(5), a2.random(5))
    assert not np.array_equal(gen.make_rng(5, gen.STREAM_WORKLOAD).random(5), b.random(5))


# ----------------------------------------------------------------------------- events
def test_event_table_has_the_contract_columns_and_one_row_per_event(built, short_scenario_cfg):
    events = _read(built, "events.csv")
    assert list(events.columns) == list(dp.EVENT_COLUMNS)
    assert events["event_id"].is_unique
    per = dp.events_per_scenario(short_scenario_cfg)
    assert len(events) == per * len(_read(built, "scenarios.csv"))
    assert set(events["type"]) == {"leak", "thermal"}
    for raw in events["params"]:
        assert isinstance(json.loads(raw), dict)


def test_no_event_crosses_a_scenario_or_split_boundary(built):
    events = _read(built, "events.csv")
    rows = pd.concat([_read(built, f"{s}.csv") for s in dp.SPLITS])
    n_rows = {sid: (0, int(n)) for sid, n in rows.groupby("scenario_id").size().items()}
    dp.assert_events_within_scenarios(events, n_rows)
    # each event is labelled on exactly its rows, and those rows belong to its scenario and its split
    for ev in events.itertuples(index=False):
        scen = rows[rows["scenario_id"] == ev.scenario_id].reset_index(drop=True)
        labelled = scen.loc[scen["event_id"] == ev.event_id]
        assert len(labelled) == ev.end_idx - ev.start_idx
        assert labelled.index.min() == ev.start_idx and labelled.index.max() == ev.end_idx - 1
        assert set(labelled["split"]) == {ev.split}
        assert (labelled["anomaly"] == 1).all()


def test_events_stay_away_from_scenario_edges_and_never_overlap(built, short_scenario_cfg):
    events = _read(built, "events.csv")
    margin = short_scenario_cfg["injection"]["edge_margin_intervals"]
    gap = short_scenario_cfg["injection"]["min_separation_intervals"]
    n = short_scenario_cfg["days_per_scenario"] * 24 * 60 // short_scenario_cfg["interval_minutes"]
    assert (events["start_idx"] >= margin).all() and (events["end_idx"] <= n - margin).all()
    for _, group in events.groupby("scenario_id"):
        spans = sorted(zip(group["start_idx"], group["end_idx"], strict=True))
        for (_, end_a), (start_b, _) in zip(spans, spans[1:], strict=False):
            assert start_b - end_a >= gap


def test_event_boundary_check_rejects_an_event_that_leaves_its_scenario():
    events = pd.DataFrame(
        [
            {
                "event_id": "train-0-E00",
                "scenario_id": "train-0",
                "split": "train",
                "type": "leak",
                "start": "x",
                "end": "y",
                "start_idx": 90,
                "end_idx": 110,
                "params": "{}",
            }
        ]
    )
    with pytest.raises(dp.DatasetConfigError, match="leaves its scenario"):
        dp.assert_events_within_scenarios(events, {"train-0": (0, 100)})
    with pytest.raises(dp.DatasetConfigError, match="unknown scenario"):
        dp.assert_events_within_scenarios(events, {"other": (0, 500)})
    dp.assert_events_within_scenarios(events, {"train-0": (0, 110)})


def test_event_windows_lie_inside_the_cells_month_block(built, split_cfg):
    rows = pd.concat([_read(built, f"{s}.csv") for s in dp.SPLITS])
    rows["timestamp"] = pd.to_datetime(rows["timestamp"])
    for block, months in split_cfg["month_blocks"].items():
        sub = rows[rows["month_block"] == block]
        assert set(sub["timestamp"].dt.month) <= set(months)
        assert set(sub["timestamp"].dt.year) == {split_cfg["year"]}


def test_windows_never_touch_the_last_day_of_a_block_where_hourly_weather_runs_out(built, split_cfg):
    rows = pd.concat([_read(built, f"{s}.csv") for s in dp.SPLITS])
    rows["timestamp"] = pd.to_datetime(rows["timestamp"])
    assert rows["timestamp"].max() < pd.Timestamp("2025-12-31")
    for block, months in split_cfg["month_blocks"].items():
        last_day = pd.Timestamp(split_cfg["year"], max(months), 1) + pd.offsets.MonthEnd(0)
        assert not (rows[rows["month_block"] == block]["timestamp"].dt.normalize() == last_day).any()


def test_at_least_thirty_test_events(built):
    manifest = json.loads((built["dir"] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["events"]["per_split"]["test"] >= 30
    assert int((_read(built, "events.csv")["split"] == "test").sum()) >= 30


def test_fewer_than_thirty_planned_test_events_is_refused_before_any_work(
    inputs, split_cfg, short_scenario_cfg, tmp_path
):
    thin = copy.deepcopy(short_scenario_cfg)
    thin["injection"]["per_scenario"]["leak"]["count"] = 0
    thin["injection"]["per_scenario"]["thermal"]["count"] = 0
    with pytest.raises(dp.DatasetConfigError, match="raise the injection counts"):
        _build(inputs, split_cfg, thin, tmp_path)
    assert not any(tmp_path.iterdir())


# ----------------------------------------------------------------------------- missing inputs raise
def test_missing_cleaned_weather_raises_and_writes_nothing(inputs, split_cfg, short_scenario_cfg, tmp_path):
    missing = {**inputs, "weather": tmp_path / "nope" / "weather_open_meteo.csv"}
    with pytest.raises(dp.MissingInputError, match="weather"):
        _build(missing, split_cfg, short_scenario_cfg, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_missing_water_stress_raises(inputs, split_cfg, short_scenario_cfg, tmp_path):
    missing = {**inputs, "water": tmp_path / "nope.csv"}
    with pytest.raises(dp.MissingInputError, match="water"):
        _build(missing, split_cfg, short_scenario_cfg, tmp_path / "out")


def test_unregistered_inputs_raise(inputs, split_cfg, short_scenario_cfg, tmp_path):
    with pytest.raises(dp.MissingInputError, match="register"):
        _build({**inputs, "registry": tmp_path / "MANIFEST.json"}, split_cfg, short_scenario_cfg, tmp_path / "out")


def test_an_input_changed_after_registration_raises(inputs, split_cfg, short_scenario_cfg, tmp_path):
    altered = tmp_path / "water_stress_aqueduct.csv"
    pd.DataFrame({"name_0": ["India"], "bws_score": [3.0]}).to_csv(altered, index=False)
    registry = json.loads(inputs["registry"].read_text(encoding="utf-8"))
    registry["inputs"][1] = {"path": _rel(altered), "sha256": "0" * 64, "rows": 1}
    reg = tmp_path / "MANIFEST.json"
    reg.write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(dp.DatasetConfigError, match="changed since it was registered"):
        _build({**inputs, "water": altered, "registry": reg}, split_cfg, short_scenario_cfg, tmp_path / "out")


def test_a_city_missing_from_the_cleaned_weather_raises(inputs, split_cfg, short_scenario_cfg, tmp_path):
    weather = pd.read_csv(inputs["weather"])
    weather = weather[weather["city"] != "Kochi"]
    path = tmp_path / "weather_open_meteo.csv"
    weather.to_csv(path, index=False)
    registry = json.loads(inputs["registry"].read_text(encoding="utf-8"))
    registry["inputs"][0] = {"path": _rel(path), "sha256": dp.sha256_file(path), "rows": len(weather)}
    reg = tmp_path / "MANIFEST.json"
    reg.write_text(json.dumps(registry), encoding="utf-8")
    with pytest.raises(dp.MissingInputError, match="Kochi"):
        _build({**inputs, "weather": path, "registry": reg}, split_cfg, short_scenario_cfg, tmp_path / "out")


def test_allow_synthetic_weather_proceeds_and_is_recorded_in_the_manifest(
    inputs, split_cfg, short_scenario_cfg, tmp_path
):
    no_weather = {**inputs, "weather": tmp_path / "absent.csv"}
    ident, directory = _build(no_weather, split_cfg, short_scenario_cfg, tmp_path / "out", allow_synthetic_weather=True)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["dataset_id"] == ident
    assert manifest["synthetic_inputs"], "synthetic substitution must be recorded"
    assert all(item.startswith("weather:") for item in manifest["synthetic_inputs"])
    assert len(manifest["synthetic_inputs"]) == len({c["city"] for s in dp.SPLITS for c in split_cfg["cells"][s]})
    assert all("weather_open_meteo" not in entry["path"] for entry in manifest["inputs"])


def test_a_real_input_dataset_records_no_synthetic_inputs(built):
    manifest = json.loads((built["dir"] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["synthetic_inputs"] == []
    assert len(manifest["inputs"]) == 2 and all(len(e["sha256"]) == 64 for e in manifest["inputs"])


def test_dataset_manifest_records_versions_and_config_ids(built, split_cfg, short_scenario_cfg):
    manifest = json.loads((built["dir"] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["split_id"] == split_cfg["split_id"]
    assert manifest["scenario_set_id"] == short_scenario_cfg["scenario_set_id"]
    assert manifest["generator_version"] == gen.GENERATOR_VERSION
    assert manifest["physics_version"] in ("1", "legacy-0")
    assert {"python", "numpy", "pandas"} <= set(manifest["environment"])


# ----------------------------------------------------------------------------- the registry and the legacy API
def test_register_then_verify_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "REPO_ROOT", tmp_path)
    cleaned = tmp_path / "data" / "cleaned"
    cleaned.mkdir(parents=True)
    f = cleaned / "weather_open_meteo.csv"
    f.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    registry = cleaned / "MANIFEST.json"
    manifest = dp.register_cleaned_inputs([f], registry)
    expected = {"path": "data/cleaned/weather_open_meteo.csv", "sha256": dp.sha256_file(f), "rows": 2}
    assert manifest["inputs"] == [expected]
    assert dp.verify_cleaned_inputs([f], registry)[0]["sha256"] == dp.sha256_file(f)
    f.write_text("a,b\n9,9\n", encoding="utf-8")
    with pytest.raises(dp.DatasetConfigError):
        dp.verify_cleaned_inputs([f], registry)


def test_register_refuses_a_missing_input(tmp_path):
    with pytest.raises(dp.MissingInputError):
        dp.register_cleaned_inputs([tmp_path / "missing.csv"], tmp_path / "MANIFEST.json")


def test_legacy_generate_sensor_data_raises_without_inputs_and_works_with_the_flags(monkeypatch, tmp_path):
    monkeypatch.setattr(gen, "CLEANED_WEATHER_PATH", tmp_path / "w.csv")
    monkeypatch.setattr(gen, "CLEANED_WATER_STRESS_PATH", tmp_path / "a.csv")
    with pytest.raises(dp.MissingInputError):
        gen.generate_sensor_data(days=2, seed=1)
    with pytest.raises(dp.MissingInputError):  # weather flag alone is not enough: water stress is required too
        gen.generate_sensor_data(days=2, seed=1, allow_synthetic_weather=True)
    df, events = gen.generate_sensor_data(
        days=2, seed=1, allow_synthetic_weather=True, allow_synthetic_water_stress=True, return_events=True
    )
    assert df.attrs["synthetic_inputs"] == ["weather:Delhi", "water_stress:India"]
    assert "event_id" not in df.columns
    assert int(df["anomaly"].sum()) == int((events["end_idx"] - events["start_idx"]).sum())
    assert len(events) == 5  # the legacy 3 leaks + 2 thermal events, now with an event table


def test_workload_regimes_have_distinct_levels_and_stay_in_range():
    ts = pd.date_range("2025-03-03", periods=7 * 288, freq="5min")
    means = {}
    for regime in dp.KNOWN_REGIMES:
        u = gen.compute_utilisation(ts, regime, gen.make_rng(3, gen.STREAM_WORKLOAD))
        assert u.min() >= 0.0 and u.max() <= 1.0
        means[regime] = u.mean()
    assert means["low"] < means["diurnal"] < means["high"]
    burst = gen.compute_utilisation(ts, "burst", gen.make_rng(3, gen.STREAM_WORKLOAD))
    assert burst.max() > 0.89
    with pytest.raises(ValueError):
        gen.compute_utilisation(ts, "nonsense", gen.make_rng(3, gen.STREAM_WORKLOAD))

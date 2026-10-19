"""Task 17: the report export is bound to one stored run, is reproducible, and refuses anything that is not that run."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from src import run_export as rx


def _results(**over):
    base = {
        "schema": "twingrid-results/1",
        "experiment": "baselines",
        "title": "Synthetic fixture run",
        "seeds": [7, 8],
        "summary": {"mean_reward": -1.5},
        "tables": {"t": {"title": "A table", "columns": ["x", "y"], "rows": [["a", 1.5]]}},
        "figures": {},
        "notes": ["fixture note"],
        "carbon": {"is_real": False, "flat_curve": True},
        "claims": {"allowed": "fixture allowed", "not_allowed": "fixture not allowed"},
        "scenario_sets": {"test": {"id": "tt", "n": 2}, "validation": {"id": "vv", "n": 1}},
        "per_scenario_test": {
            "rule": [
                {
                    "outlet_violation_steps": 1,
                    "inlet_over_max_steps": 0,
                    "inlet_under_min_steps": 2,
                    "pue_over_max_steps": 0,
                },
                {
                    "outlet_violation_steps": 2,
                    "inlet_over_max_steps": 0,
                    "inlet_under_min_steps": 0,
                    "pue_over_max_steps": 3,
                },
            ],
            "old": [{"outlet_violation_steps": 0, "inlet_over_max_steps": 0, "inlet_under_min_steps": 0}] * 2,
        },
    }
    base.update(over)
    return base


def make_run(root: Path, run_id="run-a", *, results=None, state="completed", dirty=False, newline="\n") -> Path:
    d = root / "reports" / "runs" / run_id
    d.mkdir(parents=True)
    text = json.dumps(results or _results(), indent=2, sort_keys=True) + "\n"
    (d / "results.json").write_bytes(text.replace("\n", newline).encode())
    sha = hashlib.sha256(text.encode()).hexdigest()
    manifest = {
        "run_id": run_id,
        "result_sha256": sha,
        "physics_version": "1",
        "physics_params_hash": None,
        "environment_version": "2",
        "reward_version": "2",
        "code_revision": "abc123",
        "code_revision_source": "git",
        "dirty": dirty,
        "command": ["python", "x"],
        "platform": {"python": "3.12"},
        "config_files": {"configs/a.json": "f" * 64},
        "scenario_set_id": "ss",
    }
    (d / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (d / "status.json").write_text(
        json.dumps({"run_id": run_id, "state": state, "started_at_utc": "S", "finished_at_utc": "F"}), encoding="utf-8"
    )
    return d


def test_markdown_comes_only_from_the_stored_run_and_has_the_required_sections(tmp_path):
    make_run(tmp_path)
    md = rx.export_run(tmp_path, "run-a").decode("utf-8")
    for needle in (
        "# Run report: run-a",
        "## Provenance",
        "## Seeds",
        "7, 8",
        "## Scenario sets",
        "## Claims",
        "## Limitations",
        "physics version | 1",
        "abc123",
        "fixture allowed",
        "A table",
        "## Carbon signal",
    ):
        assert needle in md, needle
    assert "ASSUMED constant" in md and "simulator output" in md.lower()


def test_violations_are_summed_from_the_run_and_missing_counters_are_not_zero(tmp_path):
    make_run(tmp_path)
    md = rx.export_run(tmp_path, "run-a").decode("utf-8")
    assert "| rule | 2 | 3 | 0 | 2 | 3 |" in md
    assert "| old | 2 | 0 | 0 | 0 | not measured |" in md


def test_a_dirty_tree_and_an_experiment_without_violation_counts_are_stated(tmp_path):
    res = _results()
    res.pop("per_scenario_test")
    make_run(tmp_path, dirty=True, results=res)
    md = rx.export_run(tmp_path, "run-a").decode("utf-8")
    assert "DIRTY" in md and "does not report per-scenario hard-constraint counts" in md


def test_export_is_byte_reproducible_and_survives_a_crlf_checkout(tmp_path):
    make_run(tmp_path)
    first = rx.export_run(tmp_path, "run-a")
    assert first == rx.export_run(tmp_path, "run-a")
    other = tmp_path / "crlf"
    other.mkdir()
    make_run(other, newline="\r\n")
    assert rx.export_run(other, "run-a") == first


@pytest.mark.parametrize("bad", ["../run-a", "a/b", "", ".hidden", "run a", "x" * 200])
def test_invalid_run_ids_are_refused(tmp_path, bad):
    make_run(tmp_path)
    with pytest.raises(rx.ExportRefused, match="not a valid run id"):
        rx.export_run(tmp_path, bad)


def test_unknown_run_is_refused(tmp_path):
    make_run(tmp_path)
    with pytest.raises(rx.ExportRefused, match="does not exist"):
        rx.export_run(tmp_path, "run-b")


def test_a_renamed_or_copied_run_directory_is_refused(tmp_path):
    d = make_run(tmp_path)
    shutil.copytree(d, d.parent / "run-b")  # manifest and status still say run-a
    with pytest.raises(rx.ExportRefused, match="run id mismatch"):
        rx.export_run(tmp_path, "run-b")


@pytest.mark.parametrize("state", ["running", "failed", "queued"])
def test_a_run_that_is_not_completed_is_refused(tmp_path, state):
    make_run(tmp_path, state=state)
    with pytest.raises(rx.ExportRefused, match="not 'completed'"):
        rx.export_run(tmp_path, "run-a")


def test_results_edited_after_the_run_are_refused(tmp_path):
    d = make_run(tmp_path)
    (d / "results.json").write_text(
        (d / "results.json").read_text(encoding="utf-8").replace("-1.5", "-9.9"), encoding="utf-8"
    )
    with pytest.raises(rx.ExportRefused, match="changed after the run"):
        rx.export_run(tmp_path, "run-a")


def test_the_caller_can_bind_the_export_to_the_result_it_selected(tmp_path):
    make_run(tmp_path)
    sha = json.loads((tmp_path / "reports/runs/run-a/manifest.json").read_text(encoding="utf-8"))["result_sha256"]
    assert rx.export_run(tmp_path, "run-a", expected_result_sha256=sha)
    with pytest.raises(rx.ExportRefused, match="not the stored result"):
        rx.export_run(tmp_path, "run-a", expected_result_sha256="0" * 64)


def test_cli_writes_on_success_and_writes_nothing_on_refusal(tmp_path):
    make_run(tmp_path)
    out = tmp_path / "r.md"
    assert rx.main(["run-a", "--root", str(tmp_path), "--out", str(out)]) == 0 and out.read_text(
        encoding="utf-8"
    ).startswith("# Run report")
    bad = tmp_path / "bad.md"
    assert rx.main(["run-b", "--root", str(tmp_path), "--out", str(bad)]) == 2 and not bad.exists()


def test_pdf_is_built_from_the_same_blocks(tmp_path):
    make_run(tmp_path)
    data = rx.export_run(tmp_path, "run-a", fmt="pdf")
    assert data.startswith(b"%PDF") and len(data) > 1000
    assert data == rx.export_run(tmp_path, "run-a", fmt="pdf")  # invariant=True: no timestamps
    with pytest.raises(rx.ExportRefused, match="unknown format"):
        rx.export_run(tmp_path, "run-a", fmt="docx")

"""T22 -- data/external/REGISTER.json and scripts/check_register.py.

Positive tests run the checker on the real repository; every rule also has a negative test that mutates a copy of the
register (or builds a tiny throw-away repository) and expects that rule, and only that rule, to fire.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
REGISTER_PATH = ROOT / "data" / "external" / "REGISTER.json"
CHECKER_PATH = ROOT / "scripts" / "check_register.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses with postponed annotations look the module up here
    spec.loader.exec_module(module)
    return module


cr = _load("t22_check_register", CHECKER_PATH)
pv = _load("t22_provenance", ROOT / "scripts" / "provenance.py")


@pytest.fixture(scope="module")
def register() -> dict:
    return json.loads(REGISTER_PATH.read_text(encoding="utf-8"))


def fresh(register: dict) -> dict:
    return copy.deepcopy(register)


def entry_of(register: dict, entry_id: str) -> dict:
    return next(e for e in register["datasets"] if e["id"] == entry_id)


def rules(findings) -> set[str]:
    return {f.rule for f in findings}


# --------------------------------------------------------------------------- the real register is valid


def test_real_register_passes_every_rule():
    assert [str(f) for f in cr.check_register()] == []


def test_checker_cli_exits_zero_on_the_real_repository():
    done = subprocess.run([sys.executable, str(CHECKER_PATH)], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "OK (15 datasets)" in done.stdout


def test_all_fourteen_manifests_are_registered(register):
    manifests = sorted(p.parent.name for p in (ROOT / "data" / "external").glob("*/provenance.json"))
    assert len(manifests) == 14
    registered = sorted(e["manifest"].split("/")[-2] for e in register["datasets"] if e["manifest"])
    assert registered == manifests
    assert len({e["id"] for e in register["datasets"]}) == len(register["datasets"]) == 15


def test_the_fifteenth_entry_is_the_api_dataset_that_code_references(register):
    nsrdb = entry_of(register, "nrel-nsrdb-psm3")
    assert nsrdb["manifest"] is None and nsrdb["retrieved_at"] is None
    assert "src/ingestion/solar_nsrdb.py" in nsrdb["used_by"]
    assert "solar_nsrdb.csv" in " ".join(nsrdb["prohibited_claims"])


def test_no_licence_is_verified_and_nothing_is_redistributable(register):
    assert {e["license_status"] for e in register["datasets"]} == {"unverified"}
    assert {e["redistribution"] for e in register["datasets"]} == {"not_permitted"}
    for e in register["datasets"]:
        assert e["terms_url"] is None and e["terms_retrieved_at"] is None and e["terms_sha256"] is None


def test_rp_1043_is_unverified_with_prohibited_claims_listed(register):
    e = entry_of(register, "ashrae-rp-1043")
    assert e["license_status"] == "unverified" and e["used_by"] == [] and e["source_url"] is None
    assert "reference_only" in e["supported_claims"]
    prohibited = " ".join(e["prohibited_claims"]).lower()
    assert "calibrates per-mode cooling cop" in prohibited
    assert "validates anomaly-detector fault signatures" in prohibited


def test_unsupported_claims_are_gone_from_supported_claims_and_manifests(register):
    banned = ("calibrates per-mode cooling cop", "real utilisation driver", "real server_utilisation driver")
    for e in register["datasets"]:
        supported = " ".join(e["supported_claims"]).lower()
        assert not any(b in supported for b in banned), e["id"]
    for path in (ROOT / "data" / "external").glob("*/provenance.json"):
        meta = json.loads(path.read_text(encoding="utf-8"))["metadata"]
        text = json.dumps(meta).lower()
        assert "calibrates per-mode cooling cop" not in text and "real server_utilisation driver" not in text, path
        assert meta["license_status"] == "unverified"
        assert meta["license"].startswith("UNVERIFIED")


def test_consumed_datasets_are_exactly_those_with_a_reader_in_the_code(register):
    consumed = {e["id"] for e in register["datasets"] if e["used_by"]}
    assert consumed == {
        "electricity-maps-coverage-2026-09-06",
        "open-meteo-hourly-2025",
        "wri-aqueduct-4-0-water-risk-data",
        "nasa-cmapss",
        "numenta-nab",
        "nrel-nsrdb-psm3",
    }
    for e in register["datasets"]:
        if not e["used_by"]:
            assert "reference_only" in e["supported_claims"], e["id"]


def test_electricity_maps_catalogue_is_not_claimed_as_carbon_intensity(register):
    e = entry_of(register, "electricity-maps-coverage-2026-09-06")
    assert not any("intensity" in v for v in e["variables"])
    assert any("no intensity column" in c for c in e["prohibited_claims"])


def test_there_is_no_frontier_or_hpc_entry(register):
    for e in register["datasets"]:
        assert not cr.FORBIDDEN_ENTRY.search(" ".join(str(e.get(k)) for k in ("id", "source_name", "source_url")))


def test_manifest_metadata_matches_the_known_sources_table():
    for path in sorted((ROOT / "data" / "external").glob("*/provenance.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        assert manifest["metadata"] == pv.match_known_source(path.parent.name), path.parent.name


def test_manifest_scan_blocks_were_not_touched():
    """T22 may change claim/licence fields only: the scan (file list, hashes) must still be there."""
    for path in (ROOT / "data" / "external").glob("*/provenance.json"):
        scan = json.loads(path.read_text(encoding="utf-8"))["scan"]
        assert scan["file_count"] == len(scan["files"]) >= 1


def test_data_licenses_doc_covers_every_entry(register):
    doc = (ROOT / "docs" / "DATA_LICENSES.md").read_text(encoding="utf-8")
    for e in register["datasets"]:
        assert f"`{e['id']}`" in doc, e["id"]
    assert "Get-FileHash" in doc and "No licence is verified" in doc


def test_ci_runs_the_checker_exactly_once_in_the_lint_job():
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert ci.count("python scripts/check_register.py") == 1
    lint = ci.split("\n  lint:\n", 1)[1].split("\n  types:\n", 1)[0]
    assert "python scripts/check_register.py" in lint


def test_checker_uses_only_the_standard_library():
    import ast

    tree = ast.parse(CHECKER_PATH.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= set(sys.stdlib_module_names), imported - set(sys.stdlib_module_names)


# --------------------------------------------------------------------------- negative: schema


def test_schema_missing_field_is_rejected(register):
    r = fresh(register)
    del r["datasets"][0]["terms_sha256"]
    assert rules(cr.check_register(ROOT, r, scan_code=False)) == {"schema"}


@pytest.mark.parametrize(
    "field,value",
    [("license_status", "open"), ("redistribution", "maybe"), ("used_by", "src/x.py"), ("variables", [1]), ("id", "")],
)
def test_schema_bad_value_is_rejected(register, field, value):
    r = fresh(register)
    r["datasets"][0][field] = value
    assert "schema" in rules(cr.check_register(ROOT, r, scan_code=False))


def test_schema_duplicate_id_is_rejected(register):
    r = fresh(register)
    r["datasets"][1]["id"] = r["datasets"][0]["id"]
    assert any("duplicate id" in f.message for f in cr.check_register(ROOT, r, scan_code=False))


def test_schema_empty_claim_boundary_is_rejected(register):
    r = fresh(register)
    r["datasets"][0]["prohibited_claims"] = []
    assert "schema" in rules(cr.check_register(ROOT, r, scan_code=False))


def test_schema_register_must_be_an_object_with_datasets():
    assert rules(cr.check_register(ROOT, [], scan_code=False)) == {"schema"}
    assert rules(cr.check_register(ROOT, {"datasets": "x"}, scan_code=False)) == {"schema"}


# --------------------------------------------------------------------------- negative: manifests


def test_manifest_present_on_disk_but_unregistered_fails(register):
    r = fresh(register)
    removed = r["datasets"].pop(next(i for i, e in enumerate(r["datasets"]) if e["id"] == "ashrae-rp-1043"))
    findings = cr.check_register(ROOT, r, scan_code=False)
    assert rules(findings) == {"manifest"}
    assert removed["manifest"] in " ".join(f.message for f in findings)


def test_manifest_path_that_does_not_exist_fails(register):
    r = fresh(register)
    r["datasets"][0]["manifest"] = "data/external/nope/provenance.json"
    assert "manifest" in rules(cr.check_register(ROOT, r, scan_code=False))


def test_two_entries_cannot_claim_one_manifest(register):
    r = fresh(register)
    r["datasets"][1]["manifest"] = r["datasets"][0]["manifest"]
    assert any("both claim" in f.message for f in cr.check_register(ROOT, r, scan_code=False))


# --------------------------------------------------------------------------- negative: used_by


@pytest.mark.parametrize("bad", ["src/does_not_exist.py", "../outside.py", "/etc/passwd", "src\\data_generator.py"])
def test_used_by_must_name_an_existing_repository_relative_path(register, bad):
    r = fresh(register)
    entry_of(r, "numenta-nab")["used_by"].append(bad)
    assert rules(cr.check_register(ROOT, r, scan_code=False)) == {"used_by"}


def test_used_by_may_name_a_directory(register):
    r = fresh(register)
    entry_of(r, "numenta-nab")["used_by"].append("src/ingestion")
    assert cr.check_register(ROOT, r, scan_code=False) == []


# --------------------------------------------------------------------------- negative: claim verbs


@pytest.mark.parametrize(
    "claim",
    [
        "Calibrates per-mode cooling COP",
        "Validates the anomaly detector",
        "Drives the carbon term",
        "It is calibrated against chiller data",
        "Results validated by this set",
        "Driving the utilisation curve",
    ],
)
def test_claim_verb_with_empty_used_by_fails(register, claim):
    r = fresh(register)
    entry_of(r, "ashrae-rp-1043")["supported_claims"].append(claim)
    assert rules(cr.check_register(ROOT, r, scan_code=False)) == {"claim_verb"}


def test_claim_verb_is_allowed_when_a_code_path_exists(register):
    r = fresh(register)
    entry_of(r, "numenta-nab")["supported_claims"].append("Validates a univariate autoencoder offline")
    assert cr.check_register(ROOT, r, scan_code=False) == []


def test_prohibited_claims_may_use_the_verbs(register):
    # the RP-1043 prohibited list says "Calibrates per-mode cooling COP"; only SUPPORTED claims are policed
    assert any("Calibrates" in c for c in entry_of(register, "ashrae-rp-1043")["prohibited_claims"])
    assert cr.check_register(ROOT, register, scan_code=False) == []


def test_reference_only_with_a_code_path_fails(register):
    r = fresh(register)
    entry_of(r, "numenta-nab")["supported_claims"].append("reference_only")
    assert rules(cr.check_register(ROOT, r, scan_code=False)) == {"reference_only"}


def test_code_use_without_a_source_url_fails(register):
    r = fresh(register)
    entry_of(r, "numenta-nab")["source_url"] = None
    assert rules(cr.check_register(ROOT, r, scan_code=False)) == {"source"}


# --------------------------------------------------------------------------- negative: licence


def test_unverified_licence_with_permitted_redistribution_fails(register):
    r = fresh(register)
    entry_of(r, "open-meteo-hourly-2025")["redistribution"] = "permitted"
    assert rules(cr.check_register(ROOT, r, scan_code=False)) == {"license"}


def test_restricted_licence_with_permitted_redistribution_fails(register):
    r = fresh(register)
    e = entry_of(r, "open-meteo-hourly-2025")
    e["license_status"], e["redistribution"] = "restricted", "permitted"
    assert rules(cr.check_register(ROOT, r, scan_code=False)) == {"license"}


def test_unknown_redistribution_is_treated_as_not_permitted(register):
    assert cr.effective_redistribution({"redistribution": "unknown"}) == "not_permitted"
    assert cr.effective_redistribution({}) == "not_permitted"
    r = fresh(register)
    entry_of(r, "open-meteo-hourly-2025")["redistribution"] = "unknown"
    found = cr.check_register(ROOT, r, scan_code=False)
    assert "license" not in rules(found) and "schema" in rules(found)  # accepted semantically, flagged as bad data


def test_verified_licence_needs_recorded_evidence(register):
    r = fresh(register)
    e = entry_of(r, "open-meteo-hourly-2025")
    e["license_status"] = "verified"
    assert rules(cr.check_register(ROOT, r, scan_code=False)) == {"license_evidence"}
    e.update(
        terms_url="https://example.org/terms", terms_retrieved_at="2026-10-04T10:00:00+05:30", terms_sha256="AB" * 32
    )
    assert rules(cr.check_register(ROOT, r, scan_code=False)) == {"license_evidence"}  # upper case is not accepted
    e["terms_sha256"] = "ab" * 32
    assert cr.check_register(ROOT, r, scan_code=False) == []


def test_verified_licence_may_be_redistributable(register):
    r = fresh(register)
    e = entry_of(r, "open-meteo-hourly-2025")
    e.update(license_status="verified", redistribution="permitted", terms_url="https://example.org/terms")
    e.update(terms_retrieved_at="2026-10-04T10:00:00+05:30", terms_sha256="0f" * 32)
    assert cr.check_register(ROOT, r, scan_code=False) == []


# --------------------------------------------------------------------------- negative: Frontier / HPC


@pytest.mark.parametrize("name", ["Frontier exascale telemetry", "OLCF Frontier jobs", "Some HPC dataset"])
def test_frontier_or_hpc_entry_is_refused(register, name):
    r = fresh(register)
    extra = fresh(entry_of(r, "numenta-nab"))
    extra.update(id="x-" + str(abs(hash(name)) % 1000), source_name=name, manifest=None, used_by=[])
    extra["supported_claims"] = ["reference_only"]
    r["datasets"].append(extra)
    assert "frontier" in rules(cr.check_register(ROOT, r, scan_code=False))


# --------------------------------------------------------------------------- code scan, on throw-away repositories


def make_repo(tmp_path: Path, register: dict, files: dict[str, str]) -> Path:
    (tmp_path / "data" / "external").mkdir(parents=True)
    (tmp_path / "data" / "external" / "REGISTER.json").write_text(json.dumps(register), encoding="utf-8")
    for entry in register["datasets"]:
        if entry["manifest"]:
            manifest = tmp_path / entry["manifest"]
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text("{}", encoding="utf-8")
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


@pytest.fixture
def tiny(register):
    base = entry_of(register, "numenta-nab")
    base = fresh(base)
    base.update(used_by=[], source_url="https://example.org/nab", supported_claims=["reference_only"])
    base["manifest"] = "data/external/KnownSet/provenance.json"
    reg = {"schema_version": 1, "datasets": [base]}
    return reg


def codes(findings) -> set[str]:
    return {f.rule for f in findings}


def test_registered_dataset_reference_passes(tmp_path, tiny):
    repo = make_repo(tmp_path, tiny, {"src/a.py": 'P = "realData/KnownSet/file.csv"\n'})
    assert cr.check_register(repo) == []


@pytest.mark.parametrize(
    "source",
    [
        'P = "realData/NewSet/file.csv"\n',
        'P = ROOT / "realData" / "NewSet" / "f.csv"\n',
        'P = real_data_dir / "NewSet"\n',
        'P = REAL_DATA_DIR / "NewSet"\n',
        '"""Reads realData/NewSet/x.csv"""\n',
        "# see realData/NewSet\n",
    ],
)
def test_unregistered_dataset_reference_fails(tmp_path, tiny, source):
    repo = make_repo(tmp_path, tiny, {"src/a.py": source})
    found = cr.check_register(repo)
    assert codes(found) == {"unregistered"} and "NewSet" in found[0].message and found[0].message.startswith("src/a.py")


@pytest.mark.parametrize(
    "text", ['"realData/<name>/x"', 'glob("realData/*")', '"realData/{source}/p"', '"realData/ is missing"']
)
def test_placeholders_are_not_dataset_references(tmp_path, tiny, text):
    repo = make_repo(tmp_path, tiny, {"src/a.py": f"P = {text}\n"})
    assert cr.check_register(repo) == []


def test_remote_dataset_without_an_entry_fails(tmp_path, tiny):
    repo = make_repo(tmp_path, tiny, {"src/solar.py": 'URL = "https://developer.nrel.gov/api/nsrdb/v2/x"\n'})
    found = cr.check_register(repo)
    assert codes(found) == {"unregistered"} and "nrel-nsrdb-psm3" in found[0].message


def test_remote_dataset_with_an_entry_passes(tmp_path, tiny, register):
    tiny["datasets"].append(fresh(entry_of(register, "nrel-nsrdb-psm3")))
    tiny["datasets"][-1]["used_by"] = []
    tiny["datasets"][-1]["supported_claims"] = ["reference_only"]
    repo = make_repo(tmp_path, tiny, {"src/solar.py": 'URL = "https://developer.nrel.gov/api/nsrdb/v2/x"\n'})
    assert cr.check_register(repo) == []


@pytest.mark.parametrize(
    "text",
    [
        "# train on Frontier telemetry\n",
        "DATA = 'OLCF/frontier_jobs.csv'\n",
        "# Oak Ridge exascale logs\n",
        "x = load('hpc_trace')\n",
    ],
)
def test_code_referencing_frontier_or_hpc_data_fails(tmp_path, tiny, text):
    repo = make_repo(tmp_path, tiny, {"src/a.py": text})
    assert codes(cr.check_register(repo)) == {"frontier"}


@pytest.mark.parametrize(
    "text",
    [
        "# Pareto frontier of cost vs energy\n",
        "# HPC Degradation fault mode (C-MAPSS high-pressure compressor)\n",
        "efficient frontier = 1\n",
    ],
)
def test_pareto_frontier_and_compressor_hpc_are_not_dataset_references(tmp_path, tiny, text):
    repo = make_repo(tmp_path, tiny, {"src/a.py": text})
    assert cr.check_register(repo) == []


def test_tests_docs_and_data_directories_are_not_scanned(tmp_path, tiny):
    repo = make_repo(
        tmp_path,
        tiny,
        {
            "tests/t.py": 'P = "realData/Sneaky/x"\n',
            "docs/x.py": "# Frontier\n",
            "data/cleaned/x.py": "# Frontier\n",
            "twin-stream-insight-main/x.py": "# Frontier\n",
        },
    )
    assert cr.check_register(repo) == []


def test_cli_exits_one_and_prints_the_rule_on_a_bad_repository(tmp_path, tiny):
    repo = make_repo(
        tmp_path,
        tiny,
        {"src/a.py": '"realData/NewSet/x"\n', "scripts/check_register.py": CHECKER_PATH.read_text(encoding="utf-8")},
    )
    done = subprocess.run(
        [sys.executable, "scripts/check_register.py"], cwd=repo, capture_output=True, text=True, timeout=60
    )
    assert done.returncode == 1
    assert re.search(r"ERROR \[unregistered\] src/a\.py references dataset 'realData/NewSet'", done.stdout)

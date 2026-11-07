"""Source -> clean panel build, verification and rerun comparison (Task 14)."""

from __future__ import annotations

import json
import platform
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

from ..adapter.reader import AdapterReader
from ..adapter.source import DEFAULT_MANIFEST, discover_all
from ..cleaning.catalogue import REASON_BLANK, REASON_TIE
from ..cleaning.config import CleanConfig
from ..cleaning.flags import apply_flags
from ..cleaning.l1 import code_sha256 as cleaning_code_sha256
from ..cleaning.l1 import verify_l1, write_l1
from ..cleaning.ledger import disposition_counts, ledger_summary, reconcile
from ..cleaning.reference import TASK6, compare_ledger
from ..cleaning.resolve import clean_file
from ..cleaning.tier1 import POWER_COLUMNS, TIER1_COLUMNS, column_slug
from ..contract.telemetry_contract import CONTRACT_VERSION, PROTOCOL_SHA256_V5
from ..evaluation.guard import RawDataGuard
from ..mapping import load_mapping, require_approved
from ..mapping.derivations import REGISTRY_PATH
from ..mapping.loader import MAPPING_PATH, mapping_file_sha256
from ..protocol.lock import verify as verify_lock
from ..protocol.protocol import load_protocol, protocol_sha256
from .channels import FAMILY, channel_table, check_tier1_against_mapping
from .derive import derive_sum, input_columns
from .errors import PanelError
from .hashing import file_sha256, lf_file_sha256, package_sha256, tree_sha256

PANEL_FORMAT = "twingrid.danish_aau.panel/1"
DERIVED_NAME = "derived.rack_power_total_1_6"
DERIVED_FILE = "derived/derived_rack_power_total_1_6.tsv"
CHANNELS_FILE = "channels.json"
MANIFEST_FILE = "panel_manifest.json"
ENV_FILE = "run_environment.json"  # machine-specific; excluded from every hash and from byte comparison
PKG = Path(__file__).resolve().parent
DANISH = PKG.parent

SOURCE = {
    "title": "A Danish high-resolution dataset for a server room: airflow, air temperature and power measurements",
    "authors": ["Melgaard, S. P.", "Juul, T.", "Nielsen, J. E.", "Jensen, R. L."],
    "publisher": "Aalborg University",
    "version": "v5",
    "doi": "10.5281/zenodo.21262042",
    "licence": "CC BY 4.0",
    "modifications": (
        "Cell values rounded half-even to the source resolution (0.01 degC, 0.1 W); cells in repeated-timestamp groups "
        "whose values conflict are set missing (never imputed); no resampling, interpolation, unit change or timezone "
        "conversion; only 40 of the 51 temperature/power columns are carried; the derived power total is a separate series."
    ),
}
VISIBILITY = {
    "status": "local_only",
    "redistribution": "not_approved",
    "note": "Do not commit, publish or serve these files without a recorded owner decision on redistribution.",
}
REAL_FILE_REFERENCE = {  # owner-run Task 12 real-file numbers (TASK_12_REAL_RUN_RESULTS.md); comparison only, never a rule
    "raw_rows": 1_371_363,
    "unique_seconds": 1_370_788,
    "retained": 1_370_289,
    "exact_duplicate": 0,
    "conflict_cell_missing": 1_074,
    "stored_cells": 54_831_520,
    "tier1_conflict_missing_cells": 7_691,
    "tier1_conflict_missing_rack_probes": 6_246,
    "tier1_conflict_missing_power": 1_445,
    "blank_cells": 0,
    "flagged_cells": 0,
    "observed_cells": 54_823_829,
}


def real_file_reference_differences(counts: dict) -> list[str]:
    return [
        f"{k}: observed {counts.get(k)!r} vs Task 12 real run {v!r}"
        for k, v in REAL_FILE_REFERENCE.items()
        if counts.get(k) != v
    ]


def _is_default(config: CleanConfig) -> bool:
    return not config.range_limits and config.flatline_min_run is None


def _write_tsv(path: Path, df: pd.DataFrame) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, sep="\t", index=False, lineterminator="\n", na_rep="", encoding="utf-8")
    sha, size = file_sha256(path)
    return {"sha256": sha, "bytes": size, "rows": len(df)}


def _write_json(path: Path, obj: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(obj, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return file_sha256(path)[0]


def _check_dirs(raw: Path, out: Path) -> None:
    if out == raw or raw in out.parents or out in raw.parents:
        raise PanelError("the output directory must be separate from the raw directory (no nesting either way)")
    if out.exists() and any(out.iterdir()):
        raise PanelError(
            f"output directory {out.name!r} is not empty; choose a new one (no stale files are ever mixed in)"
        )


def _panel_sha(parts: dict[str, str]) -> str:
    return tree_sha256(parts)


def build_panel(
    raw_dir: Path,
    out_dir: Path,
    *,
    manifest_path: Path | None = DEFAULT_MANIFEST,
    config: CleanConfig | None = None,
    progress: Callable[[str], None] | None = None,
    chunksize: int | None = None,
) -> dict:
    """Build the panel in ``out_dir`` (new or empty). Returns the panel manifest dict. Raises PanelError rather than guess."""
    say = progress or (lambda m: None)
    config = config or CleanConfig()
    raw, out = Path(raw_dir).resolve(), Path(out_dir).resolve()
    _check_dirs(raw, out)

    protocol = load_protocol()
    lock = verify_lock()
    proto_sha = protocol_sha256()
    if proto_sha != PROTOCOL_SHA256_V5 or lock["sha256_lf_normalised"] != proto_sha:
        raise PanelError("the protocol is not the locked v1.0.0 file")
    registry = load_mapping()  # validates; an invalid mapping never loads
    mf = registry.doc["mapping_file"]
    if mf["status"] != "approved" or mf["protocol_sha256"] != proto_sha or mf["dataset_id"] != "danish-aau-v5":
        raise PanelError("the mapping is not the approved danish-aau-v5 mapping for the locked protocol")
    defn = require_approved(DERIVED_NAME)
    mapping_sha = mapping_file_sha256(MAPPING_PATH)
    deriv_sha = lf_file_sha256(REGISTRY_PATH)

    with RawDataGuard(raw):
        sources = discover_all(raw, [FAMILY], manifest_path=manifest_path)
        src = sources[FAMILY]
        say("hashing the raw file")
        raw_sha, raw_bytes = file_sha256(src.source.path)
        real = src.file_sha256 is not None
        if real and src.file_sha256 != raw_sha:
            raise PanelError("the raw file's SHA-256 differs from the dataset manifest")
        filename = src.spec.filename
        entities = check_tier1_against_mapping(registry, protocol, filename)
        say("cleaning")
        reader = AdapterReader(src, chunksize=chunksize) if chunksize else AdapterReader(src)
        res = apply_flags(clean_file(reader, protocol, progress=progress), protocol, config)
    problems = reconcile(res)
    if problems:
        raise PanelError("the ledger does not reconcile: " + "; ".join(problems))
    input_columns(defn, registry, res)  # fail early if the derivation does not fit

    dcounts = disposition_counts(res)
    k = len(TIER1_COLUMNS)
    tie_by_col = {
        c: int(((~res.valid[:, j]) & (res.reason[:, j] == REASON_TIE)).sum()) for j, c in enumerate(res.columns)
    }
    counts = {
        "raw_rows": res.n_rows,
        "unique_seconds": res.n_seconds,
        "retained": dcounts["retained"],
        "exact_duplicate": dcounts["exact_duplicate"],
        "conflict_cell_missing": dcounts["conflict_cell_missing"],
        "stored_cells": k * res.n_seconds,
        "observed_cells": int(res.valid.sum()),
        "tier1_conflict_missing_cells": sum(tie_by_col.values()),
        "tier1_conflict_missing_rack_probes": sum(v for c, v in tie_by_col.items() if c not in POWER_COLUMNS),
        "tier1_conflict_missing_power": sum(tie_by_col[c] for c in POWER_COLUMNS),
        "blank_cells": int(((~res.valid) & (res.reason == REASON_BLANK)).sum()),
        "flagged_cells": int((res.valid & (res.flag > 0)).sum()),
    }
    ref: dict
    if real and _is_default(config):
        diffs = real_file_reference_differences(counts)
        diffs += compare_ledger("temperature_power", res.stats, dcounts, res.n_seconds)
        if diffs:
            raise PanelError("real-file reference mismatch (Task 4/6/12): " + "; ".join(diffs))
        ref = {"status": "matches_task12_real_run", "differences": []}
    else:
        ref = {
            "status": "not_applicable",
            "differences": [],
            "reason": "not the manifest-verified real file or a non-default configuration",
        }
    if real and "temperature_power" in TASK6 and not _is_default(config):
        ref["note"] = "non-default cleaning configuration: flags change quality and observed counts"

    say("writing L1")
    l1 = write_l1(
        res,
        out / "l1",
        dataset_id=mf["dataset_id"],
        protocol_sha256=proto_sha,
        source_file_sha256=raw_sha,
        contract_version=CONTRACT_VERSION,
    )
    l1_manifest_sha, _ = file_sha256(out / "l1" / "l1_manifest.json")

    say("deriving")
    ddf = derive_sum(res, registry, defn)
    dmeta = _write_tsv(out / DERIVED_FILE, ddf)
    n_def = int((ddf["state"] == "observed").sum())
    derived_summary = {
        "derived_name": DERIVED_NAME,
        "provenance": "derived",
        "storage_class": "derived_series",
        "file": DERIVED_FILE,
        **dmeta,
        "defined_seconds": n_def,
        "undefined_seconds": res.n_seconds - n_def,
        "undefined_reason_code": "inputs_not_all_observed",
        "formula_id": defn["formula_id"],
        "formula_text": defn["formula_text"],
        "inputs": list(defn["inputs"]),
        "input_l1_files": [
            f"l1/observations/{column_slug(registry.sensor(s)['source_column'])}.tsv" for s in defn["inputs"]
        ],
        "output_scope": defn["output_scope"],
        "output_member_source_rack_ids": list(defn["output_member_source_rack_ids"]),
        "method_approval_ref": defn["method_approval_ref"],
        "derivations_file_sha256_lf": deriv_sha,
        "split_per_rack": False,
    }

    channels = channel_table(res, entities, l1["files"], mapping_sha)
    channels_doc = {
        "panel_format": PANEL_FORMAT,
        "dataset_id": mf["dataset_id"],
        "measured_channels": channels,
        "derived_channels": [derived_summary],
    }
    channels_sha = _write_json(out / CHANNELS_FILE, channels_doc)

    cfg = {
        "range_limits": {k_: list(v) for k_, v in sorted(config.range_limits.items())},
        "flatline_min_run": config.flatline_min_run,
        "flatline_gap_step": config.flatline_gap_step,
    }
    code = {
        "cleaning_sha256": cleaning_code_sha256(),
        "panel_sha256": package_sha256(PKG),
        "mapping_sha256": package_sha256(DANISH / "mapping"),
        "adapter_sha256": package_sha256(DANISH / "adapter"),
        "protocol_sha256": package_sha256(DANISH / "protocol"),
    }
    parts = {
        "l1_sha256": l1["l1_sha256"],
        "l1_manifest": l1_manifest_sha,
        "derived": dmeta["sha256"],
        "channels": channels_sha,
    }
    manifest = {
        "panel_format": PANEL_FORMAT,
        "dataset_id": mf["dataset_id"],
        "contract_version": CONTRACT_VERSION,
        "mapping_version": registry.mapping_version,
        "visibility": VISIBILITY,
        "source": SOURCE,
        "raw": {"file": filename, "sha256": raw_sha, "bytes": raw_bytes, "verified_against_dataset_manifest": real},
        "inputs": {
            "protocol_sha256_lf": proto_sha,
            "mapping_file_sha256_lf": mapping_sha,
            "derivations_file_sha256_lf": deriv_sha,
            "cleaning_config": cfg,
            "tier1_columns": list(TIER1_COLUMNS),
        },
        "code": code,
        "time": {
            "basis": "source_text_undeclared_tz",
            "window_first_text": str(res.ts_text[0]),
            "window_last_text": str(res.ts_text[-1]),
        },
        "counts": counts,
        "ledger": ledger_summary(res),
        "reference_check": ref,
        "outputs": {
            "l1_dir": "l1",
            "l1_sha256": l1["l1_sha256"],
            "l1_manifest_sha256": l1_manifest_sha,
            "l1_result_digest": l1["result_digest"],
            "derived": {"file": DERIVED_FILE, **dmeta, "defined_seconds": n_def},
            "channels_file": CHANNELS_FILE,
            "channels_sha256": channels_sha,
        },
        "panel_sha256": _panel_sha(parts),
        "no_simulated_or_synthetic_values": True,
    }
    _write_json(out / MANIFEST_FILE, manifest)
    (out / ENV_FILE).write_bytes(
        (
            json.dumps(
                {
                    "python": sys.version,
                    "platform": platform.platform(),
                    "numpy": np.__version__,
                    "pandas": pd.__version__,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode()
    )
    say("done")
    return manifest


def _tree(root: Path) -> dict[str, str]:
    out = {}
    for p in sorted(Path(root).rglob("*")):
        if p.is_file() and p.name != ENV_FILE:
            out[p.relative_to(root).as_posix()] = file_sha256(p)[0]
    return out


def compare_trees(a: Path, b: Path) -> list[str]:
    """Relative paths that differ (or exist on one side only). Empty = byte-identical (environment file excluded)."""
    ta, tb = _tree(a), _tree(b)
    return sorted(p for p in set(ta) | set(tb) if ta.get(p) != tb.get(p))


def rerun_check(raw_dir: Path, out_dir: Path, **kw) -> dict:
    """Build twice (second into a sibling directory) and compare every output byte. Removes the second tree on success."""
    out = Path(out_dir).resolve()
    again = out.with_name(out.name + "_rerun")
    first = build_panel(raw_dir, out, **kw)
    second = build_panel(raw_dir, again, **kw)
    diffs = compare_trees(out, again)
    if not diffs:
        shutil.rmtree(again)
    return {
        "identical": not diffs,
        "differences": diffs,
        "panel_sha256": first["panel_sha256"],
        "second_panel_sha256": second["panel_sha256"],
    }


def _read(path: Path, cols=None) -> pd.DataFrame:
    return pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False, usecols=cols)


def verify_panel(out_dir: Path, *, deep: bool = True) -> list[str]:
    """Recompute hashes and re-derive the derived series from the L1 files. Empty list = verified.

    deep=True also re-reads every L1 observation file and the ledger and checks the counts in the manifest.
    """
    out = Path(out_dir)
    problems: list[str] = []
    try:
        m = json.loads((out / MANIFEST_FILE).read_text(encoding="utf-8"))
        ch = json.loads((out / CHANNELS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [f"cannot read manifest or channels: {e}"]
    problems += [f"l1: {p}" for p in verify_l1(out / "l1")]
    l1m = json.loads((out / "l1" / "l1_manifest.json").read_text(encoding="utf-8"))
    got = {
        "l1_sha256": l1m["l1_sha256"],
        "l1_manifest": file_sha256(out / "l1" / "l1_manifest.json")[0],
        "derived": file_sha256(out / DERIVED_FILE)[0],
        "channels": file_sha256(out / CHANNELS_FILE)[0],
    }
    if _panel_sha(got) != m["panel_sha256"]:
        problems.append("panel_sha256 does not match the recomputed file hashes")
    if l1m["cleaning_code_sha256"] != m["code"]["cleaning_sha256"]:
        problems.append("cleaning code hash differs between the L1 manifest and the panel manifest")
    if l1m["protocol_sha256"] != m["inputs"]["protocol_sha256_lf"] or l1m["source_file_sha256"] != m["raw"]["sha256"]:
        problems.append("protocol or raw-file hash differs between the L1 manifest and the panel manifest")
    bad_prov = [c["sensor_external_id"] for c in ch["measured_channels"] if c["provenance"] != "measured"]
    bad_prov += [c["derived_name"] for c in ch["derived_channels"] if c["provenance"] != "derived"]
    if bad_prov:
        problems.append(f"unexpected provenance on {bad_prov[:3]}")

    # derived series re-computed from the L1 files (independent of the build arrays)
    d = ch["derived_channels"][0]
    frames = [_read(out / p) for p in d["input_l1_files"]]
    ok = np.ones(len(frames[0]), dtype=bool)
    total = np.zeros(len(frames[0]), dtype=np.int64)
    for f in frames:
        if not f["ts_text"].equals(frames[0]["ts_text"]):
            problems.append("input L1 files disagree on their timestamps")
            return problems
        good = (f["state"] == "observed") & (f["quality"] == "ok")
        ok &= good.to_numpy()
        total += np.where(good, pd.to_numeric(f["value_ticks"].where(good, "0")), 0)
    dv = _read(out / DERIVED_FILE)
    if not dv["ts_text"].equals(frames[0]["ts_text"]):
        problems.append("derived timestamps differ from the L1 timestamps")
    else:
        want = pd.Series(np.where(ok, total.astype(str), ""))
        if not dv["value_ticks"].reset_index(drop=True).equals(want):
            problems.append("derived values differ from the sum recomputed from the L1 files")
        if not (dv["state"].eq("observed").to_numpy() == ok).all():
            problems.append("derived state differs from the recomputed definedness")

    if deep:
        led = _read(out / "l1" / "ledger" / "AAU_temperature_and_power_use.tsv", ["disposition"])
        by = led["disposition"].value_counts().to_dict()
        for name in (
            "retained",
            "exact_duplicate",
            "conflict_cell_missing",
            "flagged",
            "conflict_resolved_by_source_rule",
            "dropped_with_reason",
        ):
            if int(by.get(name, 0)) != int(m["ledger"]["by_disposition"][name]):
                problems.append(f"ledger count for {name} differs from the manifest")
        if len(led) != m["counts"]["raw_rows"] or sum(by.values()) != len(led):
            problems.append("ledger rows differ from raw_rows (dispositions must be one per raw row)")
        for c in ch["measured_channels"]:
            df = _read(out / "l1" / c["l1_file"], ["state", "quality", "reason_code"])
            q = c["quality"]
            if len(df) != q["stored_seconds"]:
                problems.append(f"{c['l1_file']}: row count differs")
            obs = df["state"].eq("observed")
            counts = (
                int(obs.sum()),
                int((obs & df["quality"].eq("flagged")).sum()),
                int(df["reason_code"].eq("conflict_unresolved_tie").sum()),
                int(df["reason_code"].eq("blank_cell").sum()),
            )
            if counts != (
                q["observed"],
                q["observed_flagged"],
                q["missing_conflict_unresolved_tie"],
                q["missing_blank_cell"],
            ):
                problems.append(f"{c['l1_file']}: quality counts differ from channels.json")
        tot = sum(c["quality"]["observed"] for c in ch["measured_channels"])
        if tot != m["counts"]["observed_cells"]:
            problems.append("observed cells in channels.json differ from the manifest")
    return problems

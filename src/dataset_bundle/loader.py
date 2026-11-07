"""Build the read-only dataset bundle from a Task 14 panel (Task 15). Build side: needs numpy and pandas.
It imports nothing from ``research`` (isolation contract: production code never imports the harness); the research-side
checks run through the panel's own command-line tool in a separate process, and the mapping, derivations and protocol are
checked by file hash.

The bundle is a rebuildable index of the versioned L1 file set. Nothing is written to ``telemetry_sample`` or any shared
table. Source conflicts were resolved by Task 12 before this step, so the loader never relies on a database to decide one:
a repeated ``(entity, t_naive_s)`` key, an unknown code or a count that disagrees with the panel is a hard error and the
previous bundle stays in place. The bundle is built in a temporary file, checked, then renamed over the target.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

from . import digest as dg
from . import panel_io as pio
from .errors import BundleError
from .schema import (
    BUNDLE_FORMAT,
    DDL,
    DISPOSITIONS,
    QUALITY_OK,
    REASON_CODES,
    SCHEMA_VERSION,
    STATE_OBSERVED,
)

PKG = Path(__file__).resolve().parent
REPO_ROOT = PKG.parents[1]
PANEL_FORMAT = "twingrid.danish_aau.panel/1"
STREAM_RE = re.compile(r"^import:[a-z0-9.-]{1,57}$")
DERIVED_REASON_ID = 3
# Files the panel was built from, checked by LF-normalised SHA-256 (the convention of every task report).
MAPPING_PATH = REPO_ROOT / "research" / "danish_aau" / "mapping" / "danish_aau_v5_mapping_v1.json"
DERIVATIONS_PATH = REPO_ROOT / "research" / "danish_aau" / "mapping" / "derivations_v1.json"
# Locked protocol v1.0.0 (same value as ``PROTOCOL_SHA256_V5`` in the contract; a test keeps the two equal).
LOCKED_PROTOCOL_SHA256 = "0ff4521697f81c397c81f1af5686284f505956cc239a67b6fe1605adc7b47098"

# Task 12 / Task 14 owner-run real-file numbers; compared only when the panel says it matched the real run.
REAL_REFERENCE = {
    "raw_rows": 1_371_363,
    "unique_seconds": 1_370_788,
    "stored_cells": 54_831_520,
    "observed_cells": 54_823_829,
    "tier1_conflict_missing_cells": 7_691,
    "blank_cells": 0,
    "flagged_cells": 0,
    "derived_defined_seconds": 1_370_290,
    "derived_undefined_seconds": 498,
}


def code_sha256() -> str:
    h = hashlib.sha256()
    for p in sorted(PKG.glob("*.py")):
        h.update(p.name.encode() + b"\x00" + p.read_bytes().replace(b"\r\n", b"\n") + b"\x00")
    return h.hexdigest()


def _peak_rss_mb() -> float | None:
    """Peak resident memory of this process in MB; None when the platform offers no way to read it."""
    try:
        import resource

        kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(kb / 1024, 1)
    except ImportError:
        pass
    try:  # Windows: PeakWorkingSetSize from the standard library's ctypes
        import ctypes
        from ctypes import wintypes

        class _Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ]  # fmt: skip

        counters = _Counters()
        counters.cb = ctypes.sizeof(_Counters)
        k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_Counters), wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return None
        return round(counters.PeakWorkingSetSize / (1024 * 1024), 1)
    except Exception:  # noqa: BLE001 - reported as not measured, never a build failure
        return None


def _lf_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r", b"")).hexdigest()


def _verify_panel_with_tool(panel: Path) -> None:
    """Run the panel's own verifier (hashes and re-derivation) in a separate process; this process imports no research code."""
    cmd = [sys.executable, "-m", "research.danish_aau.panel", "verify", "--out", str(panel), "--shallow"]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [str(REPO_ROOT), os.environ.get("PYTHONPATH")]))}
    try:
        proc = subprocess.run(cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=3600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BundleError(f"cannot run the panel verifier: {exc}") from None
    if proc.returncode != 0:
        tail = (proc.stdout or proc.stderr or "").strip().splitlines()[-6:]
        raise BundleError("the panel does not verify: " + " | ".join(tail))


def _read_json(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BundleError(f"cannot read {Path(path).name}: {exc}") from None


def _check_locations(panel: Path, out: Path, allow_any_location: bool) -> None:
    if out == panel or panel in out.parents or out in panel.parents:
        raise BundleError("the bundle file must be separate from the panel directory (no nesting either way)")
    if not allow_any_location and REPO_ROOT in out.parents and (REPO_ROOT / "realData") not in out.parents:
        raise BundleError(
            "inside the repository the bundle may only be written under realData/ (git-ignored); "
            "choose a path there or outside the repository"
        )


def _entity_rows(doc: dict, channel_order: list[str]) -> tuple[list[tuple], dict[str, int]]:
    """Entity rows (Tier 1 channels first, in panel order, so pk 1..40 follow the panel) and sensor id -> pk."""
    by_sensor = {e["sensor_external_id"]: e for e in doc["entities"] if e["sensor_external_id"]}
    first = [by_sensor[s] for s in channel_order]
    rest = [e for e in doc["entities"] if e not in first]
    rows: list[tuple] = []
    pks: dict[str, int] = {}

    def channel(e: dict, pk: int) -> tuple:
        loaded = e["tier"] == "tier1" and e["load_in_v1"] and e["sensor_external_id"]
        a = e["attribution"]
        return (
            pk, e["entity_id"], "channel", e["sensor_external_id"] or e["reserved_id"] or e["entity_id"], None,
            "measured" if loaded else None, "research_import_file" if loaded else None, e["tier"],
            int(bool(e["load_in_v1"])), e["mapping_state"], e["asset_external_id"], e["source_rack_id"],
            e["source_file_family"], e["source_column"], e["source_label"], e["source_position_word"],
            e["measurand"], e["unit"], e["resolution_decimals"], e["mapping_id"], e["mapping_version"], e["method"],
            e["label_evidence"], e["evidence_status"], e["valid_time_status"], a["scope"],
            json.dumps(list(a["member_source_rack_ids"])), int(bool(a["split_allowed"])),
            json.dumps(e["evidence_refs"], sort_keys=True),
        )  # fmt: skip

    pk = 0
    for e in [*first, *rest]:
        pk += 1
        rows.append(channel(e, pk))
        if e["sensor_external_id"]:
            pks[e["sensor_external_id"]] = pk

    def asset(a: dict, kind: str, pk: int) -> tuple:
        return (
            pk, a["asset_external_id"], kind, a["asset_external_id"], a.get("name"), None, None, a["tier"],
            int(bool(a["load_in_v1"])), None, a["asset_external_id"], a.get("source_rack_id"), None, None, None, None,
            None, None, None, None, None, None, None, a.get("evidence_status"), None, None, None, None,
            json.dumps(a.get("evidence_refs"), sort_keys=True),
        )  # fmt: skip

    for a in doc["racks"]:
        pk += 1
        rows.append(asset(a, "rack", pk))
    for a in doc["power_ports"]:
        pk += 1
        rows.append(asset(a, "power_port", pk))
    pk += 1
    rows.append(asset(doc["zone"], "zone", pk))
    return rows, pks


def _insert(conn: sqlite3.Connection, sql: str, rows, batch: int) -> int:
    n = 0
    it = iter(rows)
    while True:
        part = list(itertools.islice(it, batch))
        if not part:
            return n
        conn.executemany(sql, part)
        n += len(part)


def _cells(pk: int, c: pio.Chunk):
    ticks = np.where(c.ticks_null.astype(bool), None, c.ticks.astype(object)).tolist()
    q = np.where(c.quality < 0, None, c.quality.astype(object)).tolist()
    r = np.where(c.reason == 0, None, c.reason.astype(object)).tolist()
    return zip(itertools.repeat(pk, len(c.t)), c.t.tolist(), ticks, c.state.tolist(), q, r, strict=True)


def build_bundle(
    panel_dir: Path,
    out_path: Path,
    *,
    progress: Callable[[str], None] | None = None,
    batch_rows: int = 50_000,
    chunk_rows: int = 250_000,
    allow_any_location: bool = False,
) -> dict:
    """Build (or atomically rebuild) the bundle. Returns the load report; raises BundleError and leaves the old file."""
    say = progress or (lambda m: None)
    t_start = time.time()
    panel, out = Path(panel_dir).resolve(), Path(out_path).resolve()
    _check_locations(panel, out, allow_any_location)

    # ---- the panel and its inputs must be exactly what Task 14 verified
    manifest = _read_json(panel / "panel_manifest.json")
    channels = _read_json(panel / "channels.json")
    if manifest.get("panel_format") != PANEL_FORMAT or channels.get("panel_format") != PANEL_FORMAT:
        raise BundleError("the panel is not a twingrid.danish_aau.panel/1 panel")
    if manifest["visibility"]["status"] != "local_only":
        raise BundleError("only a local_only panel can be loaded; access_status changes need an owner decision")
    cfg = manifest["inputs"]["cleaning_config"]
    if cfg["range_limits"] or cfg["flatline_min_run"] is not None:
        raise BundleError(
            "the panel was built with a non-default cleaning configuration; bundle v1 supports only the default"
        )
    say("verifying the panel (hashes and re-derivation)")
    _verify_panel_with_tool(panel)
    if manifest["inputs"]["protocol_sha256_lf"] != LOCKED_PROTOCOL_SHA256:
        raise BundleError("the panel was not built under the locked protocol")
    mapping_doc = _read_json(MAPPING_PATH)
    if mapping_doc["mapping_file"]["status"] != "approved":
        raise BundleError("the mapping is not approved")
    if manifest["inputs"]["mapping_file_sha256_lf"] != _lf_sha256(MAPPING_PATH):
        raise BundleError("the committed mapping file differs from the one the panel was built with; rebuild the panel")
    if manifest["inputs"]["derivations_file_sha256_lf"] != _lf_sha256(DERIVATIONS_PATH):
        raise BundleError("the derivations file differs from the one the panel was built with; rebuild the panel")

    dataset_id = manifest["dataset_id"]
    stream = f"import:{dataset_id}"
    if not STREAM_RE.match(stream):
        raise BundleError(f"stream {stream!r} does not match the contract stream grammar")
    counts = manifest["counts"]
    n_sec = counts["unique_seconds"]
    measured = channels["measured_channels"]
    derived_list = channels["derived_channels"]
    if len(measured) != 40 or len(derived_list) != 1:
        raise BundleError("expected 40 measured channels and exactly 1 derived channel in the panel")
    order = [c["sensor_external_id"] for c in measured]
    ent_rows, pk_of = _entity_rows(mapping_doc, order)

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".building")
    if tmp.exists():
        tmp.unlink()
    conn = sqlite3.connect(tmp)
    try:
        for pragma in (
            "PRAGMA page_size = 4096",
            "PRAGMA journal_mode = OFF",
            "PRAGMA synchronous = OFF",
            "PRAGMA temp_store = MEMORY",
            "PRAGMA cache_size = -262144",
            "PRAGMA foreign_keys = OFF",
        ):
            conn.execute(pragma)
        conn.executescript(DDL)
        conn.executemany("INSERT INTO reason_code VALUES (?, ?)", sorted(REASON_CODES.items()))
        conn.executemany("INSERT INTO disposition VALUES (?, ?)", sorted(DISPOSITIONS.items()))
        conn.executemany(f"INSERT INTO entity VALUES ({','.join('?' * 29)})", ent_rows)

        # ---- per-second facts (from the first channel) and per-channel cells
        sec_text = np.empty(n_sec, dtype="U19")
        sec_t = np.empty(n_sec, dtype=np.int64)
        sec_disp = np.empty(n_sec, dtype=np.int8)
        sec_gs = np.empty(n_sec, dtype=np.int32)
        sec_first = np.empty(n_sec, dtype=np.int64)
        derived_def = derived_list[0]
        input_ids = list(derived_def["inputs"])
        in_ticks: dict[str, np.ndarray] = {s: np.zeros(n_sec, dtype=np.int64) for s in input_ids}
        in_ok: dict[str, np.ndarray] = {s: np.zeros(n_sec, dtype=bool) for s in input_ids}
        h = hashlib.sha256()
        per_entity: dict[str, dict] = {}
        inserted = 0
        totals = {"observed": 0, "missing_tie": 0, "missing_blank": 0, "tie_power": 0, "tie_rack_probes": 0}
        for ci, ch in enumerate(measured):
            sid, pk = ch["sensor_external_id"], pk_of[ch["sensor_external_id"]]
            path = panel / "l1" / ch["l1_file"]
            say(f"loading {ci + 1}/40 {ch['l1_file']}")
            pos = 0
            n_obs = n_tie = n_blank = 0
            first_obs = last_obs = None
            for c in pio.iter_chunks(path, derived=False, chunk_rows=chunk_rows):
                m = len(c.t)
                if pos + m > n_sec:
                    raise BundleError(f"{ch['l1_file']}: more rows than the {n_sec} stored seconds")
                sl = slice(pos, pos + m)
                if ci == 0:
                    sec_text[sl], sec_t[sl] = c.ts_text.astype("U19"), c.t
                    sec_disp[sl], sec_gs[sl], sec_first[sl] = c.disposition, c.group_size, c.first_row
                    if pos and c.t[0] <= sec_t[pos - 1] or (np.diff(c.t) <= 0).any():
                        raise BundleError(f"{ch['l1_file']}: timestamps are not strictly ascending (duplicate second)")
                else:
                    if (
                        not np.array_equal(sec_t[sl], c.t)
                        or not np.array_equal(sec_disp[sl], c.disposition)
                        or not np.array_equal(sec_gs[sl], c.group_size)
                        or not np.array_equal(sec_first[sl], c.first_row)
                    ):
                        raise BundleError(f"{ch['l1_file']}: per-second facts differ from the first channel")
                if sid in in_ticks:
                    in_ticks[sid][sl] = c.ticks
                    in_ok[sid][sl] = (c.state == STATE_OBSERVED) & (c.quality == QUALITY_OK)
                inserted += _insert(conn, "INSERT INTO observation VALUES (?,?,?,?,?,?)", _cells(pk, c), batch_rows)
                dg.update(h, pk, c.t, c.ticks, c.ticks_null, c.state, c.quality, c.reason)
                o = c.state == STATE_OBSERVED
                n_obs += int(o.sum())
                n_tie += int((c.reason == 1).sum())
                n_blank += int((c.reason == 2).sum())
                if o.any():
                    idx = np.flatnonzero(o)
                    first_obs = first_obs or str(c.ts_text[idx[0]])
                    last_obs = str(c.ts_text[idx[-1]])
                pos += m
            if pos != n_sec:
                raise BundleError(f"{ch['l1_file']}: {pos} rows, expected {n_sec}")
            if ci == 0:
                conn.executemany(
                    "INSERT INTO second VALUES (?,?,?,?,?)",
                    zip(
                        sec_t.tolist(),
                        sec_text.tolist(),
                        sec_gs.tolist(),
                        sec_disp.tolist(),
                        sec_first.tolist(),
                        strict=True,
                    ),
                )
            q = ch["quality"]
            want = (q["observed"], q["missing_conflict_unresolved_tie"], q["missing_blank_cell"])
            if (n_obs, n_tie, n_blank) != want:
                raise BundleError(
                    f"{ch['l1_file']}: loaded counts {(n_obs, n_tie, n_blank)} differ from channels.json {want}"
                )
            per_entity[sid] = {
                "rows": pos, "observed": n_obs, "missing_conflict_unresolved_tie": n_tie, "missing_blank_cell": n_blank,
                "first_observed_ts_text": first_obs, "last_observed_ts_text": last_obs,
            }  # fmt: skip
            totals["observed"] += n_obs
            totals["missing_tie"] += n_tie
            totals["missing_blank"] += n_blank
            totals["tie_power" if ch["measurand"] == "power" else "tie_rack_probes"] += n_tie
        content_digest = h.hexdigest()

        # ---- second-level checks against the L1 ledger
        say("checking per-state counts against the L1 ledger")
        led = pd.read_csv(
            panel / "l1" / "ledger" / "AAU_temperature_and_power_use.tsv",
            sep="\t", dtype=str, keep_default_na=False, usecols=["disposition", "group_size"],
        )  # fmt: skip
        by = led["disposition"].value_counts().to_dict()
        retained_seconds = sec_disp == 1
        expect = {
            "retained": int(retained_seconds.sum()),
            "exact_duplicate": int((sec_gs[retained_seconds] - 1).sum()),
            "conflict_cell_missing": int(sec_gs[~retained_seconds].sum()),
        }
        for name, want_n in expect.items():
            if int(by.get(name, 0)) != want_n or int(manifest["ledger"]["by_disposition"][name]) != want_n:
                raise BundleError(f"ledger count for {name}: ledger {by.get(name, 0)}, bundle {want_n}")
        if len(led) != counts["raw_rows"] or int(sec_gs.sum()) != counts["raw_rows"]:
            raise BundleError("raw rows differ between the ledger, the stored seconds and the panel manifest")

        # ---- derived series (separate tables)
        say("loading the derived series")
        res = {c["resolution_decimals"] for c in measured if c["sensor_external_id"] in input_ids}
        if len(res) != 1:
            raise BundleError("derived inputs have different resolutions")
        d_dec = next(iter(res))
        conn.execute(
            "INSERT INTO derived_series VALUES (1,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                derived_def["derived_name"], "derived", "derived_series", derived_def["formula_id"],
                derived_def["formula_text"], json.dumps(input_ids), "power", "W", d_dec, derived_def["output_scope"],
                json.dumps(list(derived_def["output_member_source_rack_ids"])), 0, derived_def["method_approval_ref"],
                derived_def["derivations_file_sha256_lf"], DERIVED_REASON_ID,
            ),
        )  # fmt: skip
        dh = hashlib.sha256()
        ok_all = np.logical_and.reduce([in_ok[s] for s in input_ids])
        total = np.sum([in_ticks[s] for s in input_ids], axis=0)
        pos = d_def = d_undef = 0
        for c in pio.iter_chunks(panel / derived_def["file"], derived=True, chunk_rows=chunk_rows):
            m = len(c.t)
            sl = slice(pos, pos + m)
            if pos + m > n_sec or not np.array_equal(sec_t[sl], c.t):
                raise BundleError("derived timestamps differ from the stored seconds")
            defined = c.state == STATE_OBSERVED
            if not np.array_equal(defined, ok_all[sl]) or not np.array_equal(
                np.where(defined, c.ticks, 0), np.where(ok_all[sl], total[sl], 0)
            ):
                raise BundleError("derived values differ from the sum of the loaded input channels")
            rows = zip(
                itertools.repeat(1, len(c.t)), c.t.tolist(),
                np.where(c.ticks_null.astype(bool), None, c.ticks.astype(object)).tolist(),
                c.state.tolist(), np.where(c.quality < 0, None, c.quality.astype(object)).tolist(),
                np.where(c.reason == 0, None, c.reason.astype(object)).tolist(), strict=True,
            )  # fmt: skip
            _insert(conn, "INSERT INTO derived_observation VALUES (?,?,?,?,?,?)", rows, batch_rows)
            dg.update(dh, 1, c.t, c.ticks, c.ticks_null, c.state, c.quality, c.reason)
            d_def += int(defined.sum())
            d_undef += int((~defined).sum())
            pos += m
        if pos != n_sec:
            raise BundleError("derived series has the wrong number of rows")
        if (d_def, d_undef) != (derived_def["defined_seconds"], derived_def["undefined_seconds"]):
            raise BundleError("derived defined/undefined counts differ from channels.json")

        # ---- totals against the panel manifest (and the real-file reference when the panel matched it)
        flagged = 0
        got = {
            "raw_rows": counts["raw_rows"],
            "unique_seconds": n_sec,
            "stored_cells": 40 * n_sec,
            "observed_cells": totals["observed"],
            "tier1_conflict_missing_cells": totals["missing_tie"],
            "tier1_conflict_missing_rack_probes": totals["tie_rack_probes"],
            "tier1_conflict_missing_power": totals["tie_power"],
            "blank_cells": totals["missing_blank"],
            "flagged_cells": flagged,
        }
        for k, v in got.items():
            if counts[k] != v:
                raise BundleError(f"{k}: bundle {v} differs from the panel manifest {counts[k]}")
        if (
            inserted != got["stored_cells"]
            or totals["observed"] + totals["missing_tie"] + totals["missing_blank"] != inserted
        ):
            raise BundleError("inserted cells do not equal observed + missing")
        reference = {"status": "not_applicable"}
        if manifest["reference_check"]["status"] == "matches_task12_real_run":
            ref_got = {**got, "derived_defined_seconds": d_def, "derived_undefined_seconds": d_undef}
            diff = [f"{k}: {ref_got[k]} vs {v}" for k, v in REAL_REFERENCE.items() if ref_got[k] != v]
            if diff:
                raise BundleError("real-file reference mismatch: " + "; ".join(diff))
            reference = {"status": "matches_task12_real_run"}

        report_counts = {
            **got,
            "derived_defined_seconds": d_def,
            "derived_undefined_seconds": d_undef,
            "inserted": inserted,
            "skipped": 0,
            "invalid": 0,
            "conflict": 0,
            "ledger_by_disposition": {k: int(by.get(k, 0)) for k in sorted(by)},
            "per_entity": per_entity,
            "reference_check": reference,
        }
        src = manifest["source"]
        conn.execute(
            f"INSERT INTO dataset_version VALUES (1,{','.join('?' * 26)})",
            (
                BUNDLE_FORMAT, SCHEMA_VERSION, dataset_id, src["version"], src["doi"], f"https://doi.org/{src['doi']}",
                src["licence"],
                f"{'; '.join(src['authors'])}. {src['title']}. Version {src['version']}. {src['publisher']}. "
                f"DOI {src['doi']}. {src['licence']}.",
                src["modifications"], stream, "local_only", manifest["time"]["basis"],
                manifest["time"]["window_first_text"], manifest["time"]["window_last_text"], manifest["raw"]["file"],
                manifest["raw"]["sha256"], manifest["inputs"]["protocol_sha256_lf"],
                manifest["inputs"]["mapping_file_sha256_lf"], manifest["mapping_version"],
                manifest["inputs"]["derivations_file_sha256_lf"], manifest["outputs"]["l1_sha256"],
                manifest["panel_sha256"], code_sha256(), content_digest, dh.hexdigest(),
                json.dumps(report_counts, sort_keys=True),
            ),
        )  # fmt: skip
        conn.commit()
    except BaseException:
        conn.close()
        tmp.unlink(missing_ok=True)
        raise
    conn.close()

    # read-back of the temporary file before it replaces anything
    say("read-back check")
    from .verify import quick_counts

    rb = quick_counts(tmp)
    if rb["observation_rows"] != inserted or rb["second_rows"] != n_sec or rb["derived_rows"] != n_sec:
        tmp.unlink(missing_ok=True)
        raise BundleError(f"read-back counts differ from what was inserted: {rb}")
    if out.exists():
        os.chmod(out, 0o666)
    os.chmod(tmp, 0o444)
    os.replace(tmp, out)
    size = out.stat().st_size
    return {
        "bundle_format": BUNDLE_FORMAT,
        "schema_version": SCHEMA_VERSION,
        "stream": stream,
        "panel_sha256": manifest["panel_sha256"],
        "content_digest": content_digest,
        "derived_content_digest": dh.hexdigest(),
        "loader_code_sha256": code_sha256(),
        "counts": {k: v for k, v in report_counts.items() if k not in ("per_entity",)},
        "read_back": rb,
        "bundle_bytes": size,
        "seconds": round(time.time() - t_start, 1),
        "peak_rss_mb": _peak_rss_mb(),
        "bytes_per_cell": round(size / max(inserted, 1), 2),
    }

"""Owner-run, read-only check of the adapter on the REAL files. Writes an aggregate JSON only (no row values).

    python -m research.danish_aau.adapter.local_check --raw .\\realData\\danish-server-room-v5\\raw --out ..\\task11_local_check.json [--rerun]

Per file: header/schema acceptance, row count, timestamp-text span, repeated-timestamp row count (kept, not resolved),
integrity verification (re-read of every column vs pass 1) and, with --rerun, a cell fingerprint computed twice. The
raw directory is fingerprinted before and after (size + mtime); any change aborts with an error.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path

from ..evaluation.guard import RawDataGuard
from .reader import AdapterReader
from .source import DEFAULT_MANIFEST, discover_all

TOOL = "task11_adapter_local_check 1.0"


def run(
    raw: Path,
    rerun: bool,
    keys: list[str] | None = None,
    manifest_path: Path | None = DEFAULT_MANIFEST,
    integrity: bool = True,
    progress: bool = False,
) -> dict:
    report = {"tool": TOOL, "python": sys.version, "platform": platform.platform(), "files": {}}
    with RawDataGuard(raw):
        for key, src in discover_all(raw, keys, manifest_path=manifest_path).items():
            t0 = time.time()
            say = (
                (lambda m: print(f"[{time.strftime('%H:%M:%S')}] {key}: {m}", file=sys.stderr, flush=True))
                if progress
                else (lambda m: None)
            )
            say("start")
            r = AdapterReader(src)
            idx = r.build_index()
            say(f"index built, {idx.n_rows} rows")
            ver = r.verify_integrity() if integrity else {"skipped": True}
            say("integrity done" if integrity else "integrity skipped")
            entry = {
                "filename": src.spec.filename,
                "n_columns": src.spec.n_columns,
                "rows": int(idx.n_rows),
                "first_ts_text": str(idx.ts_text[0]) if idx.n_rows else None,
                "last_ts_text": str(idx.ts_text[-1]) if idx.n_rows else None,
                "rows_in_repeated_timestamp_groups": int((idx.dup_size > 1).sum()),
                "integrity": ver,
                "file_sha256_from_manifest": src.file_sha256,
            }
            if rerun:
                say("fingerprint run 1")
                a = r.fingerprint()
                say("fingerprint run 2")
                b = r.fingerprint()
                entry.update(fingerprint=a, fingerprint_rerun_identical=a == b)
            entry["seconds"] = round(time.time() - t0, 1)
            report["files"][key] = entry
            say(f"done in {entry['seconds']} s")
    report["raw_directory_unchanged"] = True  # RawDataGuard raises otherwise
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--rerun", action="store_true")
    ap.add_argument("--keys", nargs="*")
    ap.add_argument("--no-integrity", action="store_true", help="skip the full re-read check (much faster)")
    a = ap.parse_args()
    raw, out = Path(a.raw).resolve(), Path(a.out).resolve()
    if raw in out.parents:
        sys.exit("refusing: --out must be outside the raw directory")
    out.write_text(
        json.dumps(run(raw, a.rerun, a.keys, integrity=not a.no_integrity, progress=True), indent=2), encoding="utf-8"
    )
    print("wrote", out)


if __name__ == "__main__":
    main()

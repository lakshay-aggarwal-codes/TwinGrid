"""python -m src.dataset_bundle build|verify|info   (run from the repository root)

build   --panel DIR --out FILE [--report FILE]   build or atomically rebuild the bundle from a Task 14 panel
verify  --bundle FILE [--panel DIR] [--deep]     read-back counts and digests; with --panel also hash links; --deep
                                                 compares every value with the panel TSVs (slow)
info    --bundle FILE                            dataset_version and counts
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .errors import BundleError


def _say(m: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {m}", file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m src.dataset_bundle", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--panel", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--report")
    b.add_argument("--allow-any-location", action="store_true")
    v = sub.add_parser("verify")
    v.add_argument("--bundle", required=True)
    v.add_argument("--panel")
    v.add_argument("--deep", action="store_true")
    i = sub.add_parser("info")
    i.add_argument("--bundle", required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "build":
            from .loader import build_bundle

            rep = build_bundle(Path(a.panel), Path(a.out), progress=_say, allow_any_location=a.allow_any_location)
            text = json.dumps(rep, indent=2, sort_keys=True)
            if a.report:
                Path(a.report).write_text(text + "\n", encoding="utf-8")
            print(text)
            return 0
        if a.cmd == "verify":
            from .verify import verify_bundle

            res = verify_bundle(Path(a.bundle), Path(a.panel) if a.panel else None, deep=a.deep, progress=_say)
            print(json.dumps(res, indent=2, sort_keys=True))
            return 0 if not res["problems"] else 1
        from .reader import dataset_version, open_readonly

        conn = open_readonly(a.bundle)
        try:
            d = dataset_version(conn)
        finally:
            conn.close()
        d["counts"].pop("per_entity", None)
        print(json.dumps(d, indent=2, sort_keys=True))
        return 0
    except BundleError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

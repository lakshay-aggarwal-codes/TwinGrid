"""python -m research.danish_aau.panel build --raw <dir> --out <new dir> [--rerun]   |   verify --out <dir> [--shallow]"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from ..adapter.source import DEFAULT_MANIFEST
from .build import build_panel, rerun_check, verify_panel
from .errors import PanelError


def _say(m: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {m}", file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="panel", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--raw", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    b.add_argument("--no-manifest", action="store_true", help="skip the dataset manifest (synthetic data only)")
    b.add_argument("--rerun", action="store_true", help="build a second time into <out>_rerun and compare every byte")
    v = sub.add_parser("verify")
    v.add_argument("--out", required=True)
    v.add_argument("--shallow", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "build":
            kw = {"manifest_path": None if a.no_manifest else Path(a.manifest), "progress": _say}
            if a.rerun:
                r = rerun_check(Path(a.raw), Path(a.out), **kw)
                print(json.dumps(r, indent=2))
                return 0 if r["identical"] else 1
            m = build_panel(Path(a.raw), Path(a.out), **kw)
            print(
                json.dumps(
                    {"panel_sha256": m["panel_sha256"], "counts": m["counts"], "reference_check": m["reference_check"]},
                    indent=2,
                )
            )
            return 0
        probs = verify_panel(Path(a.out), deep=not a.shallow)
        print(json.dumps({"verified": not probs, "problems": probs}, indent=2))
        return 0 if not probs else 1
    except PanelError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

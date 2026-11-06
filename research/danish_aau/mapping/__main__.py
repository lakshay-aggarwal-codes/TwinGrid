"""``python -m research.danish_aau.mapping verify | report [--out FILE]`` (no data is read)."""

from __future__ import annotations

import argparse
import json
import sys

from .derivations import approved_derivation_ids
from .errors import MappingError
from .loader import load_mapping
from .report import build_report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m research.danish_aau.mapping")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify", help="validate the mapping file and the derivation registry")
    r = sub.add_parser("report", help="print the aggregate mapping report")
    r.add_argument("--out", help="also write the report as JSON to this path")
    args = p.parse_args(argv)
    try:
        reg = load_mapping()
        approved = approved_derivation_ids()
    except MappingError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        for line in getattr(exc, "errors", []):
            print(f"  {line}", file=sys.stderr)
        return 1
    if args.cmd == "verify":
        c = reg.counts()
        print(f"OK mapping v{reg.mapping_version} sha256 {reg.sha256}")
        print(
            f"entities {c['entities']} (unmapped {c['unmapped']}, tier1 not mapped {c['tier1_unmapped']}); approved derivations {len(approved)}"
        )
        return 0
    rep = build_report(reg)
    text = json.dumps(rep, indent=2)
    print(text)
    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

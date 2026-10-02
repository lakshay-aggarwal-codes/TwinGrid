#!/usr/bin/env python3
"""Operator tool for the model artifact manifest (models/registry.json).

  adopt   Give every registry entry that has no manifest (a legacy entry) a
          manifest: project-relative paths, per-file SHA-256 + size, physics
          version, dataset id/hash. Hashes are computed from the files that are
          on disk NOW, i.e. TRUST ON FIRST USE -- run it only after you have
          confirmed those files are the ones you intend to deploy. Idempotent:
          entries that already have a manifest are left alone (see --force).

  verify  Re-hash the newest entry of each model name and report PASS/FAIL
          (exit status 1 on any failure). Same checks the loaders make with
          ARTIFACT_VERIFY=enforce.

Examples:
  python scripts/artifact_manifest.py adopt --dry-run
  python scripts/artifact_manifest.py adopt \
      --dataset-sha256 sensor_data.csv=11f3d473cd9eedd7db7f3a23de56cc72f88f5794f6e0c2a78543b623d06f07d5
  python scripts/artifact_manifest.py verify

Hashes detect changes after logging; they do not defend against a malicious or
compromised training/build pipeline.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src import model_registry as mr  # noqa: E402
from src.versions import PHYSICS_VERSION  # noqa: E402


def _parse_dataset_hashes(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items:
        name, sep, digest = item.partition("=")
        if not sep or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest.lower()):
            raise SystemExit(f"--dataset-sha256 expects ID=<64 hex chars>, got {item!r}")
        out[name] = digest.lower()
    return out


def _adopt_entry(entry: dict, dataset_hashes: dict[str, str]) -> dict:
    """Manifest for ``entry`` from the files on disk now; existing provenance fields are kept."""
    rel = mr.relativise(str(entry["artifact_path"]), anchor_legacy=True)
    source = mr._relative_data_source(str(entry.get("data_source", "")), anchor_legacy=True)
    dataset_id, dataset_sha = mr._dataset_from_source(source)
    head = source.split(" (", 1)[0]
    if dataset_id is None and head.endswith(".csv"):
        dataset_id = Path(head).name
        dataset_sha = dataset_hashes.get(dataset_id)  # None if not supplied: left unknown, not guessed
    fields = mr.build_manifest_fields(
        rel,
        physics_version=PHYSICS_VERSION,
        dataset_id=dataset_id,
        dataset_sha256=dataset_sha,
        git_sha="unknown",
    )
    fields["key_package_versions"] = None  # not recorded at training time; do not claim today's versions
    for key in ("git_sha", "physics_version", "key_package_versions"):
        if key in entry:  # --force on an already-manifested entry: keep what training recorded
            fields[key] = entry[key]
    return {**entry, "data_source": source, **fields}


def cmd_adopt(args: argparse.Namespace) -> int:
    dataset_hashes = _parse_dataset_hashes(args.dataset_sha256)
    entries = mr.read_registry()
    changed = 0
    out = []
    for entry in entries:
        if isinstance(entry.get("files"), dict) and not args.force:
            out.append(entry)
            continue
        adopted = _adopt_entry(entry, dataset_hashes)
        changed += 1
        print(
            f"adopt {entry.get('name')} {entry.get('version')}: {adopted['relative_path']} "
            f"({len(adopted['files'])} files, sha256 {adopted['sha256'][:12]}...)"
        )
        out.append(adopted)
    if not changed:
        print("nothing to do: every entry already has a manifest")
        return 0
    if args.dry_run:
        print(f"dry run: {changed} entr{'y' if changed == 1 else 'ies'} would be updated; nothing written")
        return 0
    mr.write_registry(out)
    print(f"wrote {changed} manifest(s) to {mr.REGISTRY_PATH.relative_to(mr.PROJECT_ROOT).as_posix()}")
    print("NOTE: trust on first use -- these hashes describe the files as found today.")
    return 0


def cmd_verify(_args: argparse.Namespace) -> int:
    entries = mr.read_registry()
    newest: dict[str, dict] = {}
    for entry in entries:
        newest[str(entry.get("name"))] = entry
    failures = 0
    for name, entry in newest.items():
        files = entry.get("files")
        if not isinstance(files, dict) or not files:
            print(f"FAIL {name} {entry.get('version')}: no manifest (run: adopt)")
            failures += 1
            continue
        try:
            mr._check([mr.PROJECT_ROOT / rel for rel in files])
            print(f"PASS {name} {entry.get('version')}: {len(files)} file(s)")
        except mr.ModelUnavailableError as exc:
            print(f"FAIL {name} {entry.get('version')}: {exc.reason}")
            failures += 1
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    adopt = sub.add_parser("adopt", help="add a manifest to legacy registry entries (trust on first use)")
    adopt.add_argument("--dry-run", action="store_true", help="show what would change; write nothing")
    adopt.add_argument(
        "--force",
        action="store_true",
        help="re-record hashes for entries that already have a manifest (explicitly re-trusts the files on disk)",
    )
    adopt.add_argument(
        "--dataset-sha256", action="append", default=[], metavar="ID=HEX", help="known dataset hash, repeatable"
    )
    adopt.set_defaults(func=cmd_adopt)
    verify = sub.add_parser("verify", help="re-hash the newest entry of each model and report")
    verify.set_defaults(func=cmd_verify)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

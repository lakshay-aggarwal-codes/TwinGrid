"""Owner-run, read-only check for F-3 / O-12: are the extracted `_mv` images the members of the manifest zip?

    python -m research.danish_aau.mapping.mv_members_check --raw <raw directory of the dataset> --out ..\\mv_members_check.json [--write-sidecar]

Reads `Measurement_visualization.zip` (never extracts to disk), hashes every member, hashes the files in
`_mv/Measurement_visualization/`, and compares both with the image hashes recorded in the mapping file. Nothing in the raw
directory is changed. `--write-sidecar` writes `docs/datasets/danish-server-room-v5/manifest_extracted_members.json`
only when every check passes; `manifest.json` itself is never edited.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

from .loader import MAPPING_PATH

CONTAINER = "Measurement_visualization.zip"
SIDECAR = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "datasets"
    / "danish-server-room-v5"
    / "manifest_extracted_members.json"
)
TOOL = "danish_aau.mapping.mv_members_check 1"


def _sha(fp) -> str:
    h = hashlib.sha256()
    for block in iter(lambda: fp.read(1 << 20), b""):
        h.update(block)
    return h.hexdigest()


def recorded_image_hashes(doc: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in ("probe_images", "plot_images"):
        out.update(doc["evidence_sources"][key]["sha256"])
    return out


def check(raw: Path, doc: dict, manifest_sha256: str | None = None) -> dict:
    raw = Path(raw)
    recorded = recorded_image_hashes(doc)
    zpath = raw / CONTAINER
    members: dict[str, dict] = {}
    with zipfile.ZipFile(zpath) as z, open(zpath, "rb") as zf:
        container_sha = _sha(zf)
        for info in z.infolist():
            if info.is_dir():
                continue
            with z.open(info) as fp:
                members[Path(info.filename).name] = {
                    "member_path": info.filename, "size_bytes": info.file_size, "sha256": _sha(fp),
                }  # fmt: skip
    disk: dict[str, str] = {}
    folder = raw / "_mv" / "Measurement_visualization"
    if folder.is_dir():
        for p in sorted(folder.iterdir()):
            if p.is_file():
                with open(p, "rb") as fp:
                    disk[p.name] = _sha(fp)
    rep = {
        "tool": TOOL, "container": CONTAINER, "container_sha256": container_sha,
        "container_matches_manifest": None if manifest_sha256 is None else container_sha == manifest_sha256,
        "members": {k: {**v, "recorded_in_mapping": recorded.get(k) == v["sha256"], "disk_equals_member": disk.get(k) == v["sha256"]}
                    for k, v in sorted(members.items())},
        "mapping_images_missing_from_zip": sorted(set(recorded) - set(members)),
        "zip_members_not_in_mapping": sorted(set(members) - set(recorded)),
        "disk_files_not_in_zip": sorted(set(disk) - set(members)),
    }  # fmt: skip
    rep["all_recorded_images_equal_zip_members"] = (
        all(recorded.get(k) == members[k]["sha256"] for k in recorded if k in members)
        and not rep["mapping_images_missing_from_zip"]
    )
    rep["all_disk_files_equal_zip_members"] = (
        bool(disk)
        and all(disk[k] == members[k]["sha256"] for k in disk if k in members)
        and not rep["disk_files_not_in_zip"]
    )
    rep["ok"] = (
        rep["all_recorded_images_equal_zip_members"]
        and rep["all_disk_files_equal_zip_members"]
        and rep["container_matches_manifest"] is not False
    )
    return rep


def sidecar_document(rep: dict) -> dict:
    return {
        "description": "Members of Measurement_visualization.zip (listed in manifest.json) that were extracted to _mv/Measurement_visualization/. Written by mv_members_check after the zip members, the extracted files and the mapping's recorded hashes all agreed. manifest.json is unchanged.",
        "container": rep["container"], "container_sha256": rep["container_sha256"],
        "members": {k: {"size_bytes": v["size_bytes"], "sha256": v["sha256"]} for k, v in rep["members"].items()},
    }  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--write-sidecar", action="store_true")
    a = ap.parse_args()
    raw, out = Path(a.raw).resolve(), Path(a.out).resolve()
    if raw in out.parents:
        sys.exit("refusing: --out must be outside the raw directory")
    manifest = json.loads((SIDECAR.parent / "manifest.json").read_text(encoding="utf-8-sig"))
    msha = next((f["local_sha256"] for f in manifest["files"] if f["filename"] == CONTAINER), None)
    doc = json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
    rep = check(raw, doc, msha)
    out.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print("wrote", out, "| ok =", rep["ok"])
    if a.write_sidecar:
        if not rep["ok"]:
            sys.exit("not writing the sidecar: a check failed")
        SIDECAR.write_text(json.dumps(sidecar_document(rep), indent=2) + "\n", encoding="utf-8", newline="\n")
        print("wrote", SIDECAR)


if __name__ == "__main__":
    main()

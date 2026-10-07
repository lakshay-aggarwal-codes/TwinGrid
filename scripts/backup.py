#!/usr/bin/env python3
"""T32 backup: pg_dump -Fc through ``docker compose exec`` + file copies + a recorded state snapshot.

  python scripts/backup.py --out-dir backups/<stamp>

Writes into --out-dir: twingrid.dump (pg_dump -Fc), files/{models,configs,data_manifests,REGISTER.json,.env.example},
state.json (what restore_verify.py compares against) and backup_manifest.json (sha256 + size of every file).
It reads the database and the repo; it changes neither. Secrets are never written: the dump holds DB contents
(treat the backup directory as sensitive) but .env is NOT copied, only .env.example.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence

ROOT = Path(__file__).resolve().parent.parent
DB_NAME = "digital_twin"
DB_USER = "postgres"
AUDIT_TRIGGER = "audit_logs_append_only"
COPY_DIRS = ("models", "configs")
SKIP_PARTS = {"__pycache__", ".git"}


# ---- pure helpers (unit-tested) ------------------------------------------------------------------
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ordered_hash(lines: Iterable[str]) -> str:
    """Order-sensitive digest of rows: sha256 over the lines joined by LF. Reordering or editing any row changes it."""
    h = hashlib.sha256()
    n = 0
    for line in lines:
        h.update(line.encode("utf-8"))
        h.update(b"\n")
        n += 1
    h.update(f"#{n}".encode())
    return h.hexdigest()


def aggregate_sha256(files: dict[str, str]) -> str:
    """Same rule as src.model_registry.aggregate_sha256: sha256 over sorted 'path sha256' lines."""
    return hashlib.sha256("\n".join(f"{k} {files[k]}" for k in sorted(files)).encode("utf-8")).hexdigest()


def registry_mismatches(registry: dict, root: Path) -> list[str]:
    """Every file listed by a registry entry must exist under ``root`` with the recorded sha256."""
    bad: list[str] = []
    for entry in registry.get("artifacts", []):
        for rel, meta in (entry.get("files") or {}).items():
            p = root / rel
            if not p.is_file():
                bad.append(f"{entry.get('model_id')}: {rel} missing")
            elif sha256_file(p) != meta["sha256"]:
                bad.append(f"{entry.get('model_id')}: {rel} sha256 differs")
    return bad


def tree_files(base: Path) -> list[Path]:
    return sorted(p for p in base.rglob("*") if p.is_file() and not (set(p.parts) & SKIP_PARTS))


def required_env_vars(compose_text: str) -> list[str]:
    import re

    return sorted(set(re.findall(r"\$\{([A-Z][A-Z0-9_]*):\?", compose_text)))


def missing_from_env_example(required: Sequence[str], env_example_text: str) -> list[str]:
    import re

    present = set(re.findall(r"^\s*#?\s*([A-Z][A-Z0-9_]*)=", env_example_text, flags=re.M))
    return [v for v in required if v not in present]


# ---- docker / psql plumbing -----------------------------------------------------------------------
Runner = Callable[..., subprocess.CompletedProcess]


def run(
    cmd: Sequence[str], *, cwd: Path = ROOT, input: bytes | None = None, check: bool = True
) -> subprocess.CompletedProcess:
    cp = subprocess.run(list(cmd), cwd=cwd, input=input, capture_output=True)
    if check and cp.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:6])} failed ({cp.returncode}): {cp.stderr.decode(errors='replace')[:500]}")
    return cp


def psql(sql: str, *, db: str = DB_NAME, runner: Runner = run) -> list[str]:
    cp = runner(["docker", "compose", "exec", "-T", "db", "psql", "-U", DB_USER, "-d", db, "-At", "-c", sql])
    return [ln for ln in cp.stdout.decode().splitlines() if ln != ""]


def capture_state(db: str = DB_NAME, runner: Runner = run) -> dict:
    """What a correct restore must reproduce: table row counts, audit ordered hash, telemetry ranges, trigger, head."""
    tables = psql(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY 1",
        db=db,
        runner=runner,
    )
    counts = {t: int(psql(f'SELECT count(*) FROM "{t}"', db=db, runner=runner)[0]) for t in tables}
    state: dict = {"database": db, "row_counts": counts}
    if "audit_logs" in tables:
        rows = psql("SELECT row_to_json(a)::text FROM audit_logs a ORDER BY id", db=db, runner=runner)
        state["audit_logs"] = {"rows": len(rows), "ordered_sha256": ordered_hash(rows)}
    if "telemetry_sample" in tables:
        rows = psql(
            "SELECT stream_id||'|'||count(*)||'|'||min(ts_event)::text||'|'||max(ts_event)::text FROM telemetry_sample GROUP BY stream_id ORDER BY stream_id",
            db=db,
            runner=runner,
        )
        state["telemetry"] = {
            r.split("|")[0]: {
                "count": int(r.split("|")[1]),
                "min_ts_event": r.split("|")[2],
                "max_ts_event": r.split("|")[3],
            }
            for r in rows
        }
    if "alembic_version" in tables:
        state["alembic_version"] = psql("SELECT version_num FROM alembic_version", db=db, runner=runner)
    state["audit_trigger_present"] = bool(
        psql(f"SELECT 1 FROM pg_trigger WHERE tgname='{AUDIT_TRIGGER}' AND NOT tgisinternal", db=db, runner=runner)
    )
    return state


def repo_alembic_head() -> list[str]:
    cp = run([sys.executable, "-m", "alembic", "heads"], check=False)
    return [ln.split()[0] for ln in cp.stdout.decode().splitlines() if ln.strip()]


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def backup(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=False)
    t0 = time.monotonic()
    snapshot_at = datetime.now(timezone.utc).isoformat()
    state = capture_state()
    state["snapshot_at"] = snapshot_at
    dump = out_dir / "twingrid.dump"
    cp = run(["docker", "compose", "exec", "-T", "db", "pg_dump", "-U", DB_USER, "-Fc", DB_NAME])
    dump.write_bytes(cp.stdout)
    files = out_dir / "files"
    for d in COPY_DIRS:
        if (ROOT / d).is_dir():
            shutil.copytree(ROOT / d, files / d, ignore=shutil.ignore_patterns(*SKIP_PARTS))
    for m in sorted((ROOT / "data").rglob("*manifest*.json")) if (ROOT / "data").is_dir() else []:
        dest = files / "data_manifests" / m.relative_to(ROOT / "data")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(m, dest)
    for name, rel in (("REGISTER.json", "data/external/REGISTER.json"), (".env.example", ".env.example")):
        if (ROOT / rel).is_file():
            shutil.copy2(ROOT / rel, files / name)
    (out_dir / "state.json").write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    manifest = {
        "created_at": utc_stamp(),
        "snapshot_at": snapshot_at,
        "duration_s": round(time.monotonic() - t0, 3),
        "repo_alembic_heads": repo_alembic_head(),
        "dump_bytes": dump.stat().st_size,
        "files": {
            str(p.relative_to(out_dir)): {"sha256": sha256_file(p), "size": p.stat().st_size}
            for p in tree_files(out_dir)
        },
    }
    (out_dir / "backup_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out-dir", type=Path, required=True)
    a = ap.parse_args(argv)
    m = backup(a.out_dir)
    print(f"backup ok: {a.out_dir} dump={m['dump_bytes']} bytes in {m['duration_s']}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

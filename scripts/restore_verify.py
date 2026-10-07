#!/usr/bin/env python3
"""T32 restore drill: restore a backup into a SCRATCH database and verify it (reports/ops/restore_drill_<date>.md).

  python scripts/restore_verify.py --backup-dir backups/<stamp> [--n1-dump path/to/older.dump] [--report-dir reports/ops]

Never touches the live database: everything happens in scratch databases that are dropped at the end.
A check that cannot run is recorded as FAIL (not skipped); the report says PASS only if every check passed.
Observed RTO = wall time from "restore started" to "API /readyz 200 on the restored DB".
Observed RPO = restore start minus the backup snapshot time (writes after the snapshot would be lost).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("tg_backup", _HERE / "backup.py")
bk = importlib.util.module_from_spec(_spec)
sys.modules["tg_backup"] = bk
_spec.loader.exec_module(bk)

ROOT = bk.ROOT
SCRATCH = "twingrid_restore_scratch"
SCRATCH_N1 = "twingrid_restore_n1"
READY_PORT = 18000


# ---- pure comparison logic (unit-tested) --------------------------------------------------------
def compare_state(recorded: dict, restored: dict) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    rc, rr = recorded["row_counts"], restored["row_counts"]
    diff = {t: (rc.get(t), rr.get(t)) for t in sorted(set(rc) | set(rr)) if rc.get(t) != rr.get(t)}
    checks.append(
        ("row counts equal (every public table)", not diff, f"{len(rc)} tables" if not diff else f"differ: {diff}")
    )
    ra, rs = recorded.get("audit_logs"), restored.get("audit_logs")
    checks.append(
        (
            "audit_logs ordered hash equal",
            ra is not None and ra == rs,
            f"rows={ra and ra['rows']}" if ra == rs else f"{ra} != {rs}",
        )
    )
    rt, rst = recorded.get("telemetry"), restored.get("telemetry")
    checks.append(
        (
            "telemetry count and min/max ts_event per stream equal",
            rt is not None and rt == rst,
            f"{len(rt or {})} streams" if rt == rst else f"{rt} != {rst}",
        )
    )
    checks.append(("audit trigger present after restore", bool(restored.get("audit_trigger_present")), ""))
    return checks


def head_check(recorded_heads: Sequence[str], restored_versions: Sequence[str]) -> tuple[str, bool, str]:
    ok = bool(recorded_heads) and sorted(recorded_heads) == sorted(restored_versions)
    return (
        "alembic current equals recorded head",
        ok,
        f"recorded={list(recorded_heads)} restored={list(restored_versions)}",
    )


def render_report(r: dict) -> str:
    ok = all(c["passed"] for c in r["checks"])
    lines = [
        f"# Restore drill {r['date']}",
        "",
        f"**Result: {'PASS' if ok else 'FAIL'}** - {sum(c['passed'] for c in r['checks'])}/{len(r['checks'])} checks passed.",
        "",
        "Claim allowed: a restore from backup succeeded on this date with the measured RTO/RPO below, on this host and data volume only."
        if ok
        else "Claim allowed: none. At least one integrity check failed; fix via a new task and repeat the drill.",
        "",
        "## Measurements",
        f"- Host: {r['host']}",
        f"- Backup: `{r['backup_dir']}` dump {r['dump_bytes']} bytes, backup duration {r['backup_duration_s']} s",
        f"- Observed RTO (restore start -> /readyz 200): {r['rto_s']} s",
        f"- Observed RPO (restore start - snapshot time): {r['rpo_s']} s",
        "- Durations (s): " + ", ".join(f"{k}={v}" for k, v in r["durations_s"].items()),
        "",
        "## Checks",
        "| # | Check | Result | Detail |",
        "|---|---|---|---|",
    ]
    for i, c in enumerate(r["checks"], 1):
        lines.append(
            f"| {i} | {c['name']} | {'PASS' if c['passed'] else 'FAIL'} | {str(c['detail']).replace('|', '/')[:300]} |"
        )
    lines += ["", "No RPO/RTO or durability guarantee beyond these measurements is implied.", ""]
    return "\n".join(lines)


# ---- orchestration -----------------------------------------------------------------------------------
def _compose(*args: str, input: bytes | None = None, check: bool = True):
    return bk.run(["docker", "compose", *args], input=input, check=check)


def _db(*args: str, input: bytes | None = None, check: bool = True):
    return _compose("exec", "-T", "db", *args, input=input, check=check)


def _recreate(db: str) -> None:
    _db("psql", "-U", bk.DB_USER, "-d", "postgres", "-c", f'DROP DATABASE IF EXISTS "{db}"')
    _db("psql", "-U", bk.DB_USER, "-d", "postgres", "-c", f'CREATE DATABASE "{db}"')


def _restore(dump: Path, db: str) -> None:
    _db("pg_restore", "-U", bk.DB_USER, "--no-owner", "-d", db, input=dump.read_bytes())


def _backend_cmd(db: str, *cmd: str):
    pw = _compose("exec", "-T", "db", "printenv", "POSTGRES_PASSWORD").stdout.decode().strip()
    url = f"postgresql+asyncpg://{bk.DB_USER}:{pw}@db:5432/{db}"
    return _compose("run", "--rm", "--no-deps", "-e", f"DATABASE_URL={url}", "backend", *cmd)


def _poll_readyz(timeout: float = 120.0) -> tuple[bool, str]:
    end = time.monotonic() + timeout
    last = "no response"
    while time.monotonic() < end:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{READY_PORT}/readyz", timeout=3) as resp:  # noqa: S310
                if resp.status == 200:
                    return True, "200"
                last = str(resp.status)
        except Exception as exc:  # noqa: BLE001
            last = type(exc).__name__
        time.sleep(2)
    return False, last


def drill(backup_dir: Path, n1_dump: Path | None, report_dir: Path) -> tuple[dict, bool]:
    manifest = json.loads((backup_dir / "backup_manifest.json").read_text())
    recorded = json.loads((backup_dir / "state.json").read_text())
    checks: list[dict] = []
    dur: dict[str, float] = {}

    def add(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    def timed(label: str, fn: Callable):
        t = time.monotonic()
        try:
            return fn()
        finally:
            dur[label] = round(time.monotonic() - t, 2)

    # backup file integrity first: a corrupt backup must not look like a restore problem
    bad = [
        rel
        for rel, m in manifest["files"].items()
        if not (backup_dir / rel).is_file() or bk.sha256_file(backup_dir / rel) != m["sha256"]
    ]
    add(
        "backup files match backup_manifest.json sha256",
        not bad,
        f"bad: {bad}" if bad else f"{len(manifest['files'])} files",
    )

    t_restore = time.monotonic()
    restore_start = datetime.now(timezone.utc)
    try:
        timed("create_scratch", lambda: _recreate(SCRATCH))
        timed("pg_restore", lambda: _restore(backup_dir / "twingrid.dump", SCRATCH))
        restored = timed("collect_state", lambda: bk.capture_state(SCRATCH))
        for name, ok, detail in compare_state(recorded, restored):
            add(name, ok, detail)
        add(
            *head_check(
                manifest.get("repo_alembic_heads", []) or recorded.get("alembic_version", []),
                restored.get("alembic_version", []),
            )
        )
        cur = _backend_cmd(SCRATCH, "alembic", "current").stdout.decode()
        add(
            "alembic current (run by the app image) equals recorded head",
            all(h in cur for h in recorded.get("alembic_version", ["<none>"])),
            cur.strip()[-200:],
        )

        reg = json.loads((backup_dir / "files/models/registry.json").read_text())
        mism = bk.registry_mismatches(reg, backup_dir / "files")
        add(
            "artifact SHA-256 equals registry (restored copy of models/)",
            not mism,
            "; ".join(mism[:5]) or "all registry files match",
        )

        # API boot against the restored DB
        pw = _compose("exec", "-T", "db", "printenv", "POSTGRES_PASSWORD").stdout.decode().strip()
        url = f"postgresql+asyncpg://{bk.DB_USER}:{pw}@db:5432/{SCRATCH}"
        _compose(
            "run",
            "-d",
            "--rm",
            "--no-deps",
            "--name",
            "twingrid_restore_api",
            "-p",
            f"{READY_PORT}:8000",
            "-e",
            f"DATABASE_URL={url}",
            "backend",
        )
        ready, detail = timed("api_boot_readyz", _poll_readyz)
        add("API boots and /readyz is 200 against the restored DB", ready, detail)
        rto = round(time.monotonic() - t_restore, 2)
    finally:
        bk.run(["docker", "rm", "-f", "twingrid_restore_api"], check=False)

    if n1_dump is not None and n1_dump.is_file():
        try:
            timed("n1_restore", lambda: (_recreate(SCRATCH_N1), _restore(n1_dump, SCRATCH_N1)))
            timed("n1_upgrade", lambda: _backend_cmd(SCRATCH_N1, "alembic", "upgrade", "head"))
            cur = _backend_cmd(SCRATCH_N1, "alembic", "current").stdout.decode()
            add(
                "N-1 dump upgrades to head",
                all(h in cur for h in recorded.get("alembic_version", ["<none>"])),
                cur.strip()[-200:],
            )
        except Exception as exc:  # noqa: BLE001
            add("N-1 dump upgrades to head", False, str(exc)[:300])
    else:
        add("N-1 dump upgrades to head", False, "no --n1-dump supplied: check not executed (counts as FAIL)")

    required = bk.required_env_vars((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    missing = bk.missing_from_env_example(required, (backup_dir / "files/.env.example").read_text(encoding="utf-8"))
    add(
        ".env.example covers every required variable",
        not missing,
        f"missing: {missing}" if missing else f"required: {required}",
    )

    for db in (SCRATCH, SCRATCH_N1):
        bk.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "db",
                "psql",
                "-U",
                bk.DB_USER,
                "-d",
                "postgres",
                "-c",
                f'DROP DATABASE IF EXISTS "{db}"',
            ],
            check=False,
        )

    import platform

    rpo = round((restore_start - datetime.fromisoformat(recorded["snapshot_at"])).total_seconds(), 1)
    report = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "host": f"{platform.platform()}, cpus={os.cpu_count()}",
        "backup_dir": str(backup_dir),
        "dump_bytes": manifest["dump_bytes"],
        "backup_duration_s": manifest["duration_s"],
        "rto_s": rto,
        "rpo_s": rpo,
        "durations_s": dur,
        "checks": checks,
    }
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / f"restore_drill_{report['date']}.md").write_text(render_report(report), encoding="utf-8")
    (report_dir / f"restore_drill_{report['date']}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report, all(c["passed"] for c in checks)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backup-dir", type=Path, required=True)
    ap.add_argument("--n1-dump", type=Path, default=None, help="pg_dump -Fc taken at the PREVIOUS schema revision")
    ap.add_argument("--report-dir", type=Path, default=ROOT / "reports" / "ops")
    a = ap.parse_args(argv)
    report, ok = drill(a.backup_dir, a.n1_dump, a.report_dir)
    print(f"drill {'PASS' if ok else 'FAIL'}: RTO={report['rto_s']}s RPO={report['rpo_s']}s")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

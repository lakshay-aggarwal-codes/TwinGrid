"""T32 helper tests (hashing, ordering, comparison, report). The restore drill itself is the acceptance test."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


bk = _load("tg_backup", "scripts/backup.py")
rv = _load("tg_restore_verify", "scripts/restore_verify.py")


def test_ordered_hash_is_order_and_content_sensitive():
    a = ["r1", "r2", "r3"]
    assert bk.ordered_hash(a) == bk.ordered_hash(list(a))
    assert bk.ordered_hash(a) != bk.ordered_hash(["r2", "r1", "r3"])
    assert bk.ordered_hash(a) != bk.ordered_hash(["r1", "r2", "r3x"])
    assert bk.ordered_hash(a) != bk.ordered_hash(a + [""])  # row count is part of the digest
    assert bk.ordered_hash([]) != bk.ordered_hash([""])


def test_aggregate_matches_model_registry_rule():
    files = {"b": "2" * 64, "a": "1" * 64}
    import hashlib

    assert bk.aggregate_sha256(files) == hashlib.sha256(f"a {'1'*64}\nb {'2'*64}".encode()).hexdigest()


def test_registry_mismatches(tmp_path):
    f = tmp_path / "models" / "m.bin"
    f.parent.mkdir()
    f.write_bytes(b"abc")
    reg = {
        "artifacts": [
            {
                "model_id": "x",
                "files": {"models/m.bin": {"sha256": bk.sha256_file(f)}, "models/gone.bin": {"sha256": "0"}},
            }
        ]
    }
    assert bk.registry_mismatches(reg, tmp_path) == ["x: models/gone.bin missing"]
    f.write_bytes(b"abd")
    assert any("sha256 differs" in m for m in bk.registry_mismatches(reg, tmp_path))


def test_env_example_coverage():
    compose = "A: ${JWT_SECRET_KEY:?x}\nB: ${POSTGRES_PASSWORD:?y} ${OTHER:-d}"
    req = bk.required_env_vars(compose)
    assert req == ["JWT_SECRET_KEY", "POSTGRES_PASSWORD"]
    assert bk.missing_from_env_example(req, "JWT_SECRET_KEY=\n# POSTGRES_PASSWORD=x") == []
    assert bk.missing_from_env_example(req, "JWT_SECRET_KEY=1") == ["POSTGRES_PASSWORD"]


def test_repo_env_example_covers_repo_compose():
    req = bk.required_env_vars((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    assert req, "compose should declare required variables"
    assert bk.missing_from_env_example(req, (ROOT / ".env.example").read_text(encoding="utf-8")) == []


GOOD = {
    "row_counts": {"users": 2, "audit_logs": 5},
    "audit_logs": {"rows": 5, "ordered_sha256": "h"},
    "telemetry": {"live": {"count": 3, "min_ts_event": "a", "max_ts_event": "b"}},
    "audit_trigger_present": True,
}


def test_compare_state_pass_and_each_failure():
    assert all(ok for _, ok, _ in rv.compare_state(GOOD, json.loads(json.dumps(GOOD))))
    for mutate in (
        lambda s: s["row_counts"].update(users=1),
        lambda s: s["audit_logs"].update(ordered_sha256="x"),
        lambda s: s["telemetry"]["live"].update(max_ts_event="z"),
        lambda s: s.update(audit_trigger_present=False),
    ):
        bad = json.loads(json.dumps(GOOD))
        mutate(bad)
        assert not all(ok for _, ok, _ in rv.compare_state(GOOD, bad))


def test_head_check():
    assert rv.head_check(["h1"], ["h1"])[1]
    assert not rv.head_check(["h1"], ["h0"])[1]
    assert not rv.head_check([], [])[1]  # nothing recorded is not a pass


def test_report_pass_requires_every_check():
    base = {
        "date": "2026-01-01",
        "host": "h",
        "backup_dir": "b",
        "dump_bytes": 1,
        "backup_duration_s": 1,
        "rto_s": 2,
        "rpo_s": 3,
        "durations_s": {"pg_restore": 1.0},
        "checks": [{"name": "a", "passed": True, "detail": ""}],
    }
    assert "**Result: PASS**" in rv.render_report(base)
    base["checks"].append({"name": "b", "passed": False, "detail": "x|y"})
    out = rv.render_report(base)
    assert "**Result: FAIL**" in out and "Claim allowed: none" in out and "x/y" in out

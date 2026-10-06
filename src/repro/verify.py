"""``repro.py verify``: recompute input hashes, regenerate the report from ``results.json``, diff.

Every finding names the manifest field (or file) it is about. ``FAIL`` means the run can no longer be
re-derived from what it recorded; ``WARN`` means something could not be checked or the environment
differs (level L1 needs the same one; other platforms are not claimed bit-identical). ``--strict``
turns warnings into failures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import env, experiments, report
from .canonical import canonical_bytes, sha256_bytes, sha256_input_file, sha256_raw_file
from .run import REQUIRED_MANIFEST_FIELDS, RunError, execute_experiment, read_json, run_dir_for


@dataclass
class Finding:
    level: str  # "FAIL" | "WARN"
    field: str
    message: str

    def __str__(self) -> str:
        return f"{self.level} {self.field}: {self.message}"


@dataclass
class VerifyReport:
    run_id: str
    findings: list[Finding] = field(default_factory=list)

    def fail(self, name: str, message: str) -> None:
        self.findings.append(Finding("FAIL", name, message))

    def warn(self, name: str, message: str) -> None:
        self.findings.append(Finding("WARN", name, message))

    @property
    def failures(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "FAIL"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "WARN"]

    def ok(self, strict: bool = False) -> bool:
        return not self.failures and not (strict and self.warnings)


def _lf(raw: bytes) -> bytes:
    """Generated files are ASCII/UTF-8 text; a CRLF checkout (``core.autocrlf``) is not a modification."""
    return raw.replace(b"\r\n", b"\n")


def _mismatch(rep: VerifyReport, name: str, expected: Any, actual: Any, what: str = "") -> None:
    rep.fail(name, f"{what}recorded {expected!r} but now {actual!r}")


def _check_file(rep: VerifyReport, root: Path, name: str, rel: str, expected: str | None, *, text: bool) -> None:
    try:
        path = env.resolve_in_root(rel, root)
    except env.PathOutsideRoot as exc:
        rep.fail(name, str(exc))
        return
    if not path.is_file():
        rep.fail(name, f"{rel} is missing")
        return
    actual = sha256_input_file(path) if text else sha256_raw_file(path)
    if actual != expected:
        _mismatch(rep, name, expected, actual, f"{rel}: sha256 ")


def _check_code(rep: VerifyReport, root: Path, m: dict[str, Any]) -> None:
    now = env.code_state(root)
    if m["code_revision"] == "unknown":
        rep.warn(
            "code_revision",
            "the run did not record a code revision (no git and no GIT_SHA), so the code cannot be checked",
        )
        return
    if now["code_revision"] == "unknown":
        rep.warn("code_revision", "the current code revision cannot be determined (no git and no GIT_SHA)")
        return
    if now["code_revision"] != m["code_revision"]:
        _mismatch(rep, "code_revision", m["code_revision"], now["code_revision"])
        return
    if m["dirty"]:
        if m["dirty_diff_sha256"] is not None and now["dirty_diff_sha256"] != m["dirty_diff_sha256"]:
            _mismatch(
                rep,
                "dirty_diff_sha256",
                m["dirty_diff_sha256"],
                now["dirty_diff_sha256"],
                "uncommitted changes differ: ",
            )
        elif m["dirty_diff_sha256"] is None:
            rep.warn(
                "dirty", "the run recorded a dirty tree without a diff digest; the exact code state cannot be checked"
            )
    elif now["dirty"] and now["code_revision_source"] == "git":
        rep.fail(
            "dirty", "the run recorded a clean tree at this revision but the working tree now has uncommitted changes"
        )


def _check_lineage(rep: VerifyReport, m: dict[str, Any]) -> None:
    try:
        from src import versions

        running = versions.running_compat_values()
    except Exception as exc:  # noqa: BLE001
        rep.warn("lineage", f"running version constants could not be computed ({type(exc).__name__})")
        return
    for key, now in running.items():
        recorded = m.get(key)
        if recorded is not None and recorded != now:
            _mismatch(rep, key, recorded, now)


def _check_platform(rep: VerifyReport, m: dict[str, Any]) -> None:
    now = env.platform_info()
    recorded = m.get("platform") or {}
    for key in ("os", "arch", "python", "numpy", "torch", "tensorflow"):
        if recorded.get(key) != now.get(key):
            rep.warn(
                f"platform.{key}",
                f"recorded {recorded.get(key)!r}, now {now.get(key)!r}; re-derivation is only claimed on the same environment",
            )


def _check_generated(rep: VerifyReport, run_dir: Path, results: dict[str, Any]) -> None:
    expected = report.render_all(results)
    for rel, text in expected.items():
        path = run_dir / rel
        if not path.is_file():
            rep.fail(rel, "missing; it is generated from results.json")
        elif _lf(path.read_bytes()) != text.encode("utf-8"):
            rep.fail(
                rel,
                "differs from the version regenerated from results.json (edited by hand, or generated by other code)",
            )
    for sub in ("tables", "figures"):
        directory = run_dir / sub
        if directory.is_dir():
            for f in sorted(directory.iterdir()):
                if f"{sub}/{f.name}" not in expected:
                    rep.fail(f"{sub}/{f.name}", "unexpected file: not generated from results.json")
    leftovers = report.check_report_numbers(expected["REPORT.md"], results)
    if leftovers:  # a template bug: the generator itself printed numbers that are not in results.json
        rep.fail("REPORT.md", f"numbers not present in results.json: {', '.join(leftovers)}")
    on_disk = run_dir / "REPORT.md"
    if on_disk.is_file():
        stray = report.check_report_numbers(_lf(on_disk.read_bytes()).decode("utf-8"), results)
        if stray:
            rep.fail("REPORT.md", f"numbers not present in results.json: {', '.join(stray)}")


def verify_run(root: Path, run_id: str, *, runs_dir: str = env.RUNS_SUBDIR, rerun: bool = False) -> VerifyReport:
    """Verify ``reports/runs/<run_id>``. Never raises for a bad run; every problem is a finding."""
    root = Path(root).resolve()
    rep = VerifyReport(run_id)
    try:
        run_dir = run_dir_for(root, run_id, runs_dir)
    except (RunError, env.PathOutsideRoot) as exc:
        rep.fail("run_id", str(exc))
        return rep
    if not run_dir.is_dir():
        rep.fail("run_id", f"no run directory for {run_id}")
        return rep

    try:
        m = read_json(run_dir / "manifest.json")
    except (OSError, ValueError):
        rep.fail("manifest.json", "missing or not valid JSON")
        return rep
    missing = [k for k in REQUIRED_MANIFEST_FIELDS if k not in m]
    if missing:
        rep.fail("manifest.json", f"missing fields: {', '.join(missing)}")
        return rep
    if m["run_id"] != run_id:
        _mismatch(rep, "run_id", m["run_id"], run_id)

    try:
        status = read_json(run_dir / "status.json")
        if status.get("state") != "completed":
            rep.fail(
                "status.state",
                f"is {status.get('state')!r}, not 'completed'"
                + (f" ({status.get('error')})" if status.get("error") else ""),
            )
    except (OSError, ValueError):
        rep.fail("status.json", "missing or not valid JSON")

    # ---- results.json
    results: dict[str, Any] | None = None
    results_path = run_dir / "results.json"
    if not results_path.is_file():
        rep.fail("results.json", "missing")
    else:
        raw = _lf(results_path.read_bytes())
        if m["result_sha256"] is None:
            rep.fail("result_sha256", "the manifest has no result hash (the run did not finish)")
        elif sha256_bytes(raw) != m["result_sha256"]:
            _mismatch(rep, "result_sha256", m["result_sha256"], sha256_bytes(raw), "results.json: ")
        try:
            results = read_json(results_path)
            report.validate_results(results)
            if canonical_bytes(results) != raw:
                rep.fail("results.json", "is not in canonical form (reformatted or edited)")
            if results["seeds"] != m["seeds"]:
                _mismatch(rep, "seeds", m["seeds"], results["seeds"], "results.json seeds: ")
            if results["experiment"] != m["experiment"]:
                _mismatch(rep, "experiment", m["experiment"], results["experiment"])
        except (ValueError, report.ResultsError) as exc:
            rep.fail("results.json", f"invalid: {exc}")
            results = None

    # ---- inputs
    for rel, sha in sorted(m["config_files"].items()):
        _check_file(rep, root, f"config_files[{rel}]", rel, sha, text=True)
    if m["dataset_manifest_path"] is not None:
        _check_file(
            rep, root, "dataset_manifest_sha256", m["dataset_manifest_path"], m["dataset_manifest_sha256"], text=True
        )
    if m["prereg_path"] is not None:
        _check_file(rep, root, "prereg_sha256", m["prereg_path"], m["prereg_sha256"], text=True)
    if m["lock_path"] is not None:
        _check_file(rep, root, "lock_sha256", m["lock_path"], m["lock_sha256"], text=True)
    for art in m["artifacts"]:
        for rel, sha in sorted(art["files"].items()):
            _check_file(rep, root, f"artifacts[{art['model_id']}].files[{rel}]", rel, sha, text=False)

    _check_code(rep, root, m)
    _check_lineage(rep, m)
    _check_platform(rep, m)

    # ---- regenerate tables / figures / REPORT.md from results.json only
    if results is not None:
        _check_generated(rep, run_dir, results)

    # ---- optional full re-execution (level L1)
    if rerun and results is not None and not rep.failures:
        try:
            experiments.get(m["experiment"])
            config = read_json(env.resolve_in_root(m["primary_config"], root))
            again = execute_experiment(
                m["experiment"],
                config,
                list(m["seeds"]),
                digits=m["determinism"]["float_sig_digits"],
                check_determinism=False,
            )
            if canonical_bytes(again) != canonical_bytes(results):
                rep.fail(
                    "results.json",
                    "re-executing the experiment with the recorded config and seeds gives different results",
                )
        except Exception as exc:  # noqa: BLE001
            rep.fail("rerun", f"{type(exc).__name__}: {exc}")
    elif rerun and rep.failures:
        rep.warn("rerun", "skipped because verification already failed")
    return rep

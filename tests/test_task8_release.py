"""Task 8: smoke-test pure parts, and the release/deploy files agree with each other. No network, no Docker."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load_smoke():
    spec = importlib.util.spec_from_file_location("smoke_test_under_test", ROOT / "scripts" / "smoke_test.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module  # dataclasses (postponed annotations) look the module up by name
    spec.loader.exec_module(module)
    return module


st = _load_smoke()
R = st.Response


# --------------------------------------------------------------------------- URL helpers


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://api.example.org", "https://api.example.org"),
        ("https://api.example.org/", "https://api.example.org"),
        (" http://localhost:8000/ ", "http://localhost:8000"),
        ("https://example.org/prefix/?x=1#f", "https://example.org/prefix"),
    ],
)
def test_normalize_base_url(raw, expected):
    assert st.normalize_base_url(raw) == expected


@pytest.mark.parametrize("raw", ["", "example.org", "ftp://example.org", "https://", "https://user:pw@example.org"])
def test_normalize_base_url_rejects(raw):
    with pytest.raises(st.SmokeError):
        st.normalize_base_url(raw)


def test_ws_url_maps_scheme_and_keeps_prefix():
    assert st.ws_url("https://api.example.org") == "wss://api.example.org/ws/live"
    assert st.ws_url("http://localhost:8000/", "ticket=abc") == "ws://localhost:8000/ws/live?ticket=abc"
    assert st.ws_url("https://example.org/prefix") == "wss://example.org/prefix/ws/live"


def test_history_params_are_aware_rfc3339_one_hour():
    now = datetime(2026, 10, 14, 12, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    p = st.history_params(now)
    assert p["to"] == "2026-10-14T06:30:00+00:00"
    assert p["from"] == "2026-10-14T05:30:00+00:00"
    with pytest.raises(st.SmokeError):
        st.history_params(datetime(2026, 10, 14, 12, 0))


# --------------------------------------------------------------------------- response checks


def test_check_healthz():
    assert "ok" in st.check_healthz(R(200, {"status": "ok", "database": "ok"}))
    for bad in (R(503, {"detail": "x"}), R(200, {"status": "degraded"}), R(200, None)):
        with pytest.raises(st.SmokeError):
            st.check_healthz(bad)


def test_check_readyz_names_failing_checks_only():
    assert st.check_readyz(R(200, {"status": "ready"})) == "HTTP 200"
    with pytest.raises(st.SmokeError) as exc:
        st.check_readyz(R(503, {"checks": {"database": "ok", "schema": "behind", "broadcast": "stale"}}))
    assert "broadcast, schema" in str(exc.value)
    assert "database" not in str(exc.value)
    with pytest.raises(st.SmokeError):
        st.check_readyz(R(503, None))


def test_check_login_never_returns_the_token():
    detail = st.check_login(R(200, {"access_token": "SECRET-TOKEN", "refresh_token": "SECRET-R", "role": "viewer"}))
    assert "SECRET" not in detail and "viewer" in detail
    for bad in (R(401, {"detail": "no"}), R(200, {}), R(200, {"access_token": ""}), R(200, [])):
        with pytest.raises(st.SmokeError):
            st.check_login(bad)


def test_check_state():
    assert "1.250" in st.check_state(R(200, {"pue": 1.25, "total_power_kw": 300.0}))
    for bad in (
        R(500, None),
        R(200, []),
        R(200, {"pue": 1.2}),
        R(200, {"pue": "x", "total_power_kw": 1}),
        R(200, {"pue": True, "total_power_kw": 1}),
    ):
        with pytest.raises(st.SmokeError):
            st.check_state(bad)


def test_check_ws_frame():
    assert "seq 7" in st.check_ws_frame(json.dumps({"origin": "simulated", "seq": 7}))
    for bad in (
        "not json",
        "[]",
        json.dumps({"origin": "measured", "seq": 1}),
        json.dumps({"origin": "simulated"}),
        None,
    ):
        with pytest.raises(st.SmokeError):
            st.check_ws_frame(bad)


def test_check_history():
    assert "0 item" in st.check_history(R(200, {"items": []}))
    with pytest.raises(st.SmokeError, match="not found"):
        st.check_history(R(404, None))
    for bad in (R(401, None), R(200, {}), R(200, {"items": "x"})):
        with pytest.raises(st.SmokeError):
            st.check_history(bad)


def test_exit_code_and_format():
    ok, bad = st.CheckResult("a", True, "fine"), st.CheckResult("b", False, "broken")
    assert st.exit_code([ok]) == 0
    assert st.exit_code([ok, bad]) == 1
    assert st.exit_code([]) == 1
    text = st.format_results([ok, bad])
    assert "[PASS] a: fine" in text and "[FAIL] b: broken" in text and "1/2 checks passed, 1 failed" in text


# --------------------------------------------------------------------------- runner with fakes

NOW = lambda: datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)  # noqa: E731


class FakeServer:
    def __init__(self, **overrides):
        self.calls: list[tuple[str, str]] = []
        self.ws_urls: list[str] = []
        self.overrides = overrides

    def http(self, method, url, headers, body):
        self.calls.append((method, url))
        path = url.split("://", 1)[1].split("/", 1)[1].split("?", 1)[0]
        key = f"{method} /{path}"
        if key in self.overrides:
            out = self.overrides[key]
            if isinstance(out, Exception):
                raise out
            return out
        authed = bool(headers and headers.get("Authorization", "").startswith("Bearer "))
        table = {
            "GET /healthz": R(200, {"status": "ok"}),
            "GET /readyz": R(200, {"status": "ready"}),
            "POST /auth/login": R(200, {"access_token": "tok", "role": "viewer"}),
            "POST /auth/ws-ticket": R(200, {"ticket": "tkt", "expires_in": 30}) if authed else R(401, None),
            "GET /api/state": R(200, {"pue": 1.3, "total_power_kw": 100.0}) if authed else R(401, None),
            "GET /api/telemetry/sensors/fac1.it_power_kw/samples": R(200, {"items": []}) if authed else R(401, None),
        }
        return table.get(key, R(404, None))

    def ws(self, url, timeout):
        self.ws_urls.append(url)
        return json.dumps({"origin": "simulated", "seq": 3})


def _run(server, **kw):
    return st.run_smoke("https://api.example.org/", "u", "p", http=server.http, ws=server.ws, now=NOW, **kw)


def test_run_smoke_all_pass_uses_ticket_not_token():
    srv = FakeServer()
    results = _run(srv)
    assert [r.name for r in results] == ["healthz", "readyz", "login", "state", "websocket", "history"]
    assert all(r.ok for r in results), st.format_results(results)
    assert srv.ws_urls == ["wss://api.example.org/ws/live?ticket=tkt"]
    assert "via ticket" in results[4].detail
    assert st.exit_code(results) == 0
    assert any("from=2026-10-14T11%3A00%3A00%2B00%3A00" in url for _, url in srv.calls)


def test_run_smoke_falls_back_to_token_when_no_ticket():
    srv = FakeServer(**{"POST /auth/ws-ticket": R(503, None)})
    results = _run(srv)
    assert results[4].ok and "via token" in results[4].detail
    assert srv.ws_urls == ["wss://api.example.org/ws/live?token=tok"]


def test_run_smoke_failed_login_fails_dependents_not_skips_them():
    srv = FakeServer(**{"POST /auth/login": R(401, {"detail": "bad"})})
    results = {r.name: r for r in _run(srv)}
    assert results["healthz"].ok and results["readyz"].ok
    for name in ("login", "state", "websocket", "history"):
        assert not results[name].ok
    assert "no access token" in results["state"].detail
    assert st.exit_code(list(results.values())) == 1


def test_run_smoke_network_error_reports_type_only():
    srv = FakeServer(**{"GET /api/state": ConnectionError("https://secret-host/leak?token=abc")})
    results = {r.name: r for r in _run(srv)}
    assert not results["state"].ok
    assert results["state"].detail == "ConnectionError"
    assert "secret-host" not in st.format_results(list(results.values()))


def test_run_smoke_readyz_503_fails_but_continues():
    srv = FakeServer(**{"GET /readyz": R(503, {"checks": {"schema": "behind"}})})
    results = {r.name: r for r in _run(srv)}
    assert not results["readyz"].ok and "schema" in results["readyz"].detail
    assert results["history"].ok


def test_run_smoke_output_never_contains_credentials():
    srv = FakeServer()
    out = st.format_results(st.run_smoke("https://x.org", "alice", "hunter2", http=srv.http, ws=srv.ws, now=NOW))
    assert "hunter2" not in out and "tok" not in out.replace("token", "")


def test_main_requires_credentials_and_valid_url(capsys):
    saved = {k: os.environ.pop(k, None) for k in ("SMOKE_USERNAME", "SMOKE_PASSWORD")}
    try:
        assert st.main(["--base-url", "https://api.example.org"]) == 2
        assert "SMOKE_USERNAME" in capsys.readouterr().err
        assert st.main(["--base-url", "nonsense", "--username", "u", "--password", "p"]) == 2
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


# --------------------------------------------------------------------------- deploy files agree


def _dockerfile_cmd() -> str:
    line = next(ln for ln in (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines() if ln.startswith("CMD "))
    argv = json.loads(line[len("CMD ") :])
    assert argv[:2] == ["sh", "-c"]
    return argv[2]


def _procfile_cmd() -> str:
    lines = [ln for ln in (ROOT / "Procfile").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert [ln.split(":", 1)[0] for ln in lines] == [
        "web"
    ], "Procfile must define only `web` (migration runs in the start command)"
    return lines[0].split(":", 1)[1].strip()


def _nixpacks_cmd() -> str:
    raw = (ROOT / "nixpacks.toml").read_bytes()
    assert not raw.startswith((b"\xff\xfe", b"\xfe\xff", b"\xef\xbb\xbf")), "nixpacks.toml must be plain UTF-8, no BOM"
    return tomllib.loads(raw.decode("utf-8"))["start"]["cmd"]


def test_start_command_is_identical_in_dockerfile_procfile_nixpacks():
    docker, proc, nix = _dockerfile_cmd(), _procfile_cmd(), _nixpacks_cmd()
    assert docker == proc == nix
    assert (
        docker.index("api.startup_checks") < docker.index("alembic upgrade head") < docker.index("uvicorn api.main:app")
    )
    assert "${PORT:-8000}" in docker and "RUN_MIGRATIONS:-1" in docker


def test_default_port_agrees_with_dockerfile_env_and_expose():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"\bPORT=8000\b", text) and re.search(r"^EXPOSE 8000$", text, re.M)


def test_nixpacks_python_matches_runtime_txt():
    assert (ROOT / "runtime.txt").read_text().strip() == "python-3.12.10"
    assert (
        "requirements.txt"
        in tomllib.loads((ROOT / "nixpacks.toml").read_text(encoding="utf-8"))["phases"]["build"]["cmds"][0]
    )


# --------------------------------------------------------------------------- release workflow


def _workflow() -> dict:
    return yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"))


def test_release_runs_only_on_semver_tags_never_on_prs():
    wf = _workflow()
    triggers = wf[True] if True in wf else wf["on"]  # PyYAML reads the key `on` as boolean True
    assert set(triggers) == {"push"}
    assert triggers["push"] == {"tags": ["v[0-9]+.[0-9]+.[0-9]+"]}


def test_release_permissions_are_least_privilege():
    wf = _workflow()
    assert wf["permissions"] == {"contents": "read"}
    image = wf["jobs"]["image"]["permissions"]
    assert image == {"contents": "read", "packages": "write", "id-token": "write", "attestations": "write"}
    for name in ("verify", "frontend"):
        assert "packages" not in wf["jobs"][name].get("permissions", {})


def test_release_image_has_provenance_sbom_labels_and_attestation():
    steps = _workflow()["jobs"]["image"]["steps"]
    build = next(s for s in steps if str(s.get("uses", "")).startswith("docker/build-push-action"))
    assert build["with"]["push"] is True
    assert build["with"]["provenance"] == "mode=max" and build["with"]["sbom"] is True
    assert "steps.meta.outputs.labels" in build["with"]["labels"]
    assert any(str(s.get("uses", "")).startswith("actions/attest-build-provenance") for s in steps)
    assert any(str(s.get("uses", "")).startswith("docker/metadata-action") for s in steps)


def test_release_verifies_before_publishing_and_uses_no_extra_secrets():
    wf = _workflow()
    for name in ("image", "frontend"):
        assert wf["jobs"][name]["needs"] == "verify"
    assert set(wf["jobs"]["github-release"]["needs"]) == {"verify", "image", "frontend"}
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert set(re.findall(r"secrets\.([A-Z0-9_]+)", text)) == {"GITHUB_TOKEN"}
    assert "pull_request" not in text


def test_release_does_not_interpolate_untrusted_context_into_shell():
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    for block in re.findall(r"run: \|\n((?:\s{10}.*\n)+)", text):
        assert "${{" not in block, "use env: for context values inside run: scripts"


def test_every_third_party_action_is_listed_in_release_process():
    text = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    doc = (ROOT / "docs" / "release" / "RELEASE_PROCESS.md").read_text(encoding="utf-8")
    uses = set(re.findall(r"uses:\s*([\w./-]+@[\w.]+)", text))
    assert uses
    for action in uses:
        assert action in doc, f"{action} is not listed under 'Third-party actions'"


def test_changelog_follows_keep_a_changelog():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert text.startswith("# Changelog")
    assert "keepachangelog.com" in text and "semver.org" in text
    assert re.search(r"^## \[Unreleased\]$", text, re.M)
    for m in re.finditer(r"^## \[(\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2}$", text, re.M):
        assert m.group(1)

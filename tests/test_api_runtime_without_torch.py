"""T29: the API runtime has no PyTorch and no stable-baselines3, and still boots.

The "API image" is simulated in-process-free: a child Python process installs an import blocker that makes
``import torch`` / ``import stable_baselines3`` fail exactly as in the image (where the packages are not installed), then
imports the app, runs its lifespan against an in-memory database, and calls the endpoints. The Dockerfile and the
requirements split are checked statically in tests/test_requirements_split.py.
"""

import json
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CHILD = textwrap.dedent(
    r"""
    import asyncio, importlib.abc, json, os, sys

    class Blocker(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path, target=None):
            if name.split(".")[0] in ("torch", "stable_baselines3"):
                raise ModuleNotFoundError(f"No module named {name!r}")

    sys.meta_path.insert(0, Blocker())
    sys.path.insert(0, __ROOT__)
    os.environ.update(
        JWT_SECRET_KEY="test-secret-for-suite-only", ENVIRONMENT="development",
        TELEMETRY_STORE_ENABLED="false",
        ANOMALY_SERVER_SIDE="false", RATE_LIMIT_ENABLED="false", HTTP_LIMITS_ENABLED="false",
    )
    out = {}
    try:
        import torch  # noqa: F401
        out["torch_import_failed"] = False
    except ModuleNotFoundError:
        out["torch_import_failed"] = True
    try:
        import stable_baselines3  # noqa: F401
        out["sb3_import_failed"] = False
    except ModuleNotFoundError:
        out["sb3_import_failed"] = True

    import httpx
    import api.main as main
    from api.services import optimization_service as svc

    async def nothing(*a, **k):  # no database or background producers in this process: only the torch-free boot is under test
        return None

    main.init_db = nothing
    main.run_broadcast_loop = nothing

    class StubSession:
        async def execute(self, *a, **k):
            return None

    async def stub_db():
        yield StubSession()

    from database import get_db

    main.app.dependency_overrides[get_db] = stub_db

    async def go():
        async with main.app.router.lifespan_context(main.app):
            transport = httpx.ASGITransport(app=main.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                r = await c.get("/healthz")
                out["healthz"] = r.status_code
        try:
            await svc.run_optimization(0.5, 0.3, 0.2, 0.0, 1)
            out["optimize"] = "served"
        except Exception as exc:
            out["optimize"] = [type(exc).__name__, getattr(exc, "status_code", None), getattr(exc, "detail", None)]

    asyncio.run(go())
    out["torch_loaded"] = "torch" in sys.modules
    out["sb3_loaded"] = "stable_baselines3" in sys.modules
    print("RESULT " + json.dumps(out))
    """
)


def run_child() -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", CHILD.replace("__ROOT__", repr(str(ROOT)))],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=ROOT,
    )
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")), None)
    assert line, f"child failed (rc={proc.returncode}):\n{proc.stdout[-1500:]}\n{proc.stderr[-2500:]}"
    return json.loads(line[len("RESULT ") :])


def test_import_torch_fails_and_the_app_boots_and_serves_probes():
    out = run_child()
    assert out["torch_import_failed"] is True and out["sb3_import_failed"] is True
    assert out["healthz"] == 200
    assert out["torch_loaded"] is False and out["sb3_loaded"] is False


def test_without_a_promoted_policy_optimize_is_503_model_unavailable_in_that_process():
    out = run_child()
    assert out["optimize"] == ["OptimizerUnavailableError", 503, "model_unavailable"]

"""T29: training dependencies are split out of the API's requirements, and the API image cannot contain them."""

import ast
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRAINING_ONLY = ("torch", "stable-baselines3", "stable_baselines3")


def _names(path: Path) -> set[str]:
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            names.add(re.split(r"[=<>!~\[; ]", line, 1)[0].lower().replace("_", "-"))
    return names


def test_api_requirements_exclude_the_training_stack_but_keep_gymnasium():
    names = _names(ROOT / "requirements.txt")
    assert not (names & {"torch", "stable-baselines3"})
    assert "gymnasium" in names  # DataCentreEnv is a gymnasium.Env; the API rolls policies out on it


def test_training_requirements_add_exactly_the_training_stack_on_top_of_the_api_ones():
    text = (ROOT / "requirements-train.txt").read_text(encoding="utf-8")
    assert re.search(r"^-r requirements\.txt$", text, re.M)
    assert _names(ROOT / "requirements-train.txt") == {"stable-baselines3", "torch"}
    assert "stable-baselines3==2.9.0" in text and "torch==2.14.0" in text
    assert "https://download.pytorch.org/whl/cpu" in text


def test_dev_requirements_pull_in_the_training_stack_for_ci_tests():
    assert re.search(r"^-r requirements-train\.txt$", (ROOT / "requirements-dev.txt").read_text(encoding="utf-8"), re.M)


def test_dockerfile_filters_the_lock_and_fails_the_build_if_torch_or_sb3_is_importable():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"pip install .*--require-hashes.* -r requirements\.lock", text)
    assert (
        "--extra-index-url" not in text.split("AS runtime", 1)[0].split("pip install", 1)[1]
    )  # no CPU-torch index needed
    assert "find_spec" in text and "torch" in text and "stable_baselines3" in text
    assert "rm -rf /app/artifacts_training" in text
    filter_pos, install_pos, check_pos = (
        text.index(s) for s in ("RUN python - <<'PY'", "RUN pip install", "find_spec")
    )
    assert filter_pos < install_pos < check_pos  # filter, then install, then verify


def test_the_dockerfile_lock_filter_removes_the_training_stack_and_only_it():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    code = re.search(r"RUN python - <<'PY'\n(.*?)\nPY\n", text, re.S).group(1)
    with tempfile.TemporaryDirectory() as tmp:
        lock = Path(tmp) / "requirements.lock"
        sample = (
            "# header\n"
            "fastapi==0.136.1 \\\n    --hash=sha256:aa \\\n    --hash=sha256:bb\n"
            "torch==2.14.0 \\\n    --hash=sha256:cc\n"
            "stable_baselines3==2.9.0 \\\n    --hash=sha256:dd\n"
            "Jinja2==3.1.6 \\\n    --hash=sha256:ee\n"
            "gymnasium==1.3.0 \\\n    --hash=sha256:ff\n"
            "sympy==1.14.0 \\\n    --hash=sha256:11\n"
            "markupsafe==3.0.3 \\\n    --hash=sha256:22\n"
        )
        lock.write_text(sample, encoding="utf-8")
        subprocess.run([sys.executable, "-c", code], cwd=tmp, check=True, timeout=60)
        kept = lock.read_text(encoding="utf-8")
    assert re.findall(r"^([A-Za-z0-9_.\-]+)==", kept, re.M) == ["fastapi", "gymnasium", "markupsafe"]
    assert "--hash=sha256:cc" not in kept and "--hash=sha256:aa" in kept and kept.startswith("# header")
    # on the real lock it removes exactly the training stack (and what only it needs)
    real = ROOT / "requirements.lock"
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "requirements.lock").write_bytes(real.read_bytes())
        subprocess.run([sys.executable, "-c", code], cwd=tmp, check=True, timeout=60)
        after = (Path(tmp) / "requirements.lock").read_text(encoding="utf-8")
    before_names = set(re.findall(r"^([A-Za-z0-9_.\-]+)==", real.read_text(encoding="utf-8"), re.M))
    removed = before_names - set(re.findall(r"^([A-Za-z0-9_.\-]+)==", after, re.M))
    assert {n.lower() for n in removed} <= {
        "torch",
        "stable_baselines3",
        "jinja2",
        "filelock",
        "fsspec",
        "mpmath",
        "networkx",
        "sympy",
    }
    assert {"torch", "stable_baselines3"} <= {n.lower() for n in removed} or not (
        before_names & {"torch", "stable_baselines3"}
    )


def test_no_api_or_runtime_module_imports_the_training_stack_at_module_level():
    offenders = []
    for base in (
        "api",
        "src/rl/numpy_policy.py",
        "src/rl/env.py",
        "src/artifacts",
        "src/optimizer.py",
        "src/model_registry.py",
    ):
        path = ROOT / base
        files = [path] if path.is_file() else sorted(path.rglob("*.py"))
        for f in files:
            tree = ast.parse(f.read_text(encoding="utf-8"))
            for (
                node
            ) in tree.body:  # module level only: lazy imports inside functions are how training code stays optional
                mods = (
                    [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                    if isinstance(node, ast.ImportFrom)
                    else []
                )
                if any(m.split(".")[0] in ("torch", "stable_baselines3") for m in mods):
                    offenders.append(str(f.relative_to(ROOT)))
    assert offenders == []


def test_the_api_service_never_imports_the_exporter_or_the_sb3_loader():
    src = (ROOT / "api" / "services" / "optimization_service.py").read_text(encoding="utf-8")
    assert "src.rl.export" not in src and "load_sb3_zip" not in src and "stable_baselines3" not in src
    assert "src.rl.numpy_policy" in src

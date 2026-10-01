"""SHA-256 tree hash of the production directories (T0 acceptance criterion 4).

    python -m tests.characterization.tools.tree_hash

Run before and after the T0 suite is added/executed; the two outputs must be identical.
__pycache__, *.pyc and node_modules are excluded (interpreter/tool artefacts, not source).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DIRS = ("api", "src", "models", "alembic", "twin-stream-insight-main/src", "notebooks", "scripts")


def tree_hash() -> str:
    h = hashlib.sha256()
    for d in DIRS:
        base = ROOT / d
        for p in sorted(base.rglob("*")):
            if not p.is_file() or "__pycache__" in p.parts or "node_modules" in p.parts or p.suffix == ".pyc":
                continue
            h.update(p.relative_to(ROOT).as_posix().encode())
            h.update(b"\0")
            h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


if __name__ == "__main__":
    print(tree_hash())

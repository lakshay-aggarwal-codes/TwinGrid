"""Protocol tests use SYNTHETIC data only; they never read realData. Repo root is derived from this file's location."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

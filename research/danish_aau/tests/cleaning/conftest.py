"""Cleaning tests use SYNTHETIC fixtures only (year-2000 timestamps, patterned values); they never read realData."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

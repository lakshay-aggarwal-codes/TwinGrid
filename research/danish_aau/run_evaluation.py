"""Run the evaluation harness from ANY working directory:

    python research/danish_aau/run_evaluation.py doctor

The repository root is derived from this file's location (never from the current directory) and put on sys.path.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research.danish_aau.evaluation.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())

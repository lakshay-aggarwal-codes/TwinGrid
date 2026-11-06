"""CP-9: evaluate the Copilot docs RAG on the golden questions. Offline by default (fake providers, no network).

    python scripts/copilot_eval.py                         # summary; exit code 1 if a gate fails, 2 if blocked
    python scripts/copilot_eval.py --write-report          # also rewrite docs/copilot/EVAL_REPORT.md
    python scripts/copilot_eval.py --json out.json         # raw numbers
    python scripts/copilot_eval.py --real --real-limit 10  # OPTIONAL: SENDS questions and doc passages to the
                                                           # providers configured in COPILOT_LLM_* (see docs/copilot)

The engine is ``tests/copilot_eval/harness.py``; the questions are ``tests/copilot_eval/questions.yaml``. Needs PyYAML
(already in requirements-dev.txt). Standard library plus the repository's own modules otherwise.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.copilot_eval.harness import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())

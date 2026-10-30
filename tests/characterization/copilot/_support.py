"""Shared helpers for the CP-0 Copilot characterization tests (not collected: the name does not start with ``test_``).

Goldens live next to the tests in ``golden/``. A golden test FAILS when the stored JSON differs from what the code now
produces. To accept an intended change, re-run with ``COPILOT_CHAR_UPDATE=1`` (PowerShell: ``$env:COPILOT_CHAR_UPDATE="1"``),
review the diff, then unset it. Without that variable nothing is ever written.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
from pathlib import Path
from typing import Any

from src.copilot import answer
from tests.fixtures.copilot.helpers import make_ctx

GOLDEN = Path(__file__).parent / "golden"
UPDATE_ENV = "COPILOT_CHAR_UPDATE"

# A small fixed catalogue so goldens do not move when docs/copilot/capabilities.json is edited by later tasks.
CATALOGUE = [
    {
        "id": "alerts_centre",
        "title": "Alerts centre",
        "description": "Anomaly alerts with an incident workflow and an explanation of why each alert fired.",
        "ui_path": "/alerts",
        "api_paths": ["/api/alerts"],
    },
    {
        "id": "what_if_lab",
        "title": "What-if lab",
        "description": "Runs the simulator under changed load or ambient temperature and shows the differences.",
        "ui_path": "/whatif-lab",
        "api_paths": ["/api/whatif"],
    },
    {
        "id": "fleet_view",
        "title": "Fleet view",
        "description": "Ranks simulated sites by PUE and carbon.",
        "ui_path": "/fleet",
        "api_paths": ["/api/fleet/sites"],
    },
]


def run(question: str, kind: str = "general", cid: str | None = None, history: list | None = None, **ctx_kw: Any):
    """Build the rule-based (or env-configured LLM) answer exactly as the route does, with fixture loaders."""
    inp = answer.AskInput(question=question, kind=kind, context_id=cid, history=history or [])
    ctx_kw.setdefault("catalogue", CATALOGUE)
    return asyncio.run(answer.answer_question(inp, make_ctx(**ctx_kw)))


def snapshot(result: Any) -> dict[str, Any]:
    """The whole ``Answer`` as plain JSON-able data."""
    return json.loads(json.dumps(dataclasses.asdict(result), sort_keys=True))


def check_golden(relpath: str, data: Any) -> None:
    path = GOLDEN / relpath
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    if os.environ.get(UPDATE_ENV) == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return
    assert path.exists(), f"missing golden {relpath}; generate it with {UPDATE_ENV}=1 and review it"
    assert json.loads(path.read_text(encoding="utf-8")) == json.loads(text), (
        f"golden {relpath} differs from current behaviour. If the change is intended, re-run with {UPDATE_ENV}=1 and "
        "review the diff."
    )

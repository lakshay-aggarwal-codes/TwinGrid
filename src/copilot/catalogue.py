"""The capability catalogue: a curated list of REAL features (``docs/copilot/capabilities.json``).

``find_feature`` is a deterministic keyword match over the catalogue, nothing else: a feature that is not listed is not
offered. ``tests/test_copilot_catalogue.py`` checks every ``ui_path`` against the frontend route strings and every
``api_path`` against the OpenAPI document, so the catalogue cannot point at something that does not exist.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

CATALOGUE_PATH = Path(__file__).resolve().parents[2] / "docs" / "copilot" / "capabilities.json"
FIELDS = ("id", "title", "description", "ui_path", "api_paths")
_STOP = frozenset(
    "what the this that how does where can find page feature about show with for and are you was why who which its into"
    " tell give open use used from have has not any".split()
)


def load_catalogue(path: Path | None = None) -> list[dict[str, Any]]:
    """The validated catalogue. Raises ``ValueError`` on a malformed file (a broken catalogue must not be half-used)."""
    try:
        doc = json.loads((path or CATALOGUE_PATH).read_text(encoding="utf-8"))
        features = doc["features"]
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError("the capability catalogue is missing or unreadable") from None
    seen: set[str] = set()
    for f in features:
        ok = isinstance(f, dict) and set(f) == set(FIELDS) and all(isinstance(f[k], str) and f[k] for k in FIELDS[:4])
        ok = (
            ok
            and isinstance(f["api_paths"], list)
            and all(isinstance(p, str) and p.startswith("/") for p in f["api_paths"])
        )
        ok = ok and f["ui_path"].startswith("/") and f["id"] not in seen
        if not ok:
            raise ValueError("the capability catalogue has a malformed or duplicate entry")
        seen.add(f["id"])
    return features


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) >= 3 and w not in _STOP}


def find_feature(query: str, catalogue: list[dict[str, Any]] | None = None, limit: int = 3) -> list[dict[str, Any]]:
    """Catalogue entries whose id, title or description share words with ``query``, best first (ties: catalogue order)."""
    entries = catalogue if catalogue is not None else load_catalogue()
    wanted = _words(query)
    scored = []
    for order, f in enumerate(entries):
        title_hits = len(wanted & _words(f["title"] + " " + f["id"].replace("_", " ")))
        body_hits = len(wanted & _words(f["description"]))
        score = 3 * title_hits + body_hits
        if score:
            scored.append((-score, order, f))
    return [dict(f) for _, _, f in sorted(scored, key=lambda t: (t[0], t[1]))[:limit]]


def get_feature(feature_id: str, catalogue: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    for f in catalogue if catalogue is not None else load_catalogue():
        if f["id"] == feature_id:
            return dict(f)
    return None

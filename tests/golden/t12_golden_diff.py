"""T12 golden diff tool: proves a golden regeneration changed ONLY timestamp fields.

Usage (from the repo root)::

    python -m tests.golden.t12_golden_diff BEFORE_DIR AFTER_DIR [--report PATH]
    python -m tests.golden.t12_golden_diff --apply AFTER_DIR CHECKED_IN_DIR [--report PATH]

* compare mode: walks every ``*.json`` present in both dirs and classifies each difference as a
  timestamp-field change (last path key in ``TIMESTAMP_KEYS``) or ANYTHING ELSE. Exit status is 1 if
  anything else differs, so a numeric change can never be hidden inside a timestamp regeneration.
* ``--apply``: surgically rewrites ONLY timestamp-field values in the checked-in goldens' ``data``
  block with the values from AFTER_DIR, for paths that exist in both. No other byte-level value
  (numerics, keys, metadata) is touched.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Iterator

# scored_at is wall-clock noise from anomaly_service (not frozen by the harness; differs on every run).
TIMESTAMP_KEYS = frozenset({"timestamp", "time", "sim_time", "ts_ingest", "scored_at"})


Key = tuple  # path as a tuple of dict keys / list indices (case ids contain dots, so never parse strings)


def _walk(a: Any, b: Any, path: Key = ()) -> Iterator[tuple[Key, Any, Any]]:
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                yield path + (k,), "<absent>", b[k]
            elif k not in b:
                yield path + (k,), a[k], "<absent>"
            else:
                yield from _walk(a[k], b[k], path + (k,))
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            yield from _walk(x, y, path + (i,))
    elif a != b or type(a) is not type(b):
        yield path, a, b


def fmt(path: Key) -> str:
    return "$" + "".join(f"[{k}]" if isinstance(k, int) else f".{k}" for k in path)


def is_timestamp_path(path: Key) -> bool:
    return bool(path) and path[-1] in TIMESTAMP_KEYS


def compare(before: dict[str, Any], after: dict[str, Any]) -> tuple[list[tuple], list[tuple]]:
    ts, other = [], []
    for path, x, y in _walk(before, after):
        (ts if is_timestamp_path(path) else other).append((path, x, y))
    return ts, other


def _set_path(root: Any, path: Key, value: Any) -> bool:
    node = root
    for k in path[:-1]:
        try:
            node = node[k]
        except (KeyError, IndexError, TypeError):
            return False
    node[path[-1]] = value
    return True


def apply_timestamps(after_dir: Path, golden_dir: Path) -> dict[str, int]:
    """Rewrite timestamp-field values in checked-in goldens from ``after_dir``. Returns counts."""
    counts: dict[str, int] = {}
    for f in sorted(after_dir.glob("*.json")):
        target = golden_dir / f.name
        if not target.exists():
            continue
        after = json.loads(f.read_text())
        doc = json.loads(target.read_text())
        n = 0
        for path, x, y in list(_walk(doc["data"], after)):
            if is_timestamp_path(path) and x != "<absent>" and y != "<absent>":
                if _set_path(doc["data"], path, y):
                    n += 1
        target.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        counts[f.name] = n
    return counts


def report(before_dir: Path, after_dir: Path) -> tuple[str, bool]:
    lines = ["| golden | timestamp-field diffs | non-timestamp diffs |", "|---|---|---|"]
    samples: list[str] = []
    clean = True
    for f in sorted(before_dir.glob("*.json")):
        g = after_dir / f.name
        if not g.exists():
            lines.append(f"| {f.stem} | (missing in after) | - |")
            clean = False
            continue
        ts, other = compare(json.loads(f.read_text()), json.loads(g.read_text()))
        clean &= not other
        lines.append(f"| {f.stem} | {len(ts)} | {len(other)} |")
        for path, x, y in ts[:2]:
            samples.append(f"- `{f.stem}` `{fmt(path)}`: `{x}` -> `{y}`")
        for path, x, y in other[:10]:
            samples.append(f"- **NON-TIMESTAMP** `{f.stem}` `{fmt(path)}`: `{x}` -> `{y}`")
    return "\n".join(lines + ["", "Samples:", *samples]) + "\n", clean


def main(argv: list[str]) -> int:
    rep = None
    if "--report" in argv:
        i = argv.index("--report")
        rep = Path(argv[i + 1])
        argv = argv[:i] + argv[i + 2 :]
    if argv and argv[0] == "--apply":
        counts = apply_timestamps(Path(argv[1]), Path(argv[2]))
        print(json.dumps(counts, indent=2))
        return 0
    text, clean = report(Path(argv[0]), Path(argv[1]))
    print(text)
    if rep:
        rep.write_text(text, encoding="utf-8")
    return 0 if clean else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))

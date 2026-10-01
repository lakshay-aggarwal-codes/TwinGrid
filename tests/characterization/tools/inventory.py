"""Resolve the roadmap's "330 defs vs 214 passing" discrepancy (T0 constraint 8).

    python -m tests.characterization.tools.inventory

Counts, per file: `def test_` occurrences (text), pytest-collected items (parametrisation expands them),
and files pytest's ``python_files = test_*.py`` setting never collects.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TESTS = ROOT / "tests"


def main() -> None:
    text_counts: Counter[str] = Counter()
    for p in sorted(TESTS.rglob("*.py")):
        if "characterization" in p.parts:
            continue
        n = len(re.findall(r"^\s*(?:async\s+)?def test_", p.read_text(encoding="utf-8"), flags=re.M))
        if n:
            text_counts[p.relative_to(ROOT).as_posix()] = n
    out = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-o",
            "addopts=",
            "-p",
            "no:cacheprovider",
            "--ignore=tests/characterization",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).stdout
    collected: Counter[str] = Counter()
    for line in out.splitlines():
        if "::" in line:
            collected[line.split("::")[0]] += 1
    print(f"{'file':55} {'def test_':>9} {'collected':>9}")
    for f in sorted(set(text_counts) | set(collected)):
        print(f"{f:55} {text_counts[f]:9d} {collected[f]:9d}")
    print(f"{'TOTAL':55} {sum(text_counts.values()):9d} {sum(collected.values()):9d}")
    never = [f for f in text_counts if f not in collected]
    print("files with test defs that pytest never collects:", never or "none")


if __name__ == "__main__":
    main()

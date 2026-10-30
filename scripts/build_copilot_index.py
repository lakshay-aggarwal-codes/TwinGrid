"""CP-6: build, check or query the Copilot docs index. Standard library only.

    python scripts/build_copilot_index.py                       # build data/copilot/docs_index.sqlite
    python scripts/build_copilot_index.py --check               # exit 0 if fresh, 1 if stale/missing/incompatible
    python scripts/build_copilot_index.py --query "how do I rotate secrets"

``COPILOT_DOCS_INDEX_PATH`` or ``--out`` moves the file. The index is a build artifact and is never committed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.copilot.rag import index as rag_index  # noqa: E402
from src.copilot.rag import search as rag_search  # noqa: E402


def _build(args: argparse.Namespace) -> int:
    result = rag_index.build_index(args.out, ROOT, tuple(args.extra_allow))
    print(f"built {result.path}")
    print(f"documents={result.documents} chunks={result.chunks} terms={result.terms}")
    print(f"fingerprint={result.fingerprint[:16]}")
    for path, reason in result.skipped:
        print(f"skipped {path}: {reason}")
    for path in result.missing:
        print(f"MISSING allow-listed path: {path}")
    return 0


def _check(args: argparse.Namespace) -> int:
    status = rag_index.check_freshness(args.out or rag_index.default_index_path(), ROOT)
    print(f"status={status.status}" + (f" ({status.reason})" if status.reason else ""))
    for label, items in (("changed", status.changed), ("added", status.added), ("removed", status.removed)):
        for item in items:
            print(f"  {label}: {item}")
    if not status.usable:
        print("rebuild with: python scripts/build_copilot_index.py")
    return 0 if status.usable else 1


def _query(args: argparse.Namespace) -> int:
    try:
        index = rag_index.load_index(args.out or rag_index.default_index_path())
    except rag_index.IndexUnavailable as exc:
        print(f"index {exc.status}: {exc.reason}. Build it first.")
        return 2
    result = rag_search.search(index, args.query, args.k, min_score=args.min_score)
    print(
        f"terms={list(result.terms)} best_score={result.best_score} threshold={result.min_score} reason={result.reason}"
    )
    for hit in result.hits:
        snippet = " ".join(hit.chunk.text.split())[:160]
        print(f"{hit.rank}. {hit.score:.2f} cov={hit.coverage:.2f} {hit.chunk.source_path} > {hit.chunk.heading_path}")
        print(f"   matched={list(hit.matched_terms)} id={hit.chunk.chunk_id}")
        print(f"   {snippet}")
    if not result.hits:
        print("no documented answer found")
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--out", type=Path, default=None, help="index file (default: env or data/copilot/docs_index.sqlite)"
    )
    parser.add_argument(
        "--extra-allow", action="append", default=[], help="extra repo-relative file or folder (repeatable)"
    )
    parser.add_argument("--check", action="store_true", help="report whether the index matches the documents")
    parser.add_argument("--query", help="search the index instead of building it")
    parser.add_argument("-k", type=int, default=rag_search.DEFAULT_K)
    parser.add_argument(
        "--min-score", type=float, default=None, help="override the placeholder threshold (0 shows everything)"
    )
    args = parser.parse_args(argv)
    try:
        if args.query is not None:
            return _query(args)
        if args.check:
            return _check(args)
        return _build(args)
    except (rag_index.IndexUnavailable, ValueError) as exc:
        print(f"error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

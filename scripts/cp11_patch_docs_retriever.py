"""CP-11 one-off: let ``DocsRetriever`` take ``min_coverage`` (CP-9 left this pass-through undone in some checkouts).

    python scripts/cp11_patch_docs_retriever.py            # edit src/copilot/docs_answer.py in place
    python scripts/cp11_patch_docs_retriever.py --check    # only report

Without it ``python scripts/copilot_eval.py`` stops with ``TypeError: DocsRetriever.__init__() got an unexpected keyword
argument 'min_coverage'``. The running product is not affected (the shared retriever takes both fitted floors from
``rag/search.py``). Writes nothing unless all three anchors are found exactly once; safe to re-run.
"""

from __future__ import annotations

import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parent.parent / "src" / "copilot" / "docs_answer.py"
EDITS = (
    (
        "        min_score: float | None = None,\n        ttl_s: float = DEFAULT_TTL_S,\n",
        "        min_score: float | None = None,\n        min_coverage: float | None = None,\n        ttl_s: float = DEFAULT_TTL_S,\n",
    ),
    (
        "        self._min_score = min_score\n",
        "        self._min_score = min_score\n        self._min_coverage = min_coverage\n",
    ),
    (
        "rag_search.search(index, search_query(question), self._k, min_score=self._min_score)",
        "rag_search.search(\n                index, search_query(question), self._k, min_score=self._min_score, min_coverage=self._min_coverage\n            )",
    ),
)


def main(argv: list[str]) -> int:
    text = TARGET.read_text(encoding="utf-8")
    if "self._min_coverage" in text:
        print("already patched: nothing to do")
        return 0
    for old, _ in EDITS:
        count = text.count(old)
        if count != 1:
            print(f"BLOCKED: anchor found {count} times (need 1) in {TARGET.name}:\n{old}")
            return 2
    if "--check" in argv:
        print("patch applies cleanly (all 3 anchors found once)")
        return 0
    for old, new in EDITS:
        text = text.replace(old, new, 1)
    TARGET.write_text(text, encoding="utf-8", newline="\n")
    print(f"patched {TARGET.name}: DocsRetriever(min_coverage=...) now reaches rag_search.search")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

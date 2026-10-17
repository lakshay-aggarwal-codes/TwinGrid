"""Task 33: the claims ledger backs the README and the judges pack, and the overclaim words stay out.

No network, no database, no browser. Every evidence path must exist; every ``[C-nn]`` tag must be a ledger row; every claim
line in the README's claim sections must carry a tag.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUSES = {"fact", "result", "assumption", "hypothesis", "future"}
TAG = re.compile(r"\[(C-\d{2})\]")
CLAIM_SECTIONS = (
    "What it is, and what it is not",
    "Feature tour",
    "What the machine-learning results show",
    "Engineering",
    "Status",
)


def _text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _rows() -> list[dict]:
    rows = []
    for line in _text("docs/CLAIMS.md").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 5 and re.fullmatch(r"C-\d{2}", cells[0]):
            rows.append(
                {"id": cells[0], "claim": cells[1], "status": cells[2], "evidence": cells[3], "boundary": cells[4]}
            )
    return rows


def test_ledger_rows_are_complete_and_unique():
    rows = _rows()
    assert len(rows) >= 30
    assert len({r["id"] for r in rows}) == len(rows)
    for r in rows:
        assert r["status"] in STATUSES, r["id"]
        assert r["claim"].endswith("."), r["id"]
        assert len(r["boundary"]) > 10, r["id"]


def test_every_evidence_path_exists():
    for r in _rows():
        paths = re.findall(r"`([^`]+)`", r["evidence"])
        assert paths, f"{r['id']}: no evidence path"
        for p in paths:
            assert (ROOT / p).exists(), (r["id"], p)


def test_hypotheses_and_future_items_are_not_worded_as_met():
    for r in _rows():
        if r["status"] in {"hypothesis", "future"}:
            assert re.search(
                r"\b(not|unmeasured|never|harness only|nothing|needs)\b", (r["claim"] + " " + r["boundary"]).lower()
            ), r["id"]


def _sections(md: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    current = None
    for line in md.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            out[current] = []
        elif current is not None:
            out[current].append(line)
    return out


def test_every_readme_claim_line_carries_a_ledger_id():
    ids = {r["id"] for r in _rows()}
    readme = _text("README.md")
    assert set(TAG.findall(readme)) <= ids
    sections = _sections(readme)
    for name in CLAIM_SECTIONS:
        assert name in sections, name
        bullets = [ln for ln in sections[name] if ln.startswith("- ")]
        assert bullets, name
        for ln in bullets:
            assert TAG.search(ln), (name, ln[:80])
            assert set(TAG.findall(ln)) <= ids


def test_every_readme_claim_that_is_a_ledger_row_is_in_the_readme_or_judges():
    used = set(TAG.findall(_text("README.md"))) | set(TAG.findall(_text("docs/JUDGES.md")))
    missing = {r["id"] for r in _rows()} - used
    assert missing == set(), f"ledger rows used nowhere: {sorted(missing)}"


def test_judges_pack_is_tagged_and_has_ten_questions():
    ids = {r["id"] for r in _rows()}
    judges = _text("docs/JUDGES.md")
    assert set(TAG.findall(judges)) <= ids
    questions = re.findall(r"^\d+\. \*\*", judges, flags=re.M)
    assert len(questions) == 10
    for ln in judges.splitlines():
        if re.match(r"^\d+\. \*\*", ln) or ln.startswith("| 0:") or re.match(r"^\| \d:\d\d", ln):
            assert TAG.search(ln), ln[:80]
    assert "DEMO_CHECKLIST.md" in judges and (ROOT / "docs" / "DEMO_CHECKLIST.md").exists()


BANNED = [
    (r"production[- ]ready", "production-ready"),
    (r"(?<!simulator-)(?<!not )(?<!un)(?<!never )\bvalidated\b", "validated"),
    (r"(?<!un)(?<!not )\bcalibrated\b", "calibrated"),
    (r"\breal[- ]time\b", "real-time"),
    (r"digital twin of a real", "digital twin of a real facility"),
    (r"\boptimal\b", "optimal"),
    (r"ai[- ]optimi[sz]ed", "AI-optimized"),
    (r"state[- ]of[- ]the[- ]art", "state-of-the-art"),
]


def _outside_banned_block(md: str) -> str:
    return re.sub(r"<!-- banned-terms:start -->.*?<!-- banned-terms:end -->", "", md, flags=re.S)


def test_overclaim_words_are_absent_from_the_public_documents():
    for rel in (
        "README.md",
        "docs/CLAIMS.md",
        "docs/JUDGES.md",
        "docs/DEMO_CHECKLIST.md",
        "PERFORMANCE_OPTIMIZATION.md",
    ):
        text = _outside_banned_block(_text(rel))
        for line in text.splitlines():
            low = line.lower()
            if "allowed:" in low or low.startswith("> **status (task 33)"):
                continue  # the sentences that name the words in order to forbid them
            for pattern, label in BANNED:
                assert not re.search(pattern, low), (rel, label, line[:100])


def test_the_frontend_does_not_ship_the_hard_overclaims():
    hits = []
    for path in (ROOT / "twin-stream-insight-main" / "src").rglob("*.ts*"):
        if ".test." in path.name or "testFixtures" in path.name:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in (
            r"production[- ]ready",
            r"ai[- ]optimi[sz]ed",
            r"state[- ]of[- ]the[- ]art",
            r"digital twin of a real",
        ):
            if re.search(pattern, text, flags=re.I):
                hits.append((path.name, pattern))
    assert hits == []

#!/usr/bin/env python3
"""Task 26 (SHOW-001): build the data behind the Evidence page from the repository's own documents.

Standard library only. Reads

* ``docs/CLAIMS.md``                                  -> ``claims.json``
* ``docs/model_cards/LIMITATIONS.md``                 -> ``limitations.json``
* ``reports/policy_evaluation_physics1/**/results.json`` -> ``ppo_result.json``
* ``evidence/status.json`` (optional, filled by the integrator with real run results) -> ``status.json``
* a short checked list of source files per skill area  -> ``skills.json``

and writes them to ``twin-stream-insight-main/src/features/evidence/generated/``.

Rules this script follows (they are the point of the page):

* A missing source is recorded as ``"not recorded"``. Nothing is invented, estimated or filled in.
* Output is deterministic (sorted keys, no build timestamp), so ``--check`` can tell stale from fresh.
* An invalid ``evidence/status.json`` stops the build; it is never silently dropped.
* Every path listed in ``skills.json`` must exist, or the build fails.

Usage (from the repository root)::

    python scripts/build_evidence.py            # write the generated JSON
    python scripts/build_evidence.py --check    # exit 1 if any generated file is missing or stale

``evidence/status.json`` format (all keys optional except ``checks``)::

    {"recorded_at": "2026-10-21", "commit": "abc1234", "note": "...",
     "checks": [{"name": "backend tests", "command": "pytest tests -m \\"not postgres\\"",
                 "result": "pass", "counts": "123 passed, 4 skipped", "log_path": "reports/..."}]}

``result`` must be one of: pass, fail, skipped, not-run.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

NOT_RECORDED = "not recorded"
ROOT = Path(__file__).resolve().parent.parent
OUT_REL = "twin-stream-insight-main/src/features/evidence/generated"
CLAIMS_REL = "docs/CLAIMS.md"
LIMITS_REL = "docs/model_cards/LIMITATIONS.md"
PPO_DIR_REL = "reports/policy_evaluation_physics1"
STATUS_REL = "evidence/status.json"

CLAIM_KINDS = ("fact", "result", "assumption", "hypothesis", "future")
CHECK_RESULTS = ("pass", "fail", "skipped", "not-run")
POLICY_FIELDS = ("total_reward", "energy_kwh", "water_L", "mean_pue")

# Which files show which skill. Each path is verified to exist when the page data is built.
SKILLS: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    (
        "security",
        "Security engineering",
        (
            ("api/auth.py", "Short-lived tokens, rotating refresh tokens, roles"),
            ("api/plugins/ws_tickets.py", "Single-use WebSocket tickets"),
            ("api/plugins/login_lockout.py", "Login lockout"),
            ("api/plugins/security.py", "Security headers"),
            ("src/log_redaction.py", "Secret redaction in logs"),
            ("docs/security/THREAT_MODEL.md", "Threat model"),
        ),
    ),
    (
        "realtime",
        "Real-time systems",
        (
            ("api/supervisor.py", "Live broadcast loop"),
            (
                "twin-stream-insight-main/src/features/realtime-resilience/index.ts",
                "Reconnect with jitter, gap back-fill",
            ),
            ("docs/architecture/data_flow.md", "Request-time and training-time flows"),
        ),
    ),
    (
        "ml",
        "ML rigor",
        (
            ("reports/policy_evaluation_physics1/PREREGISTRATION.md", "Pre-registered evaluation protocol"),
            (
                "reports/policy_evaluation_physics1/full_0fcafef9d28fd539/REPORT.md",
                "Decision-gate report, kept as it came out",
            ),
            ("src/artifacts/loaders.py", "Artifact gate for model loading"),
            ("docs/model_cards/LIMITATIONS.md", "Shared limitations of every model"),
        ),
    ),
    (
        "ux",
        "Product and UX",
        (
            ("twin-stream-insight-main/src/provenance/labels.ts", "Origin and simulated labels"),
            ("twin-stream-insight-main/src/features/alerts-centre/index.ts", "Alerts centre"),
            ("twin-stream-insight-main/src/features/replay/index.ts", "Replay and time travel"),
            ("twin-stream-insight-main/src/features/what-if-lab/index.ts", "What-if lab"),
        ),
    ),
    (
        "devops",
        "Delivery discipline",
        (
            (".github/workflows/ci.yml", "CI workflow"),
            ("tests/test_alembic_chain.py", "Single migration head, checked by a test"),
            ("docs/runbooks/README.md", "Runbooks"),
            ("docs/CLAIMS.md", "Claims ledger"),
        ),
    ),
)


class EvidenceError(Exception):
    """A source exists but cannot be trusted; the build stops instead of guessing."""


def _read(root: Path, rel: str) -> str | None:
    p = root / rel
    return p.read_text(encoding="utf-8") if p.is_file() else None


def _split_row(line: str) -> list[str]:
    """Split a markdown table row on pipes that are not inside backticks."""
    cells: list[str] = []
    buf: list[str] = []
    in_code = False
    for ch in line.strip().strip("|"):
        if ch == "`":
            in_code = not in_code
        if ch == "|" and not in_code:
            cells.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    cells.append("".join(buf).strip())
    return cells


def _plain(text: str) -> str:
    """Markdown emphasis and code ticks removed; whitespace collapsed. Wording is otherwise untouched."""
    text = text.replace("**", "").replace("`", "")
    return re.sub(r"\s+", " ", text).strip()


def parse_claims(md: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in md.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = _split_row(line)
        if len(cells) != 5 or not re.fullmatch(r"C-\d{2,}", cells[0]):
            continue
        kind = cells[2].strip().lower()
        if kind not in CLAIM_KINDS:
            raise EvidenceError(f"{CLAIMS_REL}: {cells[0]} has unknown status {cells[2]!r}")
        rows.append(
            {
                "id": cells[0],
                "text": _plain(cells[1]),
                "kind": kind,
                "evidence_paths": re.findall(r"`([^`]+)`", cells[3]),
                "limit": _plain(cells[4]),
            }
        )
    ids = [r["id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise EvidenceError(f"{CLAIMS_REL}: duplicate claim ids")
    return rows


# Sections of LIMITATIONS.md that are guidance for authors, not limitations of the system.
_SKIP_SECTIONS = re.compile(r"wording rules", re.I)


def parse_limitations(md: str) -> dict[str, Any]:
    sections: list[dict[str, Any]] = []
    model_status: list[dict[str, str]] = []
    cur: dict[str, Any] | None = None
    para: list[str] = []
    bullet: list[str] | None = None
    in_status_table = False

    def flush_para() -> None:
        nonlocal para
        if para and cur is not None:
            cur["items"].append({"title": "", "text": _plain(" ".join(para))})
        para = []

    def flush_bullet() -> None:
        nonlocal bullet
        if bullet and cur is not None:
            raw = " ".join(bullet)
            m = re.match(r"\*\*(.+?)\*\*\s*(.*)", raw)
            title, text = (m.group(1), m.group(2)) if m else ("", raw)
            cur["items"].append({"title": _plain(title), "text": _plain(text)})
        bullet = None

    for line in md.splitlines():
        h = re.match(r"##\s+(?:(\d+)\.\s+)?(.*\S)\s*$", line)
        if h:
            flush_para()
            flush_bullet()
            title = _plain(h.group(2))
            in_status_table = bool(re.search(r"unevaluated or negative", title, re.I))
            if _SKIP_SECTIONS.search(title):
                cur = None
                continue
            cur = {"id": h.group(1) or str(len(sections) + 1), "title": title, "items": []}
            sections.append(cur)
            continue
        if cur is None:
            continue
        if line.lstrip().startswith("|"):
            flush_para()
            flush_bullet()
            cells = _split_row(line)
            if in_status_table and len(cells) == 2 and not set(cells[0]) <= set("-: ") and cells[0].lower() != "model":
                model_status.append({"model": _plain(cells[0]), "statement": _plain(cells[1])})
            continue
        if line.startswith("- "):
            flush_para()
            flush_bullet()
            bullet = [line[2:].strip()]
        elif line.startswith("  ") and bullet is not None and line.strip():
            bullet.append(line.strip())
        elif not line.strip():
            flush_para()
            flush_bullet()
        elif not line.startswith("#"):
            flush_bullet()
            para.append(line.strip())
    flush_para()
    flush_bullet()
    return {
        "source": LIMITS_REL,
        "model_status": model_status,
        "sections": [s for s in sections if s["items"]],
    }


def _round(v: Any) -> Any:
    return round(v, 4) if isinstance(v, float) else v


def _load_ppo_run(root: Path, path: Path) -> dict[str, Any]:
    rel = path.relative_to(root).as_posix()
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EvidenceError(f"{rel}: not readable JSON ({exc})") from exc
    dec = d.get("decision") or {}
    summary = d.get("summary_test_mean_per_episode") or {}
    policies = []
    for name in sorted(summary):
        row = {"policy": name}
        for f in POLICY_FIELDS:
            v = summary[name].get(f)
            row[f] = _round(v) if isinstance(v, (int, float)) else NOT_RECORDED
        policies.append(row)
    test_set = (d.get("scenario_sets") or {}).get("test") or {}
    return {
        "source_path": rel,
        "outcome": dec.get("outcome", NOT_RECORDED),
        "claim_allowed": dec.get("claim_allowed", NOT_RECORDED),
        "reason": dec.get("reason", NOT_RECORDED),
        "selected_seed": dec.get("selected_seed", NOT_RECORDED),
        "physics_version_executed": d.get("physics_version_executed", NOT_RECORDED),
        "carbon_is_real": (d.get("carbon") or {}).get("is_real", NOT_RECORDED),
        "preregistration_sha256": d.get("preregistration_sha256", NOT_RECORDED),
        "scenario_set_id": d.get("scenario_set_id", NOT_RECORDED),
        "n_test_scenarios": test_set.get("n", NOT_RECORDED),
        "best_constant": ((d.get("selection") or {}).get("best_constant") or {}).get("name", NOT_RECORDED),
        "generated_at_utc": (d.get("environment") or {}).get("generated_at_utc", NOT_RECORDED),
        "policies": policies,
    }


def build_ppo(root: Path) -> dict[str, Any]:
    base = root / PPO_DIR_REL
    paths = sorted(base.rglob("results.json")) if base.is_dir() else []
    if not paths:
        return {
            "outcome": NOT_RECORDED,
            "claim_allowed": NOT_RECORDED,
            "reason": NOT_RECORDED,
            "runs": [],
            "policies": [],
            "policies_source": NOT_RECORDED,
        }
    runs = [_load_ppo_run(root, p) for p in paths]
    outcomes = {r["outcome"] for r in runs}
    claims = {r["claim_allowed"] for r in runs}
    # Headline only when every recorded run agrees; otherwise say so rather than pick one.

    def recency(r: dict[str, Any]) -> tuple[str, str]:
        at = r["generated_at_utc"]
        return (at if isinstance(at, str) else "", r["source_path"])

    latest = max(runs, key=recency)
    return {
        "outcome": next(iter(outcomes)) if len(outcomes) == 1 else "runs disagree",
        "claim_allowed": next(iter(claims)) if len(claims) == 1 else "runs disagree",
        "reason": latest["reason"],
        "runs": [{k: v for k, v in r.items() if k != "policies"} for r in runs],
        "policies": latest["policies"],
        "policies_source": latest["source_path"],
    }


def build_status(root: Path) -> dict[str, Any]:
    raw = _read(root, STATUS_REL)
    if raw is None:
        return {"recorded": False, "note": "not recorded for this build", "checks": []}
    try:
        d = json.loads(raw)
    except ValueError as exc:
        raise EvidenceError(f"{STATUS_REL}: invalid JSON ({exc})") from exc
    if not isinstance(d, dict) or not isinstance(d.get("checks"), list):
        raise EvidenceError(f"{STATUS_REL}: needs an object with a 'checks' list")
    checks = []
    for i, c in enumerate(d["checks"]):
        if not isinstance(c, dict) or not isinstance(c.get("name"), str) or c.get("result") not in CHECK_RESULTS:
            raise EvidenceError(f"{STATUS_REL}: checks[{i}] needs a name and a result in {list(CHECK_RESULTS)}")
        checks.append({k: str(c[k]) for k in ("name", "command", "result", "counts", "log_path") if k in c})
    out: dict[str, Any] = {"recorded": True, "checks": checks}
    for k in ("recorded_at", "commit", "note"):
        if isinstance(d.get(k), str):
            out[k] = d[k]
    return out


def build_skills(root: Path) -> list[dict[str, Any]]:
    out = []
    for sid, title, files in SKILLS:
        missing = [p for p, _ in files if not (root / p).exists()]
        if missing:
            raise EvidenceError(f"skills map: path(s) not in the repository: {missing}")
        out.append({"id": sid, "title": title, "files": [{"path": p, "what": w} for p, w in files]})
    return out


def build_all(root: Path = ROOT) -> dict[str, Any]:
    claims_md = _read(root, CLAIMS_REL)
    limits_md = _read(root, LIMITS_REL)
    return {
        "claims.json": parse_claims(claims_md) if claims_md is not None else [],
        "limitations.json": parse_limitations(limits_md)
        if limits_md is not None
        else {"source": NOT_RECORDED, "model_status": [], "sections": []},
        "ppo_result.json": build_ppo(root),
        "status.json": build_status(root),
        "skills.json": build_skills(root),
    }


def render(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="fail if a generated file is missing or stale; write nothing")
    args = ap.parse_args(argv)
    try:
        built = build_all(root)
    except EvidenceError as exc:
        print(f"build_evidence: {exc}", file=sys.stderr)
        return 2
    out_dir = root / OUT_REL
    stale = []
    for name, obj in built.items():
        text = render(obj)
        target = out_dir / name
        current = target.read_text(encoding="utf-8") if target.is_file() else None
        if args.check:
            if current != text:
                stale.append(name)
        elif current != text:
            out_dir.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")
            print(f"wrote {OUT_REL}/{name}")
    if args.check:
        if stale:
            names = ", ".join(stale)
            print(f"build_evidence: stale or missing: {names}. Run: python scripts/build_evidence.py", file=sys.stderr)
            return 1
        print("build_evidence: generated files are up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())

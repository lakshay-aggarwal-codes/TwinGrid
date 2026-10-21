"""Reproducible report export bound to ONE stored run (roadmap Task 17).

    python -m src.run_export baselines-v4 --format md  --out baselines-v4.md
    python -m src.run_export baselines-v4 --format pdf --out baselines-v4.pdf
    python -m src.run_export baselines-v4 --expect-result-sha256 <hash> --out x.md   # refuses if the run is not that one

The report is generated ONLY from the files of ``reports/runs/<run_id>/`` (``manifest.json``, ``status.json``,
``results.json``). It never takes numbers from a screen, a request body or the clock, so the same run exports to the same
bytes on every machine. It REFUSES (``ExportRefused``, CLI exit status 2, nothing written) when:

  * the run id is not a plain name, or the run directory does not exist;
  * the directory name, ``manifest.run_id`` and ``status.run_id`` are not all the requested id (a renamed or copied run);
  * the run is not ``completed``;
  * ``results.json`` does not hash to ``manifest.result_sha256`` (edited after the run; CRLF checkouts are tolerated);
  * the caller says which result it selected (``expected_result_sha256``) and the stored result is a different one.

Markdown is produced with the standard library. PDF uses ``reportlab`` (already in ``requirements.txt``) from the SAME block
list, so the two formats cannot disagree. Everything described is SIMULATOR output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

from .repro import report as repro_report

RUNS_SUBDIR = Path("reports") / "runs"
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
HARD_CONSTRAINT_METRICS: tuple[str, ...] = (
    "outlet_violation_steps",
    "inlet_over_max_steps",
    "inlet_under_min_steps",
    "pue_over_max_steps",
)
NOT_MEASURED = "not measured"
LIMITATIONS: tuple[str, ...] = (
    "Everything here is simulator output: a lumped, uncalibrated plant model. It is not a measurement of any facility.",
    "No statement here concerns real equipment, real grid carbon or an operational deployment.",
    "A result only supports the claim sentences quoted above under 'Claims'.",
)


class ExportRefused(ValueError):
    """The run cannot be exported as requested (the message says why)."""


Block = tuple  # ("h1"|"h2"|"p", text) | ("kv", [(k, v)]) | ("table", columns, rows) | ("list", [text])


def _lf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def _load_json(path: Path, what: str) -> dict[str, Any]:
    if not path.is_file():
        raise ExportRefused(f"{what} is missing: {path.name}")
    try:
        data = json.loads(path.read_bytes().replace(b"\r\n", b"\n").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExportRefused(f"{what} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ExportRefused(f"{what} must be a JSON object")
    return data


def load_run(
    root: Path, run_id: str, *, runs_dir: Path = RUNS_SUBDIR, expected_result_sha256: str | None = None
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    """Return ``(manifest, status, results, results_sha256)`` for ``run_id`` or raise ``ExportRefused``."""
    if not isinstance(run_id, str) or not _RUN_ID.match(run_id):
        raise ExportRefused(f"{run_id!r} is not a valid run id")
    base = (Path(root) / runs_dir).resolve()
    run_dir = (base / run_id).resolve()
    if run_dir.parent != base or not run_dir.is_dir():
        raise ExportRefused(f"run {run_id!r} does not exist under {runs_dir.as_posix()}")
    manifest = _load_json(run_dir / "manifest.json", "manifest.json")
    status = _load_json(run_dir / "status.json", "status.json")
    ids = {"directory": run_dir.name, "manifest": manifest.get("run_id"), "status": status.get("run_id")}
    if set(ids.values()) != {run_id}:
        raise ExportRefused(f"run id mismatch: requested {run_id!r} but {ids}")
    if status.get("state") != "completed":
        raise ExportRefused(f"run {run_id!r} is {status.get('state')!r}, not 'completed'")
    results_path = run_dir / "results.json"
    if not results_path.is_file():
        raise ExportRefused("results.json is missing")
    actual = _lf_sha256(results_path)
    if actual != manifest.get("result_sha256"):
        raise ExportRefused(
            f"results.json hash {actual[:12]}... differs from the manifest's {str(manifest.get('result_sha256'))[:12]}...: "
            "the result was changed after the run"
        )
    if expected_result_sha256 is not None and expected_result_sha256 != actual:
        raise ExportRefused(
            f"the selected result ({expected_result_sha256[:12]}...) is not the stored result of run {run_id!r} "
            f"({actual[:12]}...)"
        )
    results = _load_json(results_path, "results.json")
    try:
        repro_report.validate_results(results)
    except repro_report.ResultsError as exc:
        raise ExportRefused(f"results.json is not a valid results file: {exc}") from exc
    return manifest, status, results, actual


def _num(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else repro_report.fmt_number(v)


def violation_rows(results: dict[str, Any]) -> tuple[list[str], list[list[str]]] | None:
    """Hard-constraint step counts per policy summed over the held-out test scenarios, or None if not reported.

    A metric absent from ANY row of a policy is shown as 'not measured' (never as 0)."""
    per = results.get("per_scenario_test")
    if not isinstance(per, dict) or not per:
        return None
    columns = ["policy", "test scenarios", *HARD_CONSTRAINT_METRICS]
    rows = []
    for policy in sorted(per):
        scenarios = per[policy]
        row = [policy, str(len(scenarios))]
        for metric in HARD_CONSTRAINT_METRICS:
            values = [s.get(metric) for s in scenarios]
            ok = values and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in values)
            row.append(_num(sum(values)) if ok else NOT_MEASURED)
        rows.append(row)
    return columns, rows


def build_blocks(
    manifest: dict[str, Any], status: dict[str, Any], results: dict[str, Any], result_sha: str
) -> list[Block]:
    """The whole document as data. Reads only the three stored files."""
    m = manifest
    blocks: list[Block] = [
        ("h1", f"Run report: {m['run_id']}"),
        ("p", f"{results['title']}. Generated from the stored files of run {m['run_id']} only; no on-screen state."),
        ("h2", "Run"),
        (
            "kv",
            [
                ("run id", m["run_id"]),
                ("experiment", results["experiment"]),
                ("state", status["state"]),
                ("started (UTC)", status.get("started_at_utc") or "not recorded"),
                ("finished (UTC)", status.get("finished_at_utc") or "not recorded"),
                ("results schema", results["schema"]),
            ],
        ),
        ("h2", "Provenance"),
        (
            "kv",
            [
                ("physics version", m.get("physics_version") or "not recorded"),
                ("physics params hash", m.get("physics_params_hash") or "none (version has no parameter surface)"),
                (
                    "environment / reward / action semantics / safety envelope",
                    " / ".join(
                        str(m.get(k) or "?")
                        for k in (
                            "environment_version",
                            "reward_version",
                            "action_semantics_version",
                            "safety_envelope_version",
                        )
                    ),
                ),
                (
                    "code revision",
                    f"{m.get('code_revision') or 'unknown'} ({m.get('code_revision_source') or 'source unknown'})",
                ),
                (
                    "working tree",
                    "DIRTY: uncommitted changes when the run was made; not promotable" if m.get("dirty") else "clean",
                ),
                ("preregistration", f"{m.get('prereg_path') or 'none'} (sha256 {m.get('prereg_sha256') or 'n/a'})"),
                ("dependency lock sha256", m.get("lock_sha256") or "not recorded"),
                ("command", " ".join(str(c) for c in m.get("command", [])) or "not recorded"),
                (
                    "platform",
                    ", ".join(f"{k} {v}" for k, v in sorted((m.get("platform") or {}).items())) or "not recorded",
                ),
                ("manifest scenario set id", m.get("scenario_set_id") or "none"),
                ("split id", m.get("split_id") or "none"),
                ("results.json sha256", result_sha),
            ],
        ),
    ]
    if m.get("config_files"):
        blocks += [
            ("h2", "Configuration files"),
            ("table", ["file", "sha256"], [[k, v] for k, v in sorted(m["config_files"].items())]),
        ]
    seeds = results.get("seeds") or []
    blocks += [("h2", "Seeds"), ("p", ", ".join(str(s) for s in seeds) if seeds else "none recorded")]
    sets = results.get("scenario_sets")
    if isinstance(sets, dict) and sets:
        blocks += [
            ("h2", "Scenario sets"),
            (
                "table",
                ["set", "id", "scenarios"],
                [[k, str(v.get("id")), str(v.get("n"))] for k, v in sorted(sets.items())],
            ),
        ]
    carbon = results.get("carbon")
    if isinstance(carbon, dict):
        if carbon.get("is_real"):
            text = (
                "Carbon intensity is marked real by the run (is_real = true). The run record does not carry its "
                "source, region or date, so this report makes no carbon-saving statement."
            )
        else:
            text = "Carbon intensity is an ASSUMED constant (is_real = false), not measured grid data."
        blocks += [("h2", "Carbon signal"), ("p", text + (" The curve is flat." if carbon.get("flat_curve") else ""))]
    if results.get("summary"):
        blocks += [
            ("h2", "Summary"),
            (
                "table",
                ["metric", "value"],
                [[k, repro_report.fmt_number(v)] for k, v in sorted(results["summary"].items())],
            ),
        ]
    for _name, table in sorted(results["tables"].items()):
        blocks += [
            ("h2", table["title"]),
            (
                "table",
                [str(c) for c in table["columns"]],
                [[repro_report.fmt_number(c) for c in row] for row in table["rows"]],
            ),
        ]
    viol = violation_rows(results)
    blocks.append(("h2", "Hard-constraint violations (held-out test scenarios, steps summed)"))
    if viol is None:
        blocks.append(("p", "This experiment does not report per-scenario hard-constraint counts."))
    else:
        blocks.append(("table", viol[0], viol[1]))
        blocks.append(
            ("p", f"'{NOT_MEASURED}' means the stored run has no such counter for that policy; it is not zero.")
        )
    claims = results.get("claims")
    if isinstance(claims, dict):
        blocks += [
            ("h2", "Claims"),
            (
                "list",
                [
                    f"Allowed: {claims.get('allowed', 'none stated')}",
                    f"Not allowed: {claims.get('not_allowed', 'none stated')}",
                ],
            ),
        ]
    notes = list(results.get("notes") or [])
    blocks += [
        ("h2", "Notes from the run"),
        ("list", notes or ["none"]),
        ("h2", "Limitations"),
        ("list", list(LIMITATIONS)),
    ]
    return blocks


def _md_escape(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_markdown(blocks: Sequence[Block]) -> str:
    out: list[str] = []
    for b in blocks:
        kind = b[0]
        if kind == "h1":
            out += [f"# {b[1]}", ""]
        elif kind == "h2":
            out += [f"## {b[1]}", ""]
        elif kind == "p":
            out += [b[1], ""]
        elif kind == "kv":
            out += (
                ["| field | value |", "|---|---|"] + [f"| {_md_escape(k)} | {_md_escape(v)} |" for k, v in b[1]] + [""]
            )
        elif kind == "table":
            out += ["| " + " | ".join(_md_escape(c) for c in b[1]) + " |", "|" + "---|" * len(b[1])]
            out += ["| " + " | ".join(_md_escape(c) for c in row) + " |" for row in b[2]] + [""]
        elif kind == "list":
            out += [f"- {t}" for t in b[1]] + [""]
    return "\n".join(out).rstrip("\n") + "\n"


def render_pdf(blocks: Sequence[Block]) -> bytes:
    """PDF bytes from the same blocks (reportlab; imported lazily)."""
    import io
    from xml.sax.saxutils import escape

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    cell = styles["BodyText"].clone("cell", fontSize=7, leading=8.5)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        invariant=True,
    )

    def para(text: Any, style: Any = cell) -> Paragraph:
        return Paragraph(escape(str(text)), style)

    def grid(columns: Sequence[Any], rows: Sequence[Sequence[Any]]) -> Table:
        data = [[para(c) for c in columns]] + [[para(c) for c in r] for r in rows]
        table = Table(data, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        return table

    story: list[Any] = []
    for b in blocks:
        kind = b[0]
        if kind == "h1":
            story.append(para(b[1], styles["Title"]))
        elif kind == "h2":
            story += [Spacer(1, 4 * mm), para(b[1], styles["Heading2"])]
        elif kind == "p":
            story.append(para(b[1], styles["BodyText"]))
        elif kind == "kv":
            story.append(grid(["field", "value"], [[k, v] for k, v in b[1]]))
        elif kind == "table":
            story.append(grid(b[1], b[2]))
        elif kind == "list":
            story += [para(f"- {t}", styles["BodyText"]) for t in b[1]]
    doc.build(story)
    return buf.getvalue()


def export_run(
    root: Path,
    run_id: str,
    *,
    fmt: str = "md",
    runs_dir: Path = RUNS_SUBDIR,
    expected_result_sha256: str | None = None,
) -> bytes:
    """Bytes of the report for ``run_id`` (``fmt`` = ``md`` or ``pdf``). Raises ``ExportRefused``."""
    if fmt not in ("md", "pdf"):
        raise ExportRefused(f"unknown format {fmt!r}; use 'md' or 'pdf'")
    manifest, status, results, sha = load_run(
        root, run_id, runs_dir=runs_dir, expected_result_sha256=expected_result_sha256
    )
    blocks = build_blocks(manifest, status, results, sha)
    return render_markdown(blocks).encode("utf-8") if fmt == "md" else render_pdf(blocks)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m src.run_export", description=__doc__.split("\n\n")[0])
    ap.add_argument("run_id")
    ap.add_argument("--format", choices=("md", "pdf"), default="md")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    ap.add_argument("--runs-dir", type=Path, default=RUNS_SUBDIR)
    ap.add_argument("--expect-result-sha256", default=None, help="refuse unless the stored results.json has this hash")
    args = ap.parse_args(argv)
    try:
        data = export_run(
            args.root,
            args.run_id,
            fmt=args.format,
            runs_dir=args.runs_dir,
            expected_result_sha256=args.expect_result_sha256,
        )
    except ExportRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    args.out.write_bytes(data)
    print(f"wrote {args.out} ({len(data)} bytes) from run {args.run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

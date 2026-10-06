"""Tables, figures and REPORT.md, generated from ``results.json`` and nothing else (contract 11.2).

Every function here takes the parsed results object and returns text. None of them reads the
manifest, the clock, the environment or any other file, so ``repro.py verify`` can regenerate the
whole report directory from ``results.json`` and byte-compare it with what is on disk. No number
is typed into a template: tables and figures are *declared inside* ``results.json`` by the
experiment (``tables`` / ``figures``) and merely rendered here.

``results.json`` schema (``twingrid-results/1``)::

    {"schema": "twingrid-results/1", "experiment": "<name>", "title": "<text>", "seeds": [..],
     "summary": {"<metric>": <number|string>, ...},
     "tables":  {"<name>": {"title": "..", "columns": [..], "rows": [[..], ..]}},
     "figures": {"<name>": {"type": "bar"|"line", "title": "..", "x_label": "..", "y_label": "..",
                            "x": [..], "series": {"<label>": [numbers]}}},
     "notes":   ["..."]}
"""

from __future__ import annotations

import re
from typing import Any
from xml.sax.saxutils import escape

from . import RESULTS_SCHEMA

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_NUMBER_TOKEN = re.compile(r"(?<![\w.])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\w])")
_PALETTE = ("#1f6fb2", "#d9822b", "#3a9d5d", "#b04a8a", "#6b6b6b", "#8c564b")


class ResultsError(ValueError):
    """``results.json`` does not follow the results schema."""


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate_results(results: Any) -> None:
    if not isinstance(results, dict):
        raise ResultsError("results must be a JSON object")
    if results.get("schema") != RESULTS_SCHEMA:
        raise ResultsError(f"schema must be {RESULTS_SCHEMA!r}")
    for key in ("experiment", "title"):
        if not isinstance(results.get(key), str) or not results[key].strip():
            raise ResultsError(f"{key} must be a non-empty string")
    if not isinstance(results.get("seeds"), list) or not all(
        isinstance(s, int) and not isinstance(s, bool) for s in results["seeds"]
    ):
        raise ResultsError("seeds must be a list of integers")
    summary = results.get("summary")
    if not isinstance(summary, dict) or not all(isinstance(v, str) or _is_number(v) for v in summary.values()):
        raise ResultsError("summary must map names to numbers or strings")
    tables = results.get("tables")
    if not isinstance(tables, dict):
        raise ResultsError("tables must be an object")
    for name, table in tables.items():
        if not _NAME.match(name):
            raise ResultsError(f"table name {name!r} is not file-name safe")
        if not isinstance(table, dict) or not isinstance(table.get("title"), str):
            raise ResultsError(f"table {name}: needs a title")
        cols, rows = table.get("columns"), table.get("rows")
        if not (isinstance(cols, list) and cols and all(isinstance(c, str) for c in cols)):
            raise ResultsError(f"table {name}: columns must be a non-empty list of strings")
        if not isinstance(rows, list):
            raise ResultsError(f"table {name}: rows must be a list")
        for i, row in enumerate(rows):
            if not (
                isinstance(row, list)
                and len(row) == len(cols)
                and all(isinstance(c, str) or _is_number(c) for c in row)
            ):
                raise ResultsError(f"table {name}: row {i} must have {len(cols)} string/number cells")
    figures = results.get("figures")
    if not isinstance(figures, dict):
        raise ResultsError("figures must be an object")
    for name, fig in figures.items():
        if not _NAME.match(name):
            raise ResultsError(f"figure name {name!r} is not file-name safe")
        if not isinstance(fig, dict) or fig.get("type") not in ("bar", "line"):
            raise ResultsError(f"figure {name}: type must be 'bar' or 'line'")
        for key in ("title", "x_label", "y_label"):
            if not isinstance(fig.get(key), str):
                raise ResultsError(f"figure {name}: {key} must be a string")
        x, series = fig.get("x"), fig.get("series")
        if not (isinstance(x, list) and x and all(isinstance(v, str) or _is_number(v) for v in x)):
            raise ResultsError(f"figure {name}: x must be a non-empty list")
        if not (isinstance(series, dict) and series):
            raise ResultsError(f"figure {name}: series must be a non-empty object")
        for label, values in series.items():
            if not (isinstance(values, list) and len(values) == len(x) and all(_is_number(v) for v in values)):
                raise ResultsError(f"figure {name}: series {label!r} must hold {len(x)} numbers")
    if not isinstance(results.get("notes"), list) or not all(isinstance(n, str) for n in results["notes"]):
        raise ResultsError("notes must be a list of strings")


# ----------------------------------------------------------------------------- number formatting


def fmt_number(v: Any) -> str:
    """The one rule for a number shown in REPORT.md: integers verbatim, floats to 6 significant digits."""
    if isinstance(v, str):
        return v
    if isinstance(v, int):
        return str(v)
    return "0" if v == 0 else f"{v:.6g}"


def _full(v: Any) -> str:
    if isinstance(v, str):
        return v
    if isinstance(v, int):
        return str(v)
    return "0.0" if v == 0 else repr(float(v))


def _md_cell(v: Any) -> str:
    return fmt_number(v).replace("|", "\\|").replace("\n", " ")


# ----------------------------------------------------------------------------- tables


def _csv_cell(v: Any) -> str:
    text = _full(v)
    if isinstance(v, str) and any(ch in text for ch in ',"\n\r'):
        return '"' + text.replace('"', '""') + '"'
    return text


def render_tables(results: dict[str, Any]) -> dict[str, str]:
    """``{"tables/<name>.csv": text}``; numbers at full (round-trip) precision."""
    out = {}
    for name, table in sorted(results["tables"].items()):
        lines = [",".join(_csv_cell(c) for c in table["columns"])]
        lines += [",".join(_csv_cell(c) for c in row) for row in table["rows"]]
        out[f"tables/{name}.csv"] = "\n".join(lines) + "\n"
    return out


# ----------------------------------------------------------------------------- figures


def _svg_text(x: float, y: float, text: str, *, anchor: str = "middle", size: int = 11, extra: str = "") -> str:
    return f'<text x="{x:.2f}" y="{y:.2f}" font-family="sans-serif" font-size="{size}" text-anchor="{anchor}"{extra}>{escape(text)}</text>'


def _nice_max(v: float) -> float:
    if v <= 0:
        return 1.0
    import math

    exp = math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * 10**exp:
            return m * 10**exp
    return 10 ** (exp + 1)


def _render_figure(fig: dict[str, Any]) -> str:
    width, height = 640, 380
    left, right, top, bottom = 70, 20, 40, 70
    plot_w, plot_h = width - left - right, height - top - bottom
    series = list(fig["series"].items())
    values = [v for _, vals in series for v in vals]
    lo, hi = min(0.0, min(values)), max(0.0, max(values))
    if lo == hi:
        hi = lo + 1.0
    hi_n = _nice_max(hi) if lo == 0.0 else hi
    span = hi_n - lo
    n = len(fig["x"])

    def ypos(v: float) -> float:
        return top + plot_h - (v - lo) / span * plot_h

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>',
        _svg_text(width / 2, 22, fig["title"], size=14, extra=' font-weight="bold"'),
    ]
    for i in range(5):
        tick = lo + span * i / 4
        y = ypos(tick)
        parts.append(f'<line x1="{left}" y1="{y:.2f}" x2="{left + plot_w}" y2="{y:.2f}" stroke="#dddddd"/>')
        parts.append(_svg_text(left - 6, y + 4, fmt_number(float(f"{tick:.6g}")), anchor="end", size=10))
    parts.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}" stroke="#444444"/>')
    parts.append(f'<line x1="{left}" y1="{ypos(0.0):.2f}" x2="{left + plot_w}" y2="{ypos(0.0):.2f}" stroke="#444444"/>')
    slot = plot_w / n
    for j, label in enumerate(fig["x"]):
        parts.append(
            _svg_text(
                left + slot * (j + 0.5),
                top + plot_h + 16,
                fmt_number(label) if not isinstance(label, str) else label,
                size=10,
            )
        )
    if fig["type"] == "bar":
        group = slot * 0.8
        bar_w = group / len(series)
        for k, (_, vals) in enumerate(series):
            for j, v in enumerate(vals):
                x = left + slot * j + (slot - group) / 2 + bar_w * k
                y0, y1 = ypos(0.0), ypos(v)
                parts.append(
                    f'<rect x="{x:.2f}" y="{min(y0, y1):.2f}" width="{bar_w:.2f}" height="{abs(y0 - y1):.2f}" fill="{_PALETTE[k % len(_PALETTE)]}"/>'
                )
    else:
        for k, (_, vals) in enumerate(series):
            pts = " ".join(f"{left + slot * (j + 0.5):.2f},{ypos(v):.2f}" for j, v in enumerate(vals))
            parts.append(
                f'<polyline points="{pts}" fill="none" stroke="{_PALETTE[k % len(_PALETTE)]}" stroke-width="2"/>'
            )
            for j, v in enumerate(vals):
                parts.append(
                    f'<circle cx="{left + slot * (j + 0.5):.2f}" cy="{ypos(v):.2f}" r="3" fill="{_PALETTE[k % len(_PALETTE)]}"/>'
                )
    parts.append(_svg_text(left + plot_w / 2, height - 28, fig["x_label"], size=11))
    parts.append(
        _svg_text(
            14, top + plot_h / 2, fig["y_label"], size=11, extra=f' transform="rotate(-90 14 {top + plot_h / 2:.2f})"'
        )
    )
    for k, (label, _) in enumerate(series):
        lx = left + 8 + k * 150
        parts.append(f'<rect x="{lx}" y="{height - 18}" width="10" height="10" fill="{_PALETTE[k % len(_PALETTE)]}"/>')
        parts.append(_svg_text(lx + 14, height - 9, label, anchor="start", size=10))
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def render_figures(results: dict[str, Any]) -> dict[str, str]:
    """``{"figures/<name>.svg": svg}``, hand-written SVG so the bytes depend on nothing but the data."""
    return {f"figures/{name}.svg": _render_figure(fig) for name, fig in sorted(results["figures"].items())}


# ----------------------------------------------------------------------------- REPORT.md


def render_report(results: dict[str, Any]) -> str:
    """REPORT.md text. Reads ONLY ``results``."""
    lines = [
        f"# {results['title']}",
        "",
        f"Experiment: `{results['experiment']}`  ",
        f"Schema: `{results['schema']}`  ",
    ]
    lines.append("Seeds: " + (", ".join(str(s) for s in results["seeds"]) or "none"))
    lines += ["", "Generated from `results.json` by `src/repro/report.py`; nothing in this file is typed by hand.", ""]
    if results["summary"]:
        lines += ["## Summary", "", "| metric | value |", "|---|---|"]
        lines += [f"| {k.replace('|', chr(92) + '|')} | {_md_cell(v)} |" for k, v in sorted(results["summary"].items())]
        lines.append("")
    for name, table in sorted(results["tables"].items()):
        lines += [f"## {table['title']}", "", "| " + " | ".join(_md_cell(c) for c in table["columns"]) + " |"]
        lines.append("|" + "---|" * len(table["columns"]))
        lines += ["| " + " | ".join(_md_cell(c) for c in row) + " |" for row in table["rows"]]
        lines += ["", f"Full precision: `tables/{name}.csv`", ""]
    for name, fig in sorted(results["figures"].items()):
        lines += [f"## {fig['title']}", "", f"![{fig['title']}](figures/{name}.svg)", ""]
    if results["notes"]:
        lines += ["## Notes", ""] + [f"- {n}" for n in results["notes"]] + [""]
    return "\n".join(lines).rstrip("\n") + "\n"


def render_all(results: dict[str, Any]) -> dict[str, str]:
    """Every generated file: ``REPORT.md``, ``tables/*.csv`` and ``figures/*.svg`` (path -> text)."""
    validate_results(results)
    files = {"REPORT.md": render_report(results)}
    files.update(render_tables(results))
    files.update(render_figures(results))
    return files


# ----------------------------------------------------------------------------- number provenance


def _collect(obj: Any, numbers: set[str], texts: list[str]) -> None:
    if isinstance(obj, bool) or obj is None:
        return
    if _is_number(obj):
        numbers.update({fmt_number(obj), _full(obj)})
        if isinstance(obj, float) and obj == int(obj) and abs(obj) < 1e15:
            numbers.add(str(int(obj)))
    elif isinstance(obj, str):
        texts.append(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            texts.append(str(k))
            _collect(v, numbers, texts)
    elif isinstance(obj, list):
        for v in obj:
            _collect(v, numbers, texts)


def allowed_number_tokens(results: dict[str, Any]) -> set[str]:
    """Every numeric token a report generated from ``results`` may contain: the numbers in it (as the
    report formats them) plus numeric tokens inside its strings and keys (titles, ids, hashes)."""
    numbers: set[str] = set()
    texts: list[str] = []
    _collect(results, numbers, texts)
    for text in texts:
        numbers.update(_NUMBER_TOKEN.findall(text))
    return numbers


def check_report_numbers(report_text: str, results: dict[str, Any]) -> list[str]:
    """Numeric tokens in ``report_text`` that are NOT present in ``results`` (empty list = all accounted for)."""
    allowed = allowed_number_tokens(results)
    return sorted({t for t in _NUMBER_TOKEN.findall(report_text) if t not in allowed})

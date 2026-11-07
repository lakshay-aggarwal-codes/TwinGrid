"""Verify a bundle: read-back counts, content digests recomputed from the file, structural rules, and (with the panel)
value-by-value agreement with the panel TSVs. Read-only on the bundle. Build/verify side (numpy, pandas)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from pathlib import Path

import numpy as np

from . import digest as dg
from .errors import BundleError
from .reader import open_readonly
from .schema import STATE_OBSERVED


def quick_counts(path: Path) -> dict:
    """Row counts only (used by the loader before it replaces a bundle)."""
    conn = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
    try:
        q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
        return {
            "observation_rows": q("SELECT COUNT(*) FROM observation"),
            "second_rows": q("SELECT COUNT(*) FROM second"),
            "derived_rows": q("SELECT COUNT(*) FROM derived_observation"),
        }
    finally:
        conn.close()


def _digest_from_db(conn: sqlite3.Connection, table: str, key: str, pk: int, h, chunk: int = 250_000) -> None:
    cur = conn.execute(
        f"SELECT t_naive_s, value_ticks, state, quality, reason_id FROM {table} WHERE {key} = ? ORDER BY t_naive_s",
        (pk,),
    )
    while rows := cur.fetchmany(chunk):
        t = np.fromiter((r[0] for r in rows), dtype=np.int64, count=len(rows))
        v = np.fromiter((0 if r[1] is None else r[1] for r in rows), dtype=np.int64, count=len(rows))
        vn = np.fromiter((r[1] is None for r in rows), dtype=np.int8, count=len(rows))
        s = np.fromiter((r[2] for r in rows), dtype=np.int8, count=len(rows))
        q = np.fromiter((-1 if r[3] is None else r[3] for r in rows), dtype=np.int8, count=len(rows))
        r_ = np.fromiter((0 if r[4] is None else r[4] for r in rows), dtype=np.int8, count=len(rows))
        dg.update(h, pk, t, v, vn, s, q, r_)


def verify_bundle(
    bundle: Path,
    panel_dir: Path | None = None,
    *,
    deep: bool = False,
    progress: Callable[[str], None] | None = None,
    chunk_rows: int = 250_000,
) -> dict:
    """``{"problems": [...], ...}``; empty problems = verified. ``deep`` also compares every value with the panel TSVs."""
    say = progress or (lambda m: None)
    conn = open_readonly(bundle)
    problems: list[str] = []
    try:
        dv = dict(conn.execute("SELECT * FROM dataset_version WHERE id = 1").fetchone())
        rep = json.loads(dv["counts_json"])
        if dv["access_status"] != "local_only":
            problems.append(f"access_status is {dv['access_status']!r}; no code path may set anything but local_only")
        if not dv["stream"].startswith("import:"):
            problems.append("stream is not an import: stream")

        say("counting")
        n_sec = conn.execute("SELECT COUNT(*) FROM second").fetchone()[0]
        if n_sec != rep["unique_seconds"]:
            problems.append(f"second rows {n_sec} != recorded {rep['unique_seconds']}")
        per = {r[0]: r[1] for r in conn.execute("SELECT entity_pk, COUNT(*) FROM observation GROUP BY entity_pk")}
        ents = {
            r["entity_pk"]: r
            for r in conn.execute("SELECT * FROM entity WHERE kind = 'channel' AND provenance = 'measured'")
        }
        if set(per) != set(ents) or len(per) != 40:
            problems.append("observation holds series that are not the 40 measured Tier 1 channels")
        for pk, n in per.items():
            if n != n_sec:
                problems.append(f"entity {pk}: {n} rows, expected {n_sec}")
        states = {
            (r[0], r[1]): r[2]
            for r in conn.execute("SELECT state, reason_id, COUNT(*) FROM observation GROUP BY state, reason_id")
        }
        obs = sum(v for (s, _), v in states.items() if s == STATE_OBSERVED)
        tie = states.get((1, 1), 0)
        blank = states.get((1, 2), 0)
        if (obs, tie, blank) != (rep["observed_cells"], rep["tier1_conflict_missing_cells"], rep["blank_cells"]):
            problems.append(f"state counts {(obs, tie, blank)} differ from the recorded counts")
        if sum(states.values()) != rep["stored_cells"]:
            problems.append("cell total differs from stored_cells")
        d_states = {r[0]: r[1] for r in conn.execute("SELECT state, COUNT(*) FROM derived_observation GROUP BY state")}
        if (d_states.get(0, 0), d_states.get(1, 0)) != (
            rep["derived_defined_seconds"],
            rep["derived_undefined_seconds"],
        ):
            problems.append("derived counts differ from the recorded counts")

        # derived rule, recomputed in SQL from the loaded measured cells
        say("derived series check")
        d_inputs = json.loads(conn.execute("SELECT inputs_json FROM derived_series").fetchone()[0])
        in_pk = [
            conn.execute("SELECT entity_pk FROM entity WHERE external_id = ? AND kind = 'channel'", (s,)).fetchone()[0]
            for s in d_inputs
        ]
        marks = ",".join("?" * len(in_pk))
        absent = conn.execute(
            f"SELECT COUNT(*) FROM (SELECT t_naive_s FROM observation WHERE entity_pk IN ({marks}) "
            "GROUP BY t_naive_s HAVING SUM(state = 0 AND quality = 0) < ?)",
            [*in_pk, len(in_pk)],
        ).fetchone()[0]
        if absent != d_states.get(1, 0):
            problems.append(
                f"{absent} seconds have an input not observed/ok but {d_states.get(1, 0)} derived values are absent"
            )
        wrong = conn.execute(
            f"SELECT COUNT(*) FROM derived_observation d WHERE d.state = 0 AND d.value_ticks != "
            f"(SELECT SUM(value_ticks) FROM observation WHERE entity_pk IN ({marks}) AND t_naive_s = d.t_naive_s)",
            in_pk,
        ).fetchone()[0]
        if wrong:
            problems.append(f"{wrong} derived values differ from the sum of their inputs")

        say("recomputing content digests")
        h = hashlib.sha256()
        for pk in sorted(per):
            _digest_from_db(conn, "observation", "entity_pk", pk, h)
        if h.hexdigest() != dv["content_digest"]:
            problems.append("measured content digest differs from the stored one")
        hd = hashlib.sha256()
        _digest_from_db(conn, "derived_observation", "series_pk", 1, hd)
        if hd.hexdigest() != dv["derived_content_digest"]:
            problems.append("derived content digest differs from the stored one")

        link = {}
        if panel_dir is not None:
            panel = Path(panel_dir)
            manifest = json.loads((panel / "panel_manifest.json").read_text(encoding="utf-8"))
            channels = json.loads((panel / "channels.json").read_text(encoding="utf-8"))
            for k_db, k_m in (
                ("panel_sha256", manifest["panel_sha256"]),
                ("l1_sha256", manifest["outputs"]["l1_sha256"]),
            ):
                if dv[k_db] != k_m:
                    problems.append(f"{k_db} differs from the panel manifest")
            link = {"panel_sha256": manifest["panel_sha256"]}
            if deep:
                from . import panel_io as pio

                for ci, ch in enumerate(channels["measured_channels"]):
                    say(f"value comparison {ci + 1}/40")
                    pk = ents_pk(conn, ch["sensor_external_id"])
                    problems += _compare_series(
                        conn, "observation", "entity_pk", pk, panel / "l1" / ch["l1_file"], False, chunk_rows, pio
                    )
                d = channels["derived_channels"][0]
                problems += _compare_series(
                    conn, "derived_observation", "series_pk", 1, panel / d["file"], True, chunk_rows, pio
                )
                fk = conn.execute("PRAGMA foreign_key_check").fetchall()
                if fk:
                    problems.append(f"{len(fk)} foreign key violations")
        return {"problems": problems, "observation_rows": sum(per.values()), "seconds": n_sec, "panel_link": link}
    finally:
        conn.close()


def ents_pk(conn: sqlite3.Connection, sensor_external_id: str) -> int:
    r = conn.execute(
        "SELECT entity_pk FROM entity WHERE external_id = ? AND kind = 'channel'", (sensor_external_id,)
    ).fetchone()
    if r is None:
        raise BundleError(f"unknown channel {sensor_external_id!r}")
    return r[0]


def _compare_series(conn, table, key, pk, tsv, derived, chunk_rows, pio) -> list[str]:
    cur = conn.execute(
        f"SELECT t_naive_s, value_ticks, state, quality, reason_id FROM {table} WHERE {key} = ? ORDER BY t_naive_s",
        (pk,),
    )
    out: list[str] = []
    for c in pio.iter_chunks(tsv, derived=derived, chunk_rows=chunk_rows):
        rows = cur.fetchmany(len(c.t))
        if len(rows) != len(c.t):
            return [f"{Path(tsv).name}: bundle has fewer rows than the panel"]
        t = np.fromiter((r[0] for r in rows), dtype=np.int64, count=len(rows))
        v = np.fromiter((0 if r[1] is None else r[1] for r in rows), dtype=np.int64, count=len(rows))
        vn = np.fromiter((r[1] is None for r in rows), dtype=np.int8, count=len(rows))
        s = np.fromiter((r[2] for r in rows), dtype=np.int8, count=len(rows))
        q = np.fromiter((-1 if r[3] is None else r[3] for r in rows), dtype=np.int8, count=len(rows))
        r_ = np.fromiter((0 if r[4] is None else r[4] for r in rows), dtype=np.int8, count=len(rows))
        if not (
            np.array_equal(t, c.t) and np.array_equal(v, c.ticks) and np.array_equal(vn, c.ticks_null)
            and np.array_equal(s, c.state) and np.array_equal(q, c.quality) and np.array_equal(r_, c.reason)
        ):  # fmt: skip
            return [f"{Path(tsv).name}: bundle values differ from the panel"]
    if cur.fetchone() is not None:
        out.append(f"{Path(tsv).name}: bundle has more rows than the panel")
    return out

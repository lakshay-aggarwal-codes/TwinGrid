"""DDL of the read-only dataset bundle (Task 9 ADR r4 section 5; Task 15 owns the DDL).

One SQLite file, plain stdlib ``sqlite3``. Measured observations and the derived series live in separate tables, so a
measured route can never return a derived value and a derived value can never be mistaken for a measurement. Nothing here
touches ``telemetry_sample`` or any shared table.

Time key ``t_naive_s`` = ``calendar.timegm`` of the naive source label (no zone, no DST). It orders and ranges; it is not
an instant. The exact source text is kept in ``second.ts_text``.

Compact on purpose: the repeated per-second facts (source text, group size, disposition, first row) are stored once in
``second`` (1,370,788 rows) instead of once per cell (54.8 M rows), and the cell table uses small integer codes.
"""

from __future__ import annotations

SCHEMA_VERSION = 1
BUNDLE_FORMAT = "twingrid.danish_aau.bundle/1"

STATE_OBSERVED, STATE_MISSING = 0, 1
QUALITY_OK, QUALITY_FLAGGED = 0, 1
STATE_NAMES = {STATE_OBSERVED: "observed", STATE_MISSING: "missing"}
QUALITY_NAMES = {QUALITY_OK: "ok", QUALITY_FLAGGED: "flagged"}

REASON_CODES = {1: "conflict_unresolved_tie", 2: "blank_cell", 3: "inputs_not_all_observed"}
DISPOSITIONS = {
    1: "retained",
    2: "conflict_cell_missing",
}  # the only two a stored second can carry with default cleaning

DDL = """
CREATE TABLE dataset_version (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    bundle_format TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    dataset_id TEXT NOT NULL,
    version TEXT NOT NULL,
    doi TEXT NOT NULL,
    source_url TEXT NOT NULL,
    licence_name TEXT NOT NULL,
    attribution_text TEXT NOT NULL,
    modifications_statement TEXT NOT NULL,
    stream TEXT NOT NULL,
    access_status TEXT NOT NULL CHECK (access_status IN ('local_only', 'restricted', 'public_approved')),
    time_basis TEXT NOT NULL,
    window_first_text TEXT NOT NULL,
    window_last_text TEXT NOT NULL,
    raw_file_name TEXT NOT NULL,
    raw_file_sha256 TEXT NOT NULL,
    protocol_sha256 TEXT NOT NULL,
    mapping_file_sha256_lf TEXT NOT NULL,
    mapping_version INTEGER NOT NULL,
    derivations_file_sha256_lf TEXT NOT NULL,
    l1_sha256 TEXT NOT NULL,
    panel_sha256 TEXT NOT NULL,
    loader_code_sha256 TEXT NOT NULL,
    content_digest TEXT NOT NULL,
    derived_content_digest TEXT NOT NULL,
    counts_json TEXT NOT NULL
);
CREATE TABLE reason_code (reason_id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE);
CREATE TABLE disposition (disposition_id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE entity (
    entity_pk INTEGER PRIMARY KEY,
    entity_id TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL CHECK (kind IN ('channel', 'rack', 'power_port', 'zone')),
    external_id TEXT NOT NULL,
    name TEXT,
    provenance TEXT CHECK (provenance IS NULL OR provenance = 'measured'),
    storage_class TEXT,
    tier TEXT NOT NULL,
    load_in_v1 INTEGER NOT NULL CHECK (load_in_v1 IN (0, 1)),
    mapping_state TEXT,
    asset_external_id TEXT,
    source_rack_id TEXT,
    source_file_family TEXT,
    source_column TEXT,
    source_label TEXT,
    source_position_word TEXT,
    measurand TEXT,
    unit TEXT,
    resolution_decimals INTEGER,
    mapping_id TEXT,
    mapping_version INTEGER,
    method TEXT,
    label_evidence TEXT,
    evidence_status TEXT,
    valid_time_status TEXT,
    attribution_scope TEXT,
    member_source_rack_ids TEXT,
    split_allowed INTEGER CHECK (split_allowed IS NULL OR split_allowed = 0),
    evidence_refs TEXT
);
CREATE INDEX entity_external_id ON entity (external_id);
CREATE TABLE second (
    t_naive_s INTEGER PRIMARY KEY,
    ts_text TEXT NOT NULL UNIQUE,
    group_size INTEGER NOT NULL CHECK (group_size >= 1),
    disposition_id INTEGER NOT NULL REFERENCES disposition (disposition_id),
    first_row_ordinal INTEGER NOT NULL CHECK (first_row_ordinal >= 1)
);
CREATE TABLE observation (
    entity_pk INTEGER NOT NULL REFERENCES entity (entity_pk),
    t_naive_s INTEGER NOT NULL REFERENCES second (t_naive_s),
    value_ticks INTEGER,
    state INTEGER NOT NULL CHECK (state IN (0, 1)),
    quality INTEGER CHECK (quality IN (0, 1)),
    reason_id INTEGER REFERENCES reason_code (reason_id),
    PRIMARY KEY (entity_pk, t_naive_s),
    CHECK (
        (state = 0 AND value_ticks IS NOT NULL AND quality IS NOT NULL AND reason_id IS NULL)
        OR (state = 1 AND value_ticks IS NULL AND quality IS NULL AND reason_id IS NOT NULL)
    )
) WITHOUT ROWID;
CREATE TABLE derived_series (
    series_pk INTEGER PRIMARY KEY,
    derived_name TEXT NOT NULL UNIQUE,
    provenance TEXT NOT NULL CHECK (provenance = 'derived'),
    storage_class TEXT NOT NULL CHECK (storage_class = 'derived_series'),
    formula_id TEXT NOT NULL,
    formula_text TEXT NOT NULL,
    inputs_json TEXT NOT NULL,
    output_measurand TEXT NOT NULL,
    output_unit TEXT NOT NULL,
    resolution_decimals INTEGER NOT NULL,
    output_scope TEXT NOT NULL,
    output_member_source_rack_ids TEXT NOT NULL,
    split_per_rack INTEGER NOT NULL CHECK (split_per_rack = 0),
    method_approval_ref TEXT NOT NULL,
    derivations_file_sha256_lf TEXT NOT NULL,
    undefined_reason_id INTEGER NOT NULL REFERENCES reason_code (reason_id)
);
CREATE TABLE derived_observation (
    series_pk INTEGER NOT NULL REFERENCES derived_series (series_pk),
    t_naive_s INTEGER NOT NULL REFERENCES second (t_naive_s),
    value_ticks INTEGER,
    state INTEGER NOT NULL CHECK (state IN (0, 1)),
    quality INTEGER CHECK (quality IN (0, 1)),
    reason_id INTEGER REFERENCES reason_code (reason_id),
    PRIMARY KEY (series_pk, t_naive_s),
    CHECK (
        (state = 0 AND value_ticks IS NOT NULL AND quality IS NOT NULL AND reason_id IS NULL)
        OR (state = 1 AND value_ticks IS NULL AND quality IS NULL AND reason_id IS NOT NULL)
    )
) WITHOUT ROWID;
"""

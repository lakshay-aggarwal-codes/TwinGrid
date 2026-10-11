"""IG-01 regression tests: one small, dependency-free check per defect fixed in Stage A."""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

from sqlalchemy import inspect as sa_inspect

ROOT = Path(__file__).resolve().parents[1]


def test_audit_log_target_names_are_synonyms_of_the_stored_resource_columns():
    from models.db_models import AuditLog

    row = AuditLog(action="x", resource_type="model", resource_id="m@1")
    assert (row.target_type, row.target_id) == ("model", "m@1")
    row.target_type = "alert"
    assert row.resource_type == "alert"
    assert "target_type" not in {c.key for c in sa_inspect(AuditLog).columns}  # no second column, no migration


def test_alert_has_identity_and_provenance_columns_and_the_unique_index():
    from models.db_models import Alert

    cols = {c.key: c for c in sa_inspect(Alert).columns}
    assert {"dedupe_key", "model_version", "origin"} <= set(cols)
    assert all(cols[k].nullable for k in ("dedupe_key", "model_version", "origin"))  # legacy rows stay NULL
    indexes = {i.name: i for i in Alert.__table__.indexes}
    assert indexes["ux_alerts_dedupe_key"].unique and [c.name for c in indexes["ux_alerts_dedupe_key"].columns] == [
        "dedupe_key"
    ]


def test_created_at_nullability_matches_the_migrations_that_created_these_tables():
    from models.db_models import AuditLog, RefreshToken

    assert AuditLog.__table__.c.created_at.nullable and RefreshToken.__table__.c.created_at.nullable


def test_twin_default_start_time_is_aware_utc():
    from src.digital_twin import DigitalTwin

    t = DigitalTwin()._time
    assert t.tzinfo is not None and t.utcoffset() == timedelta(0)


def test_request_id_of_six_characters_is_accepted_and_five_is_not():
    from api.middleware.request_id import accept_request_id

    assert accept_request_id("rid-ta") == "rid-ta"
    assert accept_request_id("short") is None


def test_every_scoped_limit_is_introspectable():
    from api.rate_limit import http_limit

    assert http_limit("webhook").http_limit_scope == "webhook"


def test_dockerfile_base_image_is_pinned_by_digest():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^ARG PYTHON_IMAGE=python:3\.12\.10-slim@sha256:[0-9a-f]{64}$", text, re.M)

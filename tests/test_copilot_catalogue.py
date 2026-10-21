"""Task 14: the capability catalogue lists only real features."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.copilot import catalogue

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "twin-stream-insight-main" / "src"


def _ui_routes() -> set[str]:
    routes = set(re.findall(r'<Route path="([^"*]+)"', (SRC / "App.tsx").read_text(encoding="utf-8")))
    for index in (SRC / "features").glob("*/index.ts"):
        routes |= set(re.findall(r'route:\s*\{\s*path:\s*"([^"]+)"', index.read_text(encoding="utf-8")))
    return routes


def test_the_catalogue_is_well_formed():
    features = catalogue.load_catalogue()
    assert len(features) >= 10 and len({f["id"] for f in features}) == len(features)
    assert all(f["api_paths"] for f in features)


def test_every_ui_path_is_a_route_of_the_frontend():
    routes = _ui_routes()
    assert {"/", "/alerts", "/whatif-lab"} <= routes
    missing = [f["id"] for f in catalogue.load_catalogue() if f["ui_path"] not in routes]
    assert missing == []


def test_every_api_path_is_in_the_openapi_document():
    from api.main import app

    paths = set(app.openapi()["paths"])
    missing = [(f["id"], p) for f in catalogue.load_catalogue() for p in f["api_paths"] if p not in paths]
    assert missing == []


def test_find_feature_is_a_deterministic_keyword_match():
    assert catalogue.find_feature("where is the what-if lab")[0]["id"] == "what_if_lab"
    assert catalogue.find_feature("incident workflow for alerts")[0]["id"] == "alerts_centre"
    assert catalogue.find_feature("flux capacitor") == []
    assert catalogue.find_feature("what is the") == []  # stop words alone match nothing
    assert catalogue.find_feature("alerts") == catalogue.find_feature("alerts")


def test_a_malformed_catalogue_is_refused(tmp_path):
    bad = tmp_path / "c.json"
    for text in (
        "not json",
        '{"features": [{"id": "a"}]}',
        '{"features": []}'.replace("[]", '[{"id":"a","title":"t","description":"d","ui_path":"x","api_paths":[]}]'),
    ):
        bad.write_text(text, encoding="utf-8")
        with pytest.raises(ValueError):
            catalogue.load_catalogue(bad)

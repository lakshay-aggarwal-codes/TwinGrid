"""T0b: no served/rendered copy may call the carbon signal "real grid carbon"
while the flat fallback is in use (carbon_data_is_real is False)."""

import json
from pathlib import Path

from src import carbon_provider
from src.digital_twin import DigitalTwin

ROOT = Path(__file__).resolve().parent.parent
PHRASE = "real grid carbon"


def test_optimizer_config_does_not_claim_real_carbon_when_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(carbon_provider, "CLEANED_CARBON_PATH", tmp_path / "missing.csv")
    assert DigitalTwin().carbon_data_is_real is False
    cfg = (ROOT / "models" / "optimizer" / "config.json").read_text(encoding="utf-8")
    json.loads(cfg)  # still valid JSON
    assert PHRASE not in cfg.lower()


def test_frontend_sources_do_not_contain_real_grid_carbon_claim():
    src = ROOT / "twin-stream-insight-main" / "src"
    offenders = [
        str(p.relative_to(ROOT))
        for p in list(src.rglob("*.ts")) + list(src.rglob("*.tsx"))
        if ".test." not in p.name and PHRASE in p.read_text(encoding="utf-8").lower()
    ]
    assert offenders == []

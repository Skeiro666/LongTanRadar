"""V5 API smoke tests — alpha dashboard + ML weight experiments."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from ashare.api.app import create_app


def test_alpha_dashboard_shape():
    with TestClient(create_app()) as client:
        r = client.get("/api/research/alpha-dashboard?horizon=5")
    assert r.status_code == 200
    body = r.json()
    assert "cost" in body
    assert "decision_chain" in body
    assert "n_buys" in body
    assert body.get("horizon") in ("5", 5, None) or "horizon" in body


def test_ml_weight_experiments_list(tmp_path, monkeypatch):
    ml_dir = tmp_path / "data" / "ml"
    ml_dir.mkdir(parents=True)
    row = {"experiment_id": "mlw_test_001", "status": "completed", "weights_tested": [0.0, 0.1]}
    (ml_dir / "weight_experiments.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")

    root = str(tmp_path)
    monkeypatch.setenv("ASHARE_ROOT", root)

    from ashare.config import load_config

    cfg_path = Path(__file__).resolve().parents[1] / "config" / "default.yaml"
    cfg = load_config(str(cfg_path))
    cfg["_root"] = root

    from ashare.ml.weight_experiment import list_weight_experiments

    rows = list_weight_experiments(cfg)
    assert len(rows) == 1
    assert rows[0]["experiment_id"] == "mlw_test_001"


def test_ml_weight_experiments_api(tmp_path):
    ml_dir = tmp_path / "data" / "ml"
    ml_dir.mkdir(parents=True)
    row = {"experiment_id": "mlw_api_001", "status": "completed"}
    (ml_dir / "weight_experiments.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")

    cfg_path = Path(__file__).resolve().parents[1] / "config" / "default.yaml"
    app = create_app(str(cfg_path))

    from ashare.api import app as app_mod

    orig = app_mod.get_cfg

    def _cfg():
        c = orig()
        c["_root"] = str(tmp_path)
        return c

    app_mod.get_cfg = _cfg
    try:
        with TestClient(app) as client:
            r = client.get("/api/ml/weight-experiments")
        assert r.status_code == 200
        body = r.json()
        assert body["n"] == 1
        assert body["experiments"][0]["experiment_id"] == "mlw_api_001"
    finally:
        app_mod.get_cfg = orig

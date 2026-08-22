"""ML weight experiment module tests."""

from __future__ import annotations

import json

from ashare.ml.weight_experiment import list_weight_experiments, run_ml_weight_experiment


def test_list_weight_experiments_empty(tmp_path):
    cfg = {"_root": str(tmp_path)}
    assert list_weight_experiments(cfg) == []


def test_run_insufficient_sample(tmp_path):
    cfg = {"_root": str(tmp_path), "ml": {}}
    out = run_ml_weight_experiment({}, cfg, persist=True)
    assert out["available"] is False
    assert out["insufficient_sample"] is True
    assert not (tmp_path / "data" / "ml" / "weight_experiments.jsonl").exists()


def test_run_persists_when_available(tmp_path, monkeypatch):
    import pandas as pd

    cfg = {"_root": str(tmp_path), "ml": {}}
    n = 120
    dates = pd.bdate_range("2020-01-02", periods=n)
    rows = []
    for i, d in enumerate(dates):
        rows.append(
            {
                "date": d,
                "symbol": "600000.SH",
                "close": 10.0 + i * 0.01,
                "leader_score": 0.5,
                "factor_score": 0.5,
                "event_score": 0.1,
                "news_score": 0.1,
                "target": 0.01,
                "fwd_excess_5d": 0.005,
            }
        )
    frame = pd.DataFrame(rows)

    class _Engine:
        feature_cols = ["leader_score", "factor_score"]

        def build_training_frame(self, panel):
            return frame.copy()

        def _fit_one(self, x_tr, y_tr, x_te, y_te):
            class _M:
                def predict(self, x):
                    import numpy as np

                    return np.zeros(len(x))

            return _M()

    monkeypatch.setattr("ashare.ml.weight_experiment.MLRankingEngine", lambda _cfg: _Engine())
    monkeypatch.setattr(
        "ashare.ml.weight_experiment.walk_forward_folds",
        lambda data, **kw: [type("F", (), {"name": "f0", "train": data, "test": data})()],
    )

    out = run_ml_weight_experiment({"600000.SH": frame}, cfg, weights=(0.0, 0.1), persist=True)
    assert out["available"] is True
    path = tmp_path / "data" / "ml" / "weight_experiments.jsonl"
    assert path.exists()
    saved = json.loads(path.read_text(encoding="utf-8").strip())
    assert saved["experiment_id"] == out["experiment_id"]

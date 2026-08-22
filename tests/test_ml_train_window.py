from __future__ import annotations

from ashare.config import load_config
from ashare.data.provider import ensure_panel
from ashare.ml.dataset import build_dataset
from ashare.ml.train import _training_fetch_window, train_model


def test_training_fetch_window_covers_ml_dates() -> None:
    cfg = load_config()
    cfg.setdefault("data", {})["provider"] = "sample"
    cfg.setdefault("universe", {})["mode"] = "watchlist"
    cfg["universe"]["symbols"] = ["601288.SH", "601398.SH", "600519.SH"]
    ml = cfg["ml"]
    train_start, train_end, fetch_start, fetch_end = _training_fetch_window(ml, cfg)
    assert fetch_start < train_start
    assert fetch_end >= train_end

    panel = ensure_panel(cfg, cfg["universe"]["symbols"], start=fetch_start, end=fetch_end)
    data = build_dataset(panel, label_horizon=int(ml.get("label_horizon", 5)), start=train_start, end=train_end)
    assert len(data) >= 100


def test_train_model_sample_provider() -> None:
    cfg = load_config()
    cfg.setdefault("data", {})["provider"] = "sample"
    cfg.setdefault("universe", {})["mode"] = "watchlist"
    cfg["universe"]["symbols"] = ["601288.SH", "601398.SH", "600519.SH", "000858.SZ", "000001.SZ"]
    meta = train_model(cfg)
    assert meta.get("run_id")
    assert int(meta.get("n_train") or 0) >= 100

from __future__ import annotations

from typing import Any

import numpy as np

from ashare.factors.library import DEFAULT_WEIGHTS, compute_raw_factors, enrich_leader_features


def factor_weights(cfg: dict[str, Any] | None) -> dict[str, float]:
    raw = dict(DEFAULT_WEIGHTS)
    override = ((cfg or {}).get("factors") or {}).get("weights") or {}
    raw.update({k: float(v) for k, v in override.items() if v is not None})
    s = sum(abs(float(x)) for x in raw.values()) or 1.0
    return {k: float(v) / s for k, v in raw.items()}


def _zscore(values: list[float]) -> list[float]:
    arr = np.array(values, dtype=float)
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    if len(arr) < 2:
        return [0.0 for _ in arr]
    std = float(arr.std())
    if std < 1e-12:
        return [0.0 for _ in arr]
    mean = float(arr.mean())
    return [float((x - mean) / std) for x in arr]


def score_candidates(
    rows: list[dict[str, Any]],
    cfg: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Cross-section z-score of the factor library. No look-ahead: each row is as-of T."""
    if not rows:
        return []
    weights = factor_weights(cfg)
    names = list(weights.keys())
    raw_matrix: dict[str, list[float]] = {n: [] for n in names}
    prepared: list[dict[str, Any]] = []

    for row in rows:
        hist = row.get("hist")
        feats = row.get("feats")
        if feats is None and hist is not None and not hist.empty:
            h = hist.sort_values("date")
            feats = enrich_leader_features(
                h.set_index("date")["close"].astype(float),
                h.set_index("date")["volume"].astype(float) if "volume" in h.columns else None,
                h.set_index("date")["high"].astype(float) if "high" in h.columns else None,
                h.set_index("date")["low"].astype(float) if "low" in h.columns else None,
            )
        if feats is None:
            continue
        meta = {
            "board_count": row.get("board_count", 0),
            "strong_flag": row.get("strong_flag", 0),
            "profit_gap_score": row.get("profit_gap_score", 0),
            "event_score": row.get("event_score", 0),
            "amount": row.get("amount", 0),
        }
        raw = compute_raw_factors(feats, meta)
        item = {**row, "feats": feats, "factors_raw": raw}
        prepared.append(item)
        for n in names:
            raw_matrix[n].append(float(raw.get(n, 0.0)))

    z_cols = {n: _zscore(raw_matrix[n]) for n in names}
    scored: list[dict[str, Any]] = []
    for i, item in enumerate(prepared):
        zmap = {n: z_cols[n][i] for n in names}
        score = sum(weights[n] * zmap[n] for n in names)
        why_bits = sorted(zmap.items(), key=lambda x: -abs(x[1]))[:3]
        why = "；".join(f"{k} z={v:+.2f}" for k, v in why_bits)
        scored.append(
            {
                **{k: v for k, v in item.items() if k != "hist"},
                "factors_z": {k: round(v, 4) for k, v in zmap.items()},
                "score": round(float(score), 6),
                "why": f"龙头因子：{why}",
            }
        )
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored

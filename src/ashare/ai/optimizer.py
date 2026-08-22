from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

from ashare.ai.client import client_from_cfg, parse_json_object
from ashare.factors.library import DEFAULT_WEIGHTS

logger = logging.getLogger("ashare.ai.optimizer")

SYSTEM = """你是 A 股「龙头股」研究系统的参数优化器。
根据模拟盘表现、股票池来源与圆桌结论，调整因子权重与池规则。
硬约束：
- 只输出一个 JSON 对象，不要 Markdown。
- 禁止把系统改回「全市场回调捡便宜」；保持龙头/事件/利润断层方向。
- 禁止要求实盘；不要承诺收益。

允许字段：
{
  "rationale": "中文简短理由",
  "top_n": 1到8整数,
  "max_candidates": 20到80,
  "min_profit_yoy_pct": 30到200,
  "tech_min_pct_chg": 1到8,
  "weights": {
    "rs_20": 0到1,
    "breakout": 0到1,
    "vol_confirm": 0到1,
    "trend": 0到1,
    "board": 0到1,
    "profit_gap": 0到1,
    "event": 0到1,
    "liquidity": 0到1
  },
  "retrain": true/false,
  "label_horizon": 3到10,
  "n_estimators": 80到300
}
"""

ALLOWED = {
    "rationale",
    "top_n",
    "max_candidates",
    "min_profit_yoy_pct",
    "tech_min_pct_chg",
    "weights",
    "retrain",
    "label_horizon",
    "n_estimators",
}


def _clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(v)))


def sanitize_proposal(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in raw.items():
        if k not in ALLOWED:
            continue
        out[k] = v
    if "top_n" in out:
        out["top_n"] = int(_clip(int(out["top_n"]), 1, 8))
    if "max_candidates" in out:
        out["max_candidates"] = int(_clip(int(out["max_candidates"]), 20, 80))
    if "min_profit_yoy_pct" in out:
        out["min_profit_yoy_pct"] = float(_clip(out["min_profit_yoy_pct"], 30, 200))
    if "tech_min_pct_chg" in out:
        out["tech_min_pct_chg"] = float(_clip(out["tech_min_pct_chg"], 1, 8))
    if "weights" in out and isinstance(out["weights"], dict):
        w = {}
        for k in DEFAULT_WEIGHTS:
            if k in out["weights"]:
                w[k] = _clip(out["weights"][k], 0.0, 1.0)
        s = sum(w.values()) or 1.0
        out["weights"] = {k: float(v) / s for k, v in w.items()}
    if "label_horizon" in out:
        out["label_horizon"] = int(_clip(int(out["label_horizon"]), 3, 10))
    if "n_estimators" in out:
        out["n_estimators"] = int(_clip(int(out["n_estimators"]), 80, 300))
    if "retrain" in out:
        out["retrain"] = bool(out["retrain"])
    if "rationale" in out:
        out["rationale"] = str(out["rationale"])[:400]
    return out


def heuristic_proposal(metrics: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    ret = float(metrics.get("paper_return", 0) or 0)
    proposal: dict[str, Any] = {"retrain": False, "rationale": "规则兜底：维持龙头因子方向"}
    weights = dict(((cfg.get("factors") or {}).get("weights")) or DEFAULT_WEIGHTS)
    if ret < -0.03:
        weights["board"] = float(weights.get("board", 0.18)) * 0.7
        weights["profit_gap"] = float(weights.get("profit_gap", 0.16)) * 1.3
        weights["vol_confirm"] = float(weights.get("vol_confirm", 0.1)) * 1.2
        proposal.update(
            {
                "weights": weights,
                "tech_min_pct_chg": 4.0,
                "rationale": "亏损偏大：降低纯连板权重，抬高利润断层与量能确认",
                "retrain": False,
            }
        )
    elif ret > 0.05:
        proposal.update(
            {
                "top_n": min(5, int(cfg.get("strategy", {}).get("top_n", 3)) + 1),
                "rationale": "收益尚可，略放宽入选数量，仍只做龙头/事件池",
            }
        )
    return sanitize_proposal(proposal)


def propose_updates(cfg: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    client = client_from_cfg(cfg)
    if not client.configured:
        return heuristic_proposal(context.get("metrics") or {}, cfg)
    user = json.dumps(context, ensure_ascii=False, default=str)[:8000]
    try:
        text = client.chat(SYSTEM, user, json_mode=True)
        raw = parse_json_object(text)
        proposal = sanitize_proposal(raw)
        if not proposal.get("rationale"):
            proposal["rationale"] = "LLM 已调整龙头研究参数"
        proposal["source"] = "llm"
        return proposal
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM optimize failed, heuristic fallback: %s", exc)
        h = heuristic_proposal(context.get("metrics") or {}, cfg)
        h["source"] = "heuristic"
        h["llm_error"] = str(exc)[:200]
        return h


def apply_proposal(cfg: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(cfg)
    st = out.setdefault("strategy", {})
    pool = out.setdefault("pool", {})
    factors = out.setdefault("factors", {})
    ml = out.setdefault("ml", {})

    if "top_n" in proposal:
        st["top_n"] = proposal["top_n"]
        ml["top_n"] = proposal["top_n"]
    if "max_candidates" in proposal:
        pool["max_candidates"] = proposal["max_candidates"]
    if "min_profit_yoy_pct" in proposal:
        pool["min_profit_yoy_pct"] = proposal["min_profit_yoy_pct"]
    if "tech_min_pct_chg" in proposal:
        pool["tech_min_pct_chg"] = proposal["tech_min_pct_chg"]
    if "weights" in proposal:
        factors["weights"] = proposal["weights"]
    for k in ("label_horizon", "n_estimators"):
        if k in proposal:
            ml[k] = proposal[k]
    st["name"] = st.get("name") or "leader"
    st["picks_style"] = "leader"
    out.setdefault("universe", {})["mode"] = "leader"
    return out


def persist_runtime_overrides(root: str | Path, proposal: dict[str, Any]) -> Path:
    path = Path(root) / "config" / "agent_overrides.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "strategy": {"name": "leader", "picks_style": "leader"},
        "universe": {"mode": "leader"},
        "pool": {},
        "factors": {},
        "ml": {},
    }
    st = payload["strategy"]
    pool = payload["pool"]
    factors = payload["factors"]
    ml = payload["ml"]
    if "top_n" in proposal:
        st["top_n"] = proposal["top_n"]
        ml["top_n"] = proposal["top_n"]
    if "max_candidates" in proposal:
        pool["max_candidates"] = proposal["max_candidates"]
    if "min_profit_yoy_pct" in proposal:
        pool["min_profit_yoy_pct"] = proposal["min_profit_yoy_pct"]
    if "tech_min_pct_chg" in proposal:
        pool["tech_min_pct_chg"] = proposal["tech_min_pct_chg"]
    if "weights" in proposal:
        factors["weights"] = proposal["weights"]
    for k in ("label_horizon", "n_estimators"):
        if k in proposal:
            ml[k] = proposal[k]
    if not pool:
        del payload["pool"]
    if not factors:
        del payload["factors"]
    if not ml:
        del payload["ml"]
    import yaml

    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path

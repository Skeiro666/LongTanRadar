from __future__ import annotations

import json
import logging
from typing import Any

from ashare.ai.client import client_for_role, client_from_cfg, parse_json_object
from ashare.ai.trade_review import fetch_stock_news, kline_summary
from ashare.data.provider import ensure_panel
from ashare.symbols import to_symbol

logger = logging.getLogger("ashare.ai.roundtable")


def _news_pkg(p: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    if p.get("news_package"):
        return p["news_package"]
    try:
        from ashare.news.engine import NewsIntelligenceEngine

        return NewsIntelligenceEngine(cfg).collect_stock(
            str(p.get("symbol") or ""),
            name=str(p.get("name") or ""),
            persist=True,
        )
    except Exception:  # noqa: BLE001
        return {"news_data_incomplete": True, "legacy_headlines": fetch_stock_news(str(p.get("symbol") or ""), 5)}

DEFAULT_ROLES = [
    {
        "id": "dragon",
        "name": "龙头研究员",
        "focus": "板块地位、连板高度、换手、分歧转一致、是否仍是总龙头/中军",
        "stance_hint": "偏多但要说清高度与接力条件",
    },
    {
        "id": "event",
        "name": "事件/业绩研究员",
        "focus": "利润断层是否真实、预告兑现节奏、催化是否一次性、基本面是否跟上价格",
        "stance_hint": "用业绩/事件证伪或确认，不看盘面情绪",
    },
    {
        "id": "risk",
        "name": "风控官",
        "focus": "炸板风险、利空、流动性、ST/退市、T+1无法当日止损、涨停买不进",
        "stance_hint": "必须挑战多头，列出否决项",
    },
    {
        "id": "chair",
        "name": "投委会主席",
        "focus": "综合三位意见交叉论证，给出 buy/watch/pass",
        "stance_hint": "裁决，不能只会附和",
    },
]

ROLE_SYSTEM = """你是 A 股投研委员会的「{name}」。
职责焦点：{focus}
立场要求：{stance_hint}

硬规则：
1. 只输出一个 JSON 对象，不要 Markdown。
2. 只分析龙头/事件/利润断层候选；禁止普通低估值捡便宜话术。
3. 信号为 T 收盘信息，成交假设 T+1；禁止把当日收盘当已成交。
4. 不要承诺收益。
5. 必须给出至少一条可证伪条件。
6. 对名单中每只股票给出你的独立判断。

输出格式：
{{
  "id": "{id}",
  "name": "{name}",
  "model": "你实际使用的模型名可省略",
  "stance": "bull|bear|neutral",
  "confidence": 0.0到1.0,
  "points": ["跨标的共性论点"],
  "challenges": ["对其他角色可能观点的质疑"],
  "falsify": "证伪条件",
  "per_symbol": [
    {{
      "symbol": "000001.SZ",
      "lean": "buy|watch|pass",
      "note": "一句话理由"
    }}
  ]
}}
"""

CHAIR_SYSTEM = """你是 A 股投研委员会主席。下面是多名委员（可能来自不同大模型）的独立意见。
你必须做交叉论证，不能简单多数投票；风控否决权优先于情绪多头。

硬规则：
1. 只输出一个 JSON 对象，不要 Markdown。
2. 对每只股票给出 buy / watch / pass。
3. 在 debate 里写至少 2 条「角色A → 角色B」的交叉质疑纪要。
4. 不要承诺收益。

输出格式：
{
  "debate": [
    {"from": "风控官", "to": "龙头研究员", "point": "交叉质疑"}
  ],
  "decisions": [
    {
      "symbol": "000001.SZ",
      "verdict": "buy|watch|pass",
      "confidence": 0.0到1.0,
      "thesis": "主逻辑",
      "risks": "主要风险",
      "horizon": "T+1~T+5 观察点",
      "rationale": "综合各委员后的主席理由"
    }
  ],
  "summary": "本轮投委会一句话纪要",
  "replay_notes": "如何复盘"
}
"""


def committee_roles(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge yaml roles with defaults; preserve model/base_url overrides."""
    raw = list(((cfg.get("ai") or {}).get("committee") or {}).get("roles") or [])
    by_id = {str(r.get("id")): dict(r) for r in raw if r.get("id")}
    out: list[dict[str, Any]] = []
    for d in DEFAULT_ROLES:
        merged = {**d, **(by_id.get(d["id"]) or {})}
        out.append(merged)
    # allow extra custom roles (except unknown chairs handled separately)
    for rid, r in by_id.items():
        if rid not in {x["id"] for x in out}:
            out.append({**r, "id": rid, "name": r.get("name") or rid})
    return out


def analyst_roles(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in committee_roles(cfg) if str(r.get("id")) != "chair"]


def chair_role(cfg: dict[str, Any]) -> dict[str, Any]:
    for r in committee_roles(cfg):
        if r.get("id") == "chair":
            return r
    return dict(DEFAULT_ROLES[-1])


def _heuristic_role(role: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    per = []
    for c in payload.get("candidates") or []:
        score = float((c.get("quant") or {}).get("score") or 0)
        boards = int(c.get("board_count") or 0)
        gap = float(c.get("profit_gap_score") or 0)
        lean = "watch"
        if role.get("id") == "risk":
            lean = "pass" if boards >= 3 and gap < 1 else ("watch" if score >= 0 else "pass")
        elif gap >= 1.5 or boards >= 2:
            lean = "buy" if score >= 0 else "watch"
        elif score > 0.4:
            lean = "watch"
        else:
            lean = "pass"
        per.append({"symbol": c.get("symbol"), "lean": lean, "note": f"启发式 {role.get('id')}"})
    return {
        "id": role.get("id"),
        "name": role.get("name"),
        "stance": "neutral",
        "confidence": 0.4,
        "points": [f"启发式占位：关注{role.get('focus')}"],
        "challenges": ["LLM 不可用"],
        "falsify": "价格结构破坏或催化证伪",
        "per_symbol": per,
        "model": "heuristic",
        "source": "heuristic",
    }


def _heuristic_chair(payload: dict[str, Any], role_opinions: list[dict[str, Any]]) -> dict[str, Any]:
    decisions = []
    for c in payload.get("candidates") or []:
        sym = c.get("symbol")
        leans = []
        for op in role_opinions:
            for row in op.get("per_symbol") or []:
                if row.get("symbol") == sym:
                    leans.append(str(row.get("lean") or "pass"))
        buy_n = leans.count("buy")
        pass_n = leans.count("pass")
        if pass_n >= 2:
            verdict = "pass"
        elif buy_n >= 2:
            verdict = "buy"
        else:
            verdict = "watch"
        decisions.append(
            {
                "symbol": sym,
                "verdict": verdict,
                "confidence": 0.42,
                "thesis": c.get("thesis") or "启发式综合",
                "risks": "多模型不可用",
                "horizon": "T+1 观察是否缩量断板",
                "rationale": f"启发式票数 lean={leans}",
            }
        )
    return {
        "debate": [
            {"from": "风控官", "to": "龙头研究员", "point": "启发式：连板高度不等于可买"},
            {"from": "事件/业绩研究员", "to": "风控官", "point": "启发式：断层是否已定价需对照预告"},
        ],
        "decisions": decisions,
        "summary": "多模型不可用，规则主席裁决",
        "replay_notes": "对照次日开盘溢价、是否断板、业绩公告是否兑现",
        "source": "heuristic",
    }


def build_roundtable_payload(cfg: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    symbols = [to_symbol(p["symbol"]) for p in candidates if p.get("symbol")]
    panel = ensure_panel(cfg, symbols) if symbols else {}
    rows = []
    for p in candidates:
        sym = to_symbol(p["symbol"])
        df = panel.get(sym)
        pkg = _news_pkg(p, cfg)
        rows.append(
            {
                "symbol": sym,
                "name": p.get("name") or "",
                "quant": {
                    "score": p.get("score"),
                    "factors_z": p.get("factors_z"),
                    "why": p.get("why"),
                    "close": p.get("close") or p.get("price"),
                    "weight": p.get("weight"),
                },
                "board_count": p.get("board_count"),
                "profit_gap_score": p.get("profit_gap_score"),
                "event_score": p.get("event_score"),
                "event_tags": p.get("event_tags"),
                "sources": p.get("sources") or ([p.get("source")] if p.get("source") else []),
                "thesis": p.get("thesis"),
                "yoy_pct": p.get("yoy_pct"),
                "forecast_type": p.get("forecast_type"),
                "kline": kline_summary(df) if df is not None else {},
                "news_package": pkg,
                "news": (pkg.get("legacy_headlines") or fetch_stock_news(sym, limit=5)),
            }
        )
    roles = analyst_roles(cfg)
    return {
        "mandate": "预测分析 A 股龙头股：因子库打分 + 利润断层/事件池 + 多模型投委会",
        "execution": "T 日收盘信息决策，T+1 成交假设，100 股一手",
        "roles": [
            {
                "id": r.get("id"),
                "name": r.get("name"),
                "focus": r.get("focus"),
                "model": r.get("model") or (cfg.get("ai") or {}).get("model"),
            }
            for r in roles
        ],
        "candidates": rows,
    }


def _ask_role(cfg: dict[str, Any], role: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    from ashare.research.intel_package import slim_roundtable_candidate

    client = client_for_role(cfg, str(role["id"]))
    if not client.configured:
        out = _heuristic_role(role, payload)
        out["model"] = "unconfigured"
        return out
    system = ROLE_SYSTEM.format(
        id=role.get("id"),
        name=role.get("name"),
        focus=role.get("focus"),
        stance_hint=role.get("stance_hint") or "",
    )
    role_id = str(role.get("id") or "")
    slim_candidates = [
        slim_roundtable_candidate(c, role_id, cfg=cfg) for c in (payload.get("candidates") or [])
    ]
    user = json.dumps(
        {
            "your_role": role,
            "candidates": slim_candidates,
            "other_roles": payload.get("roles"),
        },
        ensure_ascii=False,
        default=str,
    )[:12000]
    try:
        text = client.chat(
            system,
            user,
            json_mode=True,
            role=str(role.get("id") or ""),
            call_site="roundtable.role",
        )
        data = parse_json_object(text)
        data["id"] = role.get("id")
        data["name"] = data.get("name") or role.get("name")
        data["model"] = client.model
        data["source"] = "llm"
        return data
    except Exception as exc:  # noqa: BLE001
        logger.warning("role %s model=%s failed: %s", role.get("id"), client.model, exc)
        out = _heuristic_role(role, payload)
        out["model"] = client.model
        out["llm_error"] = str(exc)[:200]
        return out


def _ask_risk_rebuttal(
    cfg: dict[str, Any],
    role: dict[str, Any],
    payload: dict[str, Any],
    prior: list[dict[str, Any]],
) -> dict[str, Any]:
    """Risk sees other analysts then issues challenges (second call, same risk model)."""
    from ashare.research.intel_package import slim_roundtable_candidate

    client = client_for_role(cfg, str(role["id"]))
    if not client.configured:
        return _ask_role(cfg, role, payload)
    system = ROLE_SYSTEM.format(
        id=role.get("id"),
        name=role.get("name"),
        focus=role.get("focus") + "；你已看到其他委员意见，必须点名反驳",
        stance_hint="优先否决不可交易/催化证伪的标的",
    )
    slim_candidates = [
        slim_roundtable_candidate(c, "risk", cfg=cfg) for c in (payload.get("candidates") or [])
    ]
    user = json.dumps(
        {
            "your_role": role,
            "candidates": slim_candidates,
            "other_opinions": prior,
        },
        ensure_ascii=False,
        default=str,
    )[:12000]
    try:
        text = client.chat(
            system,
            user,
            json_mode=True,
            role=str(role.get("id") or ""),
            call_site="roundtable.risk_rebuttal",
        )
        data = parse_json_object(text)
        data["id"] = role.get("id")
        data["name"] = data.get("name") or role.get("name")
        data["model"] = client.model
        data["source"] = "llm"
        return data
    except Exception as exc:  # noqa: BLE001
        logger.warning("risk rebuttal failed: %s", exc)
        return _ask_role(cfg, role, payload)


def _ask_chair(
    cfg: dict[str, Any],
    payload: dict[str, Any],
    role_opinions: list[dict[str, Any]],
) -> dict[str, Any]:
    from ashare.research.intel_package import slim_roundtable_candidate

    role = chair_role(cfg)
    client = client_for_role(cfg, "chair")
    if not client.configured:
        # fall back to default client
        client = client_from_cfg(cfg)
    if not client.configured:
        out = _heuristic_chair(payload, role_opinions)
        out["model"] = "unconfigured"
        return out
    slim_candidates = [
        slim_roundtable_candidate(c, "chair", cfg=cfg) for c in (payload.get("candidates") or [])
    ]
    user = json.dumps(
        {
            "candidates": slim_candidates,
            "committee_opinions": role_opinions,
            "chair_role": role,
        },
        ensure_ascii=False,
        default=str,
    )[:14000]
    try:
        text = client.chat(
            CHAIR_SYSTEM,
            user,
            json_mode=True,
            role="chair",
            call_site="roundtable.chair",
        )
        data = parse_json_object(text)
        data["source"] = "llm"
        data["model"] = client.model
        return data
    except Exception as exc:  # noqa: BLE001
        logger.warning("chair model=%s failed: %s", client.model, exc)
        out = _heuristic_chair(payload, role_opinions)
        out["model"] = client.model
        out["llm_error"] = str(exc)[:200]
        return out


def run_roundtable(cfg: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if not candidates:
        return {
            "approved": [],
            "watch": [],
            "rejected": [],
            "reviews": [],
            "roles": [],
            "debate": [],
            "source": "empty",
            "summary": "无候选，圆桌未召开",
            "models_used": [],
        }

    committee = (cfg.get("ai") or {}).get("committee") or {}
    mode = str(committee.get("mode") or "multi_model").lower()
    payload = build_roundtable_payload(cfg, candidates)

    # Legacy: one model roleplays everyone
    if mode in {"single", "one_shot", "legacy"}:
        return _run_single_model(cfg, candidates, payload)

    analysts = analyst_roles(cfg)
    role_opinions: list[dict[str, Any]] = []
    models_used: list[dict[str, str]] = []

    # First pass: non-risk analysts in parallel-ish sequence
    prior_for_risk: list[dict[str, Any]] = []
    risk_role = None
    for role in analysts:
        if role.get("id") == "risk":
            risk_role = role
            continue
        op = _ask_role(cfg, role, payload)
        role_opinions.append(op)
        prior_for_risk.append(op)
        models_used.append({"role": str(role.get("id")), "model": str(op.get("model") or "")})

    if risk_role is not None:
        if bool(committee.get("risk_sees_others", True)) and prior_for_risk:
            risk_op = _ask_risk_rebuttal(cfg, risk_role, payload, prior_for_risk)
        else:
            risk_op = _ask_role(cfg, risk_role, payload)
        role_opinions.append(risk_op)
        models_used.append({"role": "risk", "model": str(risk_op.get("model") or "")})

    chair = _ask_chair(cfg, payload, role_opinions)
    models_used.append({"role": "chair", "model": str(chair.get("model") or "")})

    # Enrich role cards with model label for UI
    roles_out = []
    for op in role_opinions:
        roles_out.append(
            {
                "id": op.get("id"),
                "name": op.get("name"),
                "stance": op.get("stance"),
                "confidence": op.get("confidence"),
                "points": op.get("points") or [],
                "challenges": op.get("challenges") or [],
                "falsify": op.get("falsify"),
                "per_symbol": op.get("per_symbol") or [],
                "model": op.get("model"),
                "source": op.get("source"),
            }
        )

    llm_ok = any(op.get("source") == "llm" for op in role_opinions) or chair.get("source") == "llm"
    raw = {
        "roles": roles_out,
        "debate": chair.get("debate") or [],
        "decisions": chair.get("decisions") or [],
        "summary": chair.get("summary") or "",
        "replay_notes": chair.get("replay_notes") or "",
        "source": "multi_model" if llm_ok else "heuristic",
        "models_used": models_used,
        "chair_model": chair.get("model"),
        "llm_error": chair.get("llm_error"),
    }
    return _finalize(candidates, payload, raw)


def _run_single_model(
    cfg: dict[str, Any],
    candidates: list[dict[str, Any]],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Backward-compatible one-shot roleplay (not true multi-model)."""
    client = client_from_cfg(cfg)
    system = """你是投研秘书，用一个模型扮演多角色并输出 JSON（roles/debate/decisions/summary/replay_notes）。"""
    if not client.configured:
        raw = _heuristic_chair(payload, [_heuristic_role(r, payload) for r in analyst_roles(cfg)])
        raw["roles"] = [_heuristic_role(r, payload) for r in analyst_roles(cfg)]
        return _finalize(candidates, payload, raw)
    try:
        text = client.chat(
            system + "\n" + CHAIR_SYSTEM,
            json.dumps(payload, ensure_ascii=False, default=str)[:14000],
            json_mode=True,
            role="all",
            call_site="roundtable.single_model",
        )
        raw = parse_json_object(text)
        raw["source"] = "llm_single"
        raw["models_used"] = [{"role": "all", "model": client.model}]
    except Exception as exc:  # noqa: BLE001
        raw = _heuristic_chair(payload, [_heuristic_role(r, payload) for r in analyst_roles(cfg)])
        raw["roles"] = [_heuristic_role(r, payload) for r in analyst_roles(cfg)]
        raw["llm_error"] = str(exc)[:240]
    return _finalize(candidates, payload, raw)


def _finalize(
    candidates: list[dict[str, Any]],
    payload: dict[str, Any],
    raw: dict[str, Any],
) -> dict[str, Any]:
    by_sym = {to_symbol(d.get("symbol")): d for d in (raw.get("decisions") or []) if d.get("symbol")}
    approved: list[dict[str, Any]] = []
    watch: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    for p in candidates:
        sym = to_symbol(p["symbol"])
        d = by_sym.get(sym) or {
            "verdict": "pass",
            "rationale": "主席未覆盖该标的，默认 pass",
            "confidence": 0.0,
        }
        verdict = str(d.get("verdict") or "pass").lower()
        if verdict not in {"buy", "watch", "pass"}:
            verdict = "pass"
        approve = verdict == "buy"
        item = {
            **p,
            "committee_verdict": verdict,
            "committee_approve": approve,
            "ai_approve": approve,
            "ai_confidence": d.get("confidence"),
            "ai_rationale": d.get("rationale") or d.get("thesis") or "",
            "committee_thesis": d.get("thesis") or "",
            "committee_risks": d.get("risks") or "",
            "committee_horizon": d.get("horizon") or "",
            "ai_source": raw.get("source"),
        }
        reviews.append(item)
        if verdict == "buy":
            approved.append(item)
        elif verdict == "watch":
            watch.append(item)
        else:
            rejected.append(item)

    return {
        "approved": approved,
        "watch": watch,
        "rejected": rejected,
        "reviews": reviews,
        "roles": raw.get("roles") or [],
        "debate": raw.get("debate") or [],
        "source": raw.get("source"),
        "summary": raw.get("summary") or "",
        "replay_notes": raw.get("replay_notes") or "",
        "models_used": raw.get("models_used") or [],
        "chair_model": raw.get("chair_model"),
        "llm_error": raw.get("llm_error"),
        "payload_preview": [
            {
                "symbol": c["symbol"],
                "name": c.get("name"),
                "tags": c.get("event_tags"),
                "news_titles": [n.get("title") for n in (c.get("news") or [])[:3]],
            }
            for c in payload.get("candidates") or []
        ],
    }

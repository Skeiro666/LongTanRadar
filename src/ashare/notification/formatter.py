from __future__ import annotations

import os
from typing import Any

from ashare.config_loaders import load_yaml_config


def _cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    return load_yaml_config(cfg, "notification")


def research_url(cfg: dict[str, Any] | None, research_id: str) -> str:
    n_cfg = _cfg(cfg)
    base = os.getenv("PUBLIC_BASE_URL") or str(n_cfg.get("public_base_url") or "").rstrip("/")
    if base:
        return f"{base}/research?session={research_id}"
    return f"/research?session={research_id}"


def _role_summary(council: dict[str, Any], role_id: str) -> str:
    op = dict(council.get(role_id) or {})
    if not op:
        return "—"
    parts = []
    if op.get("stance"):
        parts.append(str(op["stance"]))
    pts = op.get("points") or op.get("facts") or []
    if pts:
        parts.append(str(pts[0])[:80])
    return " · ".join(parts) if parts else str(op.get("summary") or op.get("score") or "—")[:80]


def format_notification(
    *,
    level: str,
    canonical: dict[str, Any],
    snapshot: dict[str, Any] | None,
    report: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
) -> str:
    """Render notification body from existing research — zero LLM."""
    snap = snapshot or {}
    rep = report or {}
    sym = canonical.get("symbol") or rep.get("symbol") or "?"
    name = canonical.get("name") or rep.get("name") or sym
    market = snap.get("market") or (rep.get("snapshot") or {}).get("market") or {}
    price = market.get("price") or market.get("close") or "—"
    rating = canonical.get("research_rating") or (rep.get("decision") or {}).get("research_rating") or level
    action = canonical.get("trading_action") or (rep.get("decision") or {}).get("action") or "—"
    chairman = snap.get("chairman") or rep.get("chairman") or {}
    council = snap.get("council") or rep.get("council") or {}
    meta = dict(snap.get("candidate_score_meta") or {})
    eer = dict(meta.get("expected_excess_return") or {})
    eer_txt = "—"
    if eer.get("available") and eer.get("value") is not None:
        eer_txt = f"{float(eer['value']) * 100:+.1f}%"
    conf = canonical.get("confidence") or chairman.get("confidence")
    conf_txt = "—"
    if conf is not None:
        cv = float(conf)
        conf_txt = f"{cv * 100:.0f}%" if cv <= 1 else f"{cv:.0f}%"
    risk = str(canonical.get("risk_status") or "—").upper()
    inv = list((chairman.get("invalidation") or chairman.get("invalidations") or rep.get("invalidation") or []))
    if not inv:
        inv = list(chairman.get("risks") or [])[:3]
    evidence = []
    pkg = snap.get("news_package") or rep.get("news_package") or {}
    for eid in (pkg.get("evidence_ids") or [])[:5]:
        evidence.append(str(eid))
    research_time = rep.get("research_time") or snap.get("research_time") or canonical.get("as_of") or "—"
    rid = canonical.get("research_session_id") or rep.get("research_id") or ""
    url = research_url(cfg, rid)

    title = "🚨 寻龙尺 买入机会"
    if level == "STRONG_BUY":
        title = "🔥 寻龙尺 强买入机会"
    elif level == "RISK_EXIT":
        title = "⚠️ 寻龙尺 风险退出提醒"

    lines = [
        title,
        "",
        "━━━━━━━━━━━━━━",
        "",
        f"股票：\n{name} {sym}",
        "",
        f"参考价：\n{price}",
        "",
        f"评级：\n{rating}",
        "",
        f"交易动作：\n{action}",
        "",
        f"预期超额收益：\n{eer_txt}",
        "",
        f"置信度：\n{conf_txt}",
        "",
        "━━━━━━━━━━━━━━",
        "",
        "主要理由：",
        "",
        f"Quant：\n{_role_summary(council, 'quant')}",
        "",
        f"Event：\n{_role_summary(council, 'event')}",
        "",
        f"News：\n{_role_summary(council, 'news') or _role_summary(council, 'event')}",
        "",
        f"ML：\n{_role_summary(council, 'quant')}",
        "",
        "━━━━━━━━━━━━━━",
        "",
        "投委会：",
        "",
        f"Bull：\n{_role_summary(council, 'fundamental')}",
        "",
        f"Bear：\n{_role_summary(council, 'bear') or _role_summary(council, 'risk')}",
        "",
        f"Chairman：\n{str(chairman.get('base_case') or chairman.get('rationale') or '—')[:200]}",
        "",
        "━━━━━━━━━━━━━━",
        "",
        f"风险：\n{risk}",
        "",
        "━━━━━━━━━━━━━━",
        "",
        "失效条件：",
    ]
    for i, cond in enumerate(inv[:3], 1):
        lines.append(f"{i}. {cond}")
    if not inv:
        lines.append("1. —")
    lines.extend(
        [
            "",
            "━━━━━━━━━━━━━━",
            "",
            "证据：",
            "",
            "\n".join(evidence) if evidence else "—",
            "",
            "━━━━━━━━━━━━━━",
            "",
            f"研究时间：\n{research_time}",
            "",
            "Benchmark：\nCSI300",
            "",
            "━━━━━━━━━━━━━━",
            "",
            f"完整研报：\n{url}",
        ]
    )
    return "\n".join(lines)

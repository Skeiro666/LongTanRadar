from __future__ import annotations

from typing import Any

from ashare.research.cache import compute_context_hash, extract_version_meta
from ashare.research.dynamic_council import COUNCIL_ROLE_IDS, plan_council, select_council_roles
from ashare.research.intel_package import build_role_context

CHANGE_REASONS = (
    "NEW_EVENT",
    "NEW_NEWS",
    "PRICE_MOVE",
    "FACTOR_CHANGE",
    "RISK_CHANGE",
    "PROMPT_CHANGE",
    "MODEL_CHANGE",
    "MANUAL_REFRESH",
    "LIVE_STATE_DIVERGENCE",
    "NO_CHANGE",
)


def _incremental_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    if not cfg:
        return {"enabled": True}
    from ashare.config_loaders import load_yaml_config

    inc = dict(load_yaml_config(cfg, "research").get("incremental_research") or {})
    return {"enabled": bool(inc.get("enabled", True))}


def role_context_hash(snapshot: dict[str, Any], role_id: str, cfg: dict[str, Any] | None) -> str:
    from ashare.config_loaders import load_yaml_config

    research_cfg = load_yaml_config(cfg, "research") if cfg else {}
    meta = extract_version_meta(snapshot)
    ctx = build_role_context(snapshot, role_id, cfg=cfg)
    ver = f"{role_id}_v1"
    return compute_context_hash(
        symbol=str(snapshot.get("symbol") or ""),
        role_id=role_id,
        context=ctx,
        prompt_version=ver,
        model="incremental",
        factor_version=meta["factor_version"],
        news_version=meta["news_version"],
        model_version=meta["model_version"],
        as_of=meta["as_of"],
        candidate_hash=meta["candidate_hash"],
    )


def detect_change_reasons(
    snapshot: dict[str, Any],
    prior_snapshot: dict[str, Any] | None,
    cfg: dict[str, Any] | None = None,
) -> list[str]:
    if not prior_snapshot:
        return ["MANUAL_REFRESH"]
    reasons: list[str] = []
    cur_meta = extract_version_meta(snapshot)
    prev_meta = extract_version_meta(prior_snapshot)
    if cur_meta["factor_version"] != prev_meta["factor_version"] or cur_meta["candidate_hash"] != prev_meta["candidate_hash"]:
        reasons.append("FACTOR_CHANGE")
    if cur_meta["news_version"] != prev_meta["news_version"]:
        reasons.append("NEW_NEWS")
    cur_news = snapshot.get("news_snapshot") or {}
    prev_news = prior_snapshot.get("news_snapshot") or {}
    if set(cur_news.get("event_ids") or []) - set(prev_news.get("event_ids") or []):
        reasons.append("NEW_EVENT")
    cur_px = float((snapshot.get("market") or {}).get("pct_chg") or 0)
    prev_px = float((prior_snapshot.get("market") or {}).get("pct_chg") or 0)
    if abs(cur_px - prev_px) >= 3.0:
        reasons.append("PRICE_MOVE")
    cur_risk = str(snapshot.get("price_in_risk") or "")
    prev_risk = str(prior_snapshot.get("price_in_risk") or "")
    if cur_risk != prev_risk:
        reasons.append("RISK_CHANGE")
    if cur_meta["model_version"] != prev_meta["model_version"]:
        reasons.append("MODEL_CHANGE")
    try:
        from ashare.services.state_reconciliation import has_pending_live_divergence

        if has_pending_live_divergence(str(snapshot.get("symbol") or ""), cfg):
            reasons.append("LIVE_STATE_DIVERGENCE")
    except Exception:  # noqa: BLE001
        pass
    active = select_council_roles(snapshot, cfg)
    for rid in active:
        if role_context_hash(snapshot, rid, cfg) != role_context_hash(prior_snapshot, rid, cfg):
            if "PROMPT_CHANGE" not in reasons:
                reasons.append("PROMPT_CHANGE")
            break
    return reasons or ["NO_CHANGE"]


def roles_to_refresh(
    snapshot: dict[str, Any],
    prior_snapshot: dict[str, Any] | None,
    cfg: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    """Return council roles that need a fresh LLM call vs prior snapshot for same symbol."""
    active = select_council_roles(snapshot, cfg)
    if not _incremental_cfg(cfg).get("enabled", True) or not prior_snapshot:
        return active

    reasons = detect_change_reasons(snapshot, prior_snapshot, cfg)
    if reasons == ["NO_CHANGE"]:
        return ()
    # Live divergence must force a fresh council pass (advisory context may change mid-session).
    if "LIVE_STATE_DIVERGENCE" in reasons:
        return tuple(rid for rid in active if not (rid == "valuation" and not snapshot.get("value_available", False)))

    refresh: list[str] = []
    for rid in active:
        if rid == "valuation" and not snapshot.get("value_available", False):
            continue
        cur_h = role_context_hash(snapshot, rid, cfg)
        prev_h = role_context_hash(prior_snapshot, rid, cfg)
        if cur_h != prev_h:
            refresh.append(rid)
    return tuple(refresh)


def merge_prior_opinions(
    active_roles: tuple[str, ...],
    fresh: dict[str, Any],
    prior: dict[str, Any] | None,
) -> dict[str, Any]:
    out = dict(prior or {})
    for rid in active_roles:
        if rid in fresh:
            out[rid] = fresh[rid]
        elif rid in out:
            reused = dict(out[rid])
            reused["source"] = reused.get("source") or "incremental_reuse"
            out[rid] = reused
    return out

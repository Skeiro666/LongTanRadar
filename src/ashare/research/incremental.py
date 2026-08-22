from __future__ import annotations

from typing import Any

from ashare.research.cache import compute_context_hash
from ashare.research.dynamic_council import COUNCIL_ROLE_IDS, select_council_roles
from ashare.research.intel_package import build_role_context


def _incremental_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    if not cfg:
        return {"enabled": True}
    from ashare.config_loaders import load_yaml_config

    inc = dict(load_yaml_config(cfg, "research").get("incremental_research") or {})
    return {"enabled": bool(inc.get("enabled", True))}


def role_context_hash(snapshot: dict[str, Any], role_id: str, cfg: dict[str, Any] | None) -> str:
    from ashare.config_loaders import load_yaml_config

    research_cfg = load_yaml_config(cfg, "research") if cfg else {}
    factor_version = str((research_cfg.get("snapshot") or {}).get("factor_version") or "factor_v1")
    ctx = build_role_context(snapshot, role_id, cfg=cfg)
    ver = f"{role_id}_v1"
    return compute_context_hash(
        symbol=str(snapshot.get("symbol") or ""),
        role_id=role_id,
        context=ctx,
        prompt_version=ver,
        model="incremental",
        factor_version=factor_version,
    )


def roles_to_refresh(
    snapshot: dict[str, Any],
    prior_snapshot: dict[str, Any] | None,
    cfg: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    """Return council roles that need a fresh LLM call vs prior snapshot for same symbol."""
    active = select_council_roles(snapshot, cfg)
    if not _incremental_cfg(cfg).get("enabled", True) or not prior_snapshot:
        return active

    refresh: list[str] = []
    for rid in active:
        if rid == "valuation" and not snapshot.get("value_available", False):
            continue
        cur_h = role_context_hash(snapshot, rid, cfg)
        prev_h = role_context_hash(prior_snapshot, rid, cfg)
        if cur_h != prev_h:
            refresh.append(rid)
    # chairman refresh if any analyst role refreshed
    if refresh:
        return tuple(refresh)
    return ()


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

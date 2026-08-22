from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _cache_cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    if not cfg:
        return {"enabled": True, "dir": "data/cache/research", "ttl_hours": 24}
    from ashare.config_loaders import load_yaml_config

    research = load_yaml_config(cfg, "research")
    rc = dict(research.get("research_cache") or {})
    return {
        "enabled": bool(rc.get("enabled", True)),
        "dir": str(rc.get("dir") or "data/cache/research"),
        "ttl_hours": float(rc.get("ttl_hours") or 24),
    }


def compute_candidate_hash(candidate: dict[str, Any]) -> str:
    """Hash of scores/sources that affect research relevance — not full snapshot."""
    blob = {
        "candidate_score": round(float(candidate.get("candidate_score") or 0), 6),
        "candidate_sources": sorted(candidate.get("candidate_sources") or []),
        "leader_score": round(float(candidate.get("leader_score") or 0), 6),
        "event_score": round(float(candidate.get("event_score") or 0), 6),
        "news_score": round(float(candidate.get("news_score") or 0), 6),
        "ml_rank_score": round(float(candidate.get("ml_rank_score") or 0), 6)
        if candidate.get("ml_rank_score") is not None
        else None,
    }
    raw = json.dumps(blob, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def extract_version_meta(snapshot: dict[str, Any]) -> dict[str, str]:
    vers = dict(snapshot.get("versions") or {})
    news_snap = dict(snapshot.get("news_snapshot") or {})
    news_pkg = dict(snapshot.get("news_package") or {})
    pkg_vers = dict(news_pkg.get("versions") or {})
    quant = dict(snapshot.get("quant") or {})
    as_of = str(snapshot.get("as_of") or (snapshot.get("snapshot_time") or "")[:10] or "")
    cand_hash = compute_candidate_hash(
        {
            "candidate_score": quant.get("factor_score"),
            "candidate_sources": snapshot.get("candidate_sources"),
            "leader_score": quant.get("leader_score"),
            "event_score": (snapshot.get("event") or {}).get("score"),
            "news_score": news_pkg.get("net_event_score"),
            "ml_rank_score": quant.get("ml_rank_score"),
        }
    )
    return {
        "as_of": as_of,
        "factor_version": str(vers.get("factor_version") or "factor_v1"),
        "news_version": str(
            news_snap.get("news_data_version")
            or pkg_vers.get("news_data_version")
            or pkg_vers.get("provider_version")
            or "news_v1"
        ),
        "model_version": str(vers.get("model_bundle") or "models_v1"),
        "candidate_hash": cand_hash,
    }


def compute_context_hash(
    *,
    symbol: str,
    role_id: str,
    context: dict[str, Any],
    prompt_version: str,
    model: str,
    factor_version: str = "",
    news_version: str = "",
    model_version: str = "",
    as_of: str = "",
    candidate_hash: str = "",
) -> str:
    blob = json.dumps(
        {
            "symbol": symbol,
            "role_id": role_id,
            "prompt_version": prompt_version,
            "model": model,
            "factor_version": factor_version,
            "news_version": news_version,
            "model_version": model_version,
            "as_of": as_of,
            "candidate_hash": candidate_hash,
            "context": context,
        },
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


class ResearchCache:
    """Disk cache for council/chairman LLM JSON responses keyed by context hash."""

    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        self.cfg = cfg or {}
        cc = _cache_cfg(cfg)
        self.enabled = bool(cc["enabled"])
        root = Path(self.cfg.get("_root") or Path(__file__).resolve().parents[2])
        self.dir = root / cc["dir"]
        self.ttl = timedelta(hours=float(cc["ttl_hours"]))

    def get(self, key: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        path = self.dir / f"{key}.json"
        if not path.exists():
            return None
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
        ts = row.get("cached_at")
        if ts:
            try:
                cached_at = datetime.fromisoformat(str(ts))
                if cached_at.tzinfo is None:
                    cached_at = cached_at.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - cached_at > self.ttl:
                    return None
            except Exception:  # noqa: BLE001
                pass
        resp = row.get("response")
        return dict(resp) if isinstance(resp, dict) else None

    def set(self, key: str, response: dict[str, Any], meta: dict[str, Any] | None = None) -> None:
        if not self.enabled:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / f"{key}.json"
        payload = {
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "response": response,
            "meta": meta or {},
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


_cache_singleton: ResearchCache | None = None


def get_research_cache(cfg: dict[str, Any] | None = None) -> ResearchCache:
    global _cache_singleton
    if cfg is not None:
        _cache_singleton = ResearchCache(cfg)
    elif _cache_singleton is None:
        _cache_singleton = ResearchCache({})
    return _cache_singleton

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    load_dotenv()
    root = project_root()
    cfg_path = Path(path) if path else root / "config" / "default.yaml"
    if not cfg_path.is_absolute():
        cfg_path = root / cfg_path

    with cfg_path.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    overrides_path = root / "config" / "agent_overrides.yaml"
    if overrides_path.exists():
        with overrides_path.open("r", encoding="utf-8") as f:
            extra = yaml.safe_load(f) or {}
        if isinstance(extra, dict):
            cfg = _deep_merge(cfg, extra)

    paper = cfg.setdefault("paper", {})
    if "state_file" in paper:
        sf = Path(paper["state_file"])
        if not sf.is_absolute():
            paper["state_file"] = str(root / sf)

    data = cfg.setdefault("data", {})
    if "cache_dir" in data:
        kd = Path(data["cache_dir"])
        if not kd.is_absolute():
            data["cache_dir"] = str(root / kd)

    monitor = cfg.setdefault("monitor", {})
    if "log_dir" in monitor:
        ld = Path(monitor["log_dir"])
        if not ld.is_absolute():
            monitor["log_dir"] = str(root / ld)

    ai = cfg.setdefault("ai", {})
    if "cache_dir" in ai:
        ad = Path(ai["cache_dir"])
        if not ad.is_absolute():
            ai["cache_dir"] = str(root / ad)
    if os.getenv("AI_BASE_URL"):
        ai["base_url"] = os.getenv("AI_BASE_URL")
    if os.getenv("AI_MODEL"):
        ai["model"] = os.getenv("AI_MODEL")
    if os.getenv("AI_PROVIDER"):
        ai["provider"] = os.getenv("AI_PROVIDER")
    key_env = str(ai.get("api_key_env", "AI_API_KEY"))
    # Official DeepSeek samples use DEEPSEEK_API_KEY; OpenAI uses OPENAI_API_KEY
    api_key = (
        os.getenv(key_env, "")
        or os.getenv("AI_API_KEY", "")
        or os.getenv("SILICONFLOW_API_KEY", "")
        or os.getenv("DASHSCOPE_API_KEY", "")
        or os.getenv("DEEPSEEK_API_KEY", "")
        or os.getenv("OPENAI_API_KEY", "")
    )
    if not ai.get("provider"):
        from ashare.ai.client import detect_provider

        ai["provider"] = detect_provider(
            str(ai.get("base_url") or "https://api.siliconflow.cn/v1")
        )

    # Multi-model committee: AI_MODEL_DRAGON / EVENT / RISK / CHAIR (+ optional BASE_URL / API_KEY)
    committee = ai.setdefault("committee", {})
    committee.setdefault("mode", "multi_model")
    roles = list(committee.get("roles") or [])
    role_env_map = {
        "dragon": "AI_MODEL_DRAGON",
        "event": "AI_MODEL_EVENT",
        "risk": "AI_MODEL_RISK",
        "chair": "AI_MODEL_CHAIR",
    }
    by_id = {str(r.get("id")): dict(r) for r in roles if r.get("id")}
    for rid, env_name in role_env_map.items():
        row = by_id.get(rid) or {"id": rid}
        if os.getenv(env_name):
            row["model"] = os.getenv(env_name)
        base_env = f"AI_BASE_URL_{rid.upper()}"
        key_role_env = f"AI_API_KEY_{rid.upper()}"
        if os.getenv(base_env):
            row["base_url"] = os.getenv(base_env)
        if os.getenv(key_role_env):
            row["api_key"] = os.getenv(key_role_env)
            row["api_key_env"] = key_role_env
        # default model to global if still missing
        row.setdefault("model", ai.get("model"))
        by_id[rid] = row
    # keep yaml order, ensure all four exist
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in roles:
        rid = str(r.get("id"))
        if rid in by_id:
            ordered.append({**r, **by_id[rid]})
            seen.add(rid)
    for rid in ("dragon", "event", "risk", "chair"):
        if rid not in seen:
            ordered.append(by_id[rid])
    for rid, row in by_id.items():
        if rid not in seen and rid not in {"dragon", "event", "risk", "chair"}:
            ordered.append(row)
    committee["roles"] = ordered

    ml = cfg.setdefault("ml", {})
    if "models_dir" in ml:
        md = Path(ml["models_dir"])
        if not md.is_absolute():
            ml["models_dir"] = str(root / md)
    if ml.get("model_path"):
        mp = Path(ml["model_path"])
        if not mp.is_absolute():
            ml["model_path"] = str(root / mp)

    cfg["_root"] = str(root)
    cfg["_config_path"] = str(cfg_path)
    env_bag = {
        "AI_API_KEY": api_key,
        "SILICONFLOW_API_KEY": os.getenv("SILICONFLOW_API_KEY", "") or api_key,
        "DASHSCOPE_API_KEY": os.getenv("DASHSCOPE_API_KEY", ""),
        "DEEPSEEK_API_KEY": os.getenv("DEEPSEEK_API_KEY", ""),
        "MOONSHOT_API_KEY": os.getenv("MOONSHOT_API_KEY", ""),
        "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
        "TUSHARE_TOKEN": os.getenv("TUSHARE_TOKEN", ""),
        "I_UNDERSTAND_LIVE": os.getenv("I_UNDERSTAND_LIVE", "0"),
        "QMT_ACCOUNT_ID": os.getenv("QMT_ACCOUNT_ID", ""),
        "QMT_USERDATA_PATH": os.getenv("QMT_USERDATA_PATH", ""),
        "BROKER_MODE": os.getenv("BROKER_MODE", cfg.get("broker", {}).get("mode", "paper")),
        "DATABASE_URL": os.getenv("DATABASE_URL", ""),
        "REDIS_URL": os.getenv("REDIS_URL", ""),
    }
    for rid in ("DRAGON", "EVENT", "RISK", "CHAIR"):
        k = f"AI_API_KEY_{rid}"
        if os.getenv(k):
            env_bag[k] = os.getenv(k, "")
    cfg["_env"] = env_bag
    return cfg

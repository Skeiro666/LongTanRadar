from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any, Optional

import redis


def redis_url_from_env(cfg: dict[str, Any] | None = None) -> str:
    url = os.getenv("REDIS_URL", "")
    if not url and cfg:
        url = str(cfg.get("storage", {}).get("redis_url", ""))
    return url or "redis://127.0.0.1:6379/0"


@lru_cache(maxsize=2)
def get_redis(url: str) -> redis.Redis:
    return redis.Redis.from_url(url, decode_responses=True)


def ping_redis(url: str) -> bool:
    try:
        return bool(get_redis(url).ping())
    except Exception:
        return False


def cache_set(url: str, key: str, value: Any, ttl: int = 3600) -> None:
    get_redis(url).setex(key, ttl, json.dumps(value, ensure_ascii=False, default=str))


def cache_get(url: str, key: str) -> Optional[Any]:
    raw = get_redis(url).get(key)
    if raw is None:
        return None
    return json.loads(raw)

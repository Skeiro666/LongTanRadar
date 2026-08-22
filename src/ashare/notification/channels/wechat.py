"""Enterprise WeChat bot webhook — no secrets in code."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from ashare.config_loaders import load_yaml_config

logger = logging.getLogger(__name__)


def _mask_url(url: str) -> str:
    if len(url) <= 20:
        return "***"
    return url[:12] + "..." + url[-4:]


def _cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    n = load_yaml_config(cfg, "notification")
    return dict(n.get("wechat") or {})


def send_wechat(text: str, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    wcfg = _cfg(cfg)
    if not wcfg.get("enabled", True):
        return {"ok": False, "skipped": True, "reason": "wechat_disabled"}
    url = os.getenv("WECHAT_WEBHOOK_URL", "").strip()
    if not url:
        return {"ok": False, "skipped": True, "reason": "WECHAT_WEBHOOK_URL unset"}

    timeout = float(wcfg.get("timeout_sec", 10))
    retries = int(wcfg.get("max_retries", 3))
    delay = float(wcfg.get("retry_delay_sec", 2))
    payload = {"msgtype": "text", "text": {"content": text[:4000]}}

    last_err = ""
    for attempt in range(retries):
        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(url, json=payload)
            if resp.status_code == 200:
                body = resp.json()
                if body.get("errcode") == 0:
                    logger.info("wechat sent ok webhook=%s", _mask_url(url))
                    return {"ok": True, "channel": "wechat"}
                last_err = str(body.get("errmsg") or body)
            else:
                last_err = f"HTTP {resp.status_code}"
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)[:200]
            logger.warning("wechat attempt %s failed webhook=%s err=%s", attempt + 1, _mask_url(url), last_err)
        if attempt + 1 < retries:
            time.sleep(delay)
    return {"ok": False, "error": last_err, "channel": "wechat"}

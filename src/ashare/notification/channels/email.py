"""SMTP email notifications — credentials from env only."""

from __future__ import annotations

import logging
import os
import smtplib
import time
from email.mime.text import MIMEText
from typing import Any

from ashare.config_loaders import load_yaml_config

logger = logging.getLogger(__name__)


def _cfg(cfg: dict[str, Any] | None) -> dict[str, Any]:
    n = load_yaml_config(cfg, "notification")
    return dict(n.get("email") or {})


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def send_email(subject: str, body: str, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    ecfg = _cfg(cfg)
    if not ecfg.get("enabled", True):
        return {"ok": False, "skipped": True, "reason": "email_disabled"}

    host = _env("SMTP_HOST")
    port = int(_env("SMTP_PORT") or "587")
    user = _env("SMTP_USER")
    password = _env("SMTP_PASSWORD")
    from_addr = _env("NOTIFY_EMAIL_FROM")
    to_addr = _env("NOTIFY_EMAIL_TO")

    if not all([host, user, password, from_addr, to_addr]):
        return {"ok": False, "skipped": True, "reason": "smtp_env_incomplete"}

    timeout = float(ecfg.get("timeout_sec", 15))
    retries = int(ecfg.get("max_retries", 3))
    delay = float(ecfg.get("retry_delay_sec", 3))
    use_tls = bool(ecfg.get("use_tls", True))

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject[:200]
    msg["From"] = from_addr
    msg["To"] = to_addr

    last_err = ""
    for attempt in range(retries):
        try:
            with smtplib.SMTP(host, port, timeout=timeout) as smtp:
                if use_tls:
                    smtp.starttls()
                smtp.login(user, password)
                smtp.sendmail(from_addr, [to_addr], msg.as_string())
            logger.info("email sent ok to=%s host=%s", to_addr.split("@")[0] + "@***", host)
            return {"ok": True, "channel": "email"}
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)[:200]
            logger.warning("email attempt %s failed host=%s err=%s", attempt + 1, host, last_err)
        if attempt + 1 < retries:
            time.sleep(delay)
    return {"ok": False, "error": last_err, "channel": "email"}

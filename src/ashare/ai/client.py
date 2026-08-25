from __future__ import annotations

import json
import logging
import re
import time
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("ashare.ai")

# DeepSeek / OpenAI JSON Output：prompt 须含 "json"，否则可能 400
_JSON_HINT = (
    "\n\nOutput must be a single valid JSON object only "
    "(no markdown fences). Follow the JSON schema described above."
)


def detect_provider(base_url: str, hint: str | None = None) -> str:
    if hint:
        h = hint.lower().strip()
        if h in {"qwen", "dashscope", "bailian"}:
            return "qwen"
        if h in {"kimi", "moonshot"}:
            return "kimi"
        if h in {"siliconflow", "silicon", "sf"}:
            return "siliconflow"
        if h in {"local"}:
            return "ollama"
        if h in {"deepseek", "openai", "ollama", "compatible"}:
            return h
    host = (urlparse(base_url or "").hostname or "").lower()
    path = (urlparse(base_url or "").path or "").lower()
    if "siliconflow" in host:
        return "siliconflow"
    if "deepseek" in host:
        return "deepseek"
    if "dashscope" in host or "compatible-mode" in path or "aliyuncs.com" in host:
        return "qwen"
    if "moonshot" in host:
        return "kimi"
    if "openai.com" in host:
        return "openai"
    if host in {"127.0.0.1", "localhost"} or ":11434" in (base_url or ""):
        return "ollama"
    return "compatible"


def extract_chat_content(message: Any) -> str:
    """Qwen3.5 via Ollama /v1 often leaves content empty and fills reasoning_*."""
    names = ("content", "reasoning_content", "reasoning")
    extra: dict[str, Any] = {}
    if not isinstance(message, dict):
        extra = dict(getattr(message, "model_extra", None) or {})
    for name in names:
        val = message.get(name) if isinstance(message, dict) else getattr(message, name, extra.get(name))
        if val is None:
            val = extra.get(name)
        text = str(val).strip() if val is not None else ""
        if text:
            return text
    return ""


def normalize_openai_base_url(base_url: str, *, provider: str | None = None) -> str:
    """
    Official OpenAI-SDK base_url values:
      SiliconFlow: https://api.siliconflow.cn/v1
      Qwen/百炼:   https://dashscope.aliyuncs.com/compatible-mode/v1
      DeepSeek:    https://api.deepseek.com
      Kimi:        https://api.moonshot.cn/v1
    """
    raw = (base_url or "").strip().rstrip("/")
    prov = detect_provider(raw, provider)
    if not raw:
        defaults = {
            "siliconflow": "https://api.siliconflow.cn/v1",
            "deepseek": "https://api.deepseek.com",
            "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "kimi": "https://api.moonshot.cn/v1",
            "openai": "https://api.openai.com/v1",
            "ollama": "http://127.0.0.1:11434/v1",
        }
        return defaults.get(prov, "https://api.siliconflow.cn/v1")

    if prov == "deepseek":
        while raw.endswith("/v1"):
            raw = raw[: -len("/v1")].rstrip("/")
        return raw or "https://api.deepseek.com"

    if prov == "qwen":
        if "compatible-mode" in raw:
            return raw if raw.endswith("/v1") else f"{raw}/v1"
        return f"{raw}/compatible-mode/v1"

    # siliconflow / kimi / openai / ollama / compatible → keep or append /v1
    return raw if raw.endswith("/v1") else f"{raw}/v1"


def chat_completions_url(base_url: str, *, provider: str | None = None) -> str:
    """Absolute POST URL for HTTP fallback (mirrors official curl paths)."""
    prov = detect_provider(base_url, provider)
    root = (base_url or "").strip().rstrip("/")
    if prov == "deepseek":
        while root.endswith("/v1"):
            root = root[: -len("/v1")].rstrip("/")
        return f"{root}/chat/completions"
    # Qwen / Kimi / OpenAI / Ollama: base already ends with /v1
    if root.endswith("/v1"):
        return f"{root}/chat/completions"
    return f"{root}/v1/chat/completions"


class LLMClient:
    """
    Multi-vendor Chat Completions (official OpenAI-compatible):

    - DeepSeek: Bearer key, base https://api.deepseek.com, JSON Output guide
    - Qwen/DashScope: Bearer DASHSCOPE_API_KEY, .../compatible-mode/v1
    - Kimi/Moonshot: Bearer MOONSHOT_API_KEY, https://api.moonshot.cn/v1
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_sec: float = 180.0,
        temperature: float | None = 0.2,
        *,
        provider: str | None = None,
        max_tokens: int = 4096,
        use_sdk: bool = True,
        extra_body: dict[str, Any] | None = None,
        send_temperature: bool = True,
    ) -> None:
        self.provider = detect_provider(base_url, provider)
        self.base_url = normalize_openai_base_url(base_url, provider=self.provider)
        self.api_key = (api_key or "").strip()
        self.model = (model or "").strip()
        self.timeout_sec = float(timeout_sec)
        self.temperature = temperature
        self.max_tokens = int(max_tokens)
        self.use_sdk = bool(use_sdk)
        self.extra_body = dict(extra_body or {})
        # Kimi 部分模型 temperature 固定，乱传会 400
        self.send_temperature = bool(send_temperature) and self.provider != "kimi"

    @property
    def configured(self) -> bool:
        if not (self.base_url and self.model):
            return False
        if self.provider == "ollama":
            return True
        key = self.api_key.lower()
        return bool(self.api_key) and key not in {"", "none", "null", "sk-在此填写你的密钥", "sk-你的密钥"}

    def chat(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = False,
        role: str | None = None,
        symbol: str | None = None,
        call_site: str | None = None,
        cache_hit: bool = False,
        cycle_id: str | None = None,
        research_session_id: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        if not self.configured:
            raise RuntimeError(
                f"LLM[{self.provider}] not configured: set the vendor API key "
                f"(DASHSCOPE_API_KEY / DEEPSEEK_API_KEY / MOONSHOT_API_KEY) in .env"
            )
        system_msg = system
        user_msg = user
        if json_mode:
            blob = f"{system_msg}\n{user_msg}".lower()
            if "json" not in blob:
                system_msg = system_msg + _JSON_HINT

        messages = [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ]
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "max_tokens": int(max_tokens if max_tokens is not None else self.max_tokens),
        }
        if self.send_temperature and self.temperature is not None:
            kwargs["temperature"] = float(self.temperature)
        # Ollama JSON mode (response_format=json_object) often hangs until HTTP
        # timeout, then we retry without it — doubling wait. Prompt already
        # requires JSON; parse_json_object() extracts it from the reply.
        use_response_format = json_mode and self.provider != "ollama"
        if use_response_format:
            kwargs["response_format"] = {"type": "json_object"}
        if self.extra_body:
            kwargs["extra_body"] = dict(self.extra_body)

        meta = {
            "role": role,
            "symbol": symbol,
            "call_site": call_site,
            "cache_hit": cache_hit,
            "cycle_id": cycle_id,
            "research_session_id": research_session_id,
            "prompt_text": f"{system_msg}\n{user_msg}",
        }
        t0 = time.perf_counter()
        try:
            if self.use_sdk:
                content, usage = self._chat_via_openai_sdk(kwargs)
            else:
                content, usage = self._chat_via_http(kwargs)
        except Exception as first_exc:
            if not use_response_format:
                self._record_failed_usage(meta, first_exc, t0)
                raise
            msg = str(first_exc)
            if "not_found" in msg.lower() or "not found" in msg.lower():
                logger.warning(
                    "LLM model missing provider=%s model=%s — check Ollama `api/tags` / NEWS_AI_MODEL. (%s)",
                    self.provider,
                    self.model,
                    first_exc,
                )
            else:
                logger.warning(
                    "JSON mode failed provider=%s model=%s (%s); retry without response_format",
                    self.provider,
                    self.model,
                    first_exc,
                )
            kwargs.pop("response_format", None)
            try:
                if self.use_sdk:
                    content, usage = self._chat_via_openai_sdk(kwargs)
                else:
                    content, usage = self._chat_via_http(kwargs)
            except Exception as second_exc:
                self._record_failed_usage(meta, second_exc, t0)
                raise
        latency_ms = (time.perf_counter() - t0) * 1000.0
        self._record_usage(content, usage, latency_ms, meta)
        return content

    def _record_failed_usage(self, meta: dict[str, Any], exc: Exception, t0: float) -> None:
        """Count failed local/cloud attempts so Token dashboard is not silently zero."""
        try:
            from ashare.ai.cost_tracker import estimate_tokens, get_cost_tracker

            prompt = str(meta.get("prompt_text") or "")
            inp = estimate_tokens(prompt) if prompt else 0
            get_cost_tracker().record(
                model=self.model,
                provider=self.provider,
                input_tokens=inp,
                output_tokens=0,
                latency_ms=(time.perf_counter() - t0) * 1000.0,
                usage_source=f"error:{type(exc).__name__}",
                symbol=meta.get("symbol"),
                role=meta.get("role"),
                call_site=meta.get("call_site"),
                cache_hit=False,
                cycle_id=meta.get("cycle_id"),
                research_session_id=meta.get("research_session_id"),
            )
        except Exception as rec_exc:  # noqa: BLE001
            logger.debug("failed-usage record skipped: %s", rec_exc)

    @staticmethod
    def _normalize_usage(raw: dict[str, Any] | None, prompt_text: str, output_text: str) -> tuple[int, int, str]:
        if raw:
            inp = int(raw.get("input_tokens") or raw.get("prompt_tokens") or 0)
            out = int(raw.get("output_tokens") or raw.get("completion_tokens") or 0)
            if inp or out:
                return inp, out, "actual"
        from ashare.ai.cost_tracker import estimate_tokens

        return estimate_tokens(prompt_text), estimate_tokens(output_text), "estimated"

    def _record_usage(
        self,
        content: str,
        usage: dict[str, Any] | None,
        latency_ms: float,
        meta: dict[str, Any],
    ) -> None:
        try:
            from ashare.ai.cost_tracker import get_cost_tracker

            inp, out, source = self._normalize_usage(usage, meta["prompt_text"], content)
            get_cost_tracker().record(
                model=self.model,
                provider=self.provider,
                input_tokens=inp,
                output_tokens=out,
                latency_ms=latency_ms,
                usage_source=source,
                symbol=meta.get("symbol"),
                role=meta.get("role"),
                call_site=meta.get("call_site"),
                cache_hit=bool(meta.get("cache_hit")),
                cycle_id=meta.get("cycle_id"),
                research_session_id=meta.get("research_session_id"),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("usage record skipped: %s", exc)

    def _chat_via_openai_sdk(self, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
        try:
            from openai import OpenAI
        except ImportError:
            logger.info("openai package missing, HTTP fallback")
            return self._chat_via_http(kwargs)

        client = OpenAI(
            api_key=self.api_key or "ollama",
            base_url=self.base_url,
            timeout=self.timeout_sec,
        )
        resp = client.chat.completions.create(**kwargs)
        content = extract_chat_content(resp.choices[0].message)
        if not content:
            raise RuntimeError(f"{self.provider} empty content (model={self.model})")
        usage = None
        u = getattr(resp, "usage", None)
        if u is not None:
            usage = {
                "input_tokens": getattr(u, "prompt_tokens", None),
                "output_tokens": getattr(u, "completion_tokens", None),
                "total_tokens": getattr(u, "total_tokens", None),
            }
        return str(content), usage

    def _chat_via_http(self, kwargs: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
        url = chat_completions_url(self.base_url, provider=self.provider)
        headers = {
            "Authorization": f"Bearer {self.api_key or 'ollama'}",
            "Content-Type": "application/json",
        }
        body = dict(kwargs)
        extra = body.pop("extra_body", None) or {}
        body.update(extra)
        with httpx.Client(timeout=self.timeout_sec) as client:
            resp = client.post(url, headers=headers, json=body)
            if resp.status_code >= 400:
                raise RuntimeError(f"{self.provider} HTTP {resp.status_code} @ {url}: {resp.text[:800]}")
            data = resp.json()
        try:
            content = extract_chat_content(data["choices"][0]["message"])
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected response: {json.dumps(data, ensure_ascii=False)[:500]}") from exc
        if not content:
            raise RuntimeError(f"{self.provider} empty content")
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else None
        return str(content), usage


def _resolve_api_key(cfg: dict[str, Any], prof: dict[str, Any], ai: dict[str, Any]) -> str:
    """Aggregator-first: one AI_API_KEY shared by all roles unless role overrides."""
    env = cfg.get("_env", {}) or {}
    placeholders = {"", "sk-在此填写你的密钥", "sk-你的密钥", "none", "null"}
    if prof.get("api_key"):
        v = str(prof["api_key"]).strip()
        if v.lower() not in placeholders:
            return v
    key_env = str(prof.get("api_key_env") or ai.get("api_key_env") or "AI_API_KEY")
    for name in (
        key_env,
        "AI_API_KEY",
        "SILICONFLOW_API_KEY",
        "DASHSCOPE_API_KEY",
        "DEEPSEEK_API_KEY",
        "MOONSHOT_API_KEY",
        "OPENAI_API_KEY",
    ):
        val = str(env.get(name) or "").strip()
        if val and val.lower() not in placeholders:
            return val
    return ""


def client_from_cfg(cfg: dict[str, Any], profile: dict[str, Any] | None = None) -> LLMClient:
    """Roles inherit global base_url/api_key; only model (and optional overrides) differ."""
    ai = cfg.get("ai", {}) or {}
    prof = dict(profile or {})
    # Inherit gateway from global unless role explicitly sets base_url/provider
    provider_hint = str(prof.get("provider") or ai.get("provider") or "")
    base_url = str(prof.get("base_url") or ai.get("base_url") or "https://api.siliconflow.cn/v1")
    provider = detect_provider(base_url, provider_hint or None)

    # Role without api_key_env → use global api_key_env (single-key mode)
    if "api_key_env" not in prof and "api_key" not in prof:
        prof = {**prof, "api_key_env": ai.get("api_key_env") or "AI_API_KEY"}

    temp: float | None
    if "temperature" in prof:
        temp = None if prof.get("temperature") is None else float(prof["temperature"])
    else:
        temp = float(ai.get("temperature", 0.2))

    extra_body = dict(ai.get("extra_body") or {})
    extra_body.update(dict(prof.get("extra_body") or {}))
    # Only inject Kimi thinking flag when talking to Moonshot native endpoint
    if provider == "kimi" and "thinking" not in extra_body:
        extra_body["thinking"] = {"type": "disabled"}
    # /v1 ignores think=false; reasoning_effort=none is what actually turns thinking off.
    if provider == "ollama":
        extra_body.setdefault("think", False)
        extra_body.setdefault("reasoning_effort", "none")

    return LLMClient(
        base_url=base_url,
        api_key=_resolve_api_key(cfg, prof, ai),
        model=str(prof.get("model") or ai.get("model") or "deepseek-ai/DeepSeek-V4-Flash"),
        timeout_sec=float(prof.get("timeout_sec") or ai.get("timeout_sec") or 180),
        temperature=temp,
        provider=provider,
        max_tokens=int(prof.get("max_tokens") or ai.get("max_tokens") or 4096),
        use_sdk=bool(ai.get("use_openai_sdk", True)),
        extra_body=extra_body or None,
        send_temperature=provider != "kimi",
    )


def client_for_role(cfg: dict[str, Any], role_id: str) -> LLMClient:
    committee = (cfg.get("ai") or {}).get("committee") or {}
    roles = list(committee.get("roles") or [])
    match = next((r for r in roles if str(r.get("id")) == str(role_id)), None)
    return client_from_cfg(cfg, match)


def client_for_news(cfg: dict[str, Any]) -> LLMClient | None:
    """News Intelligence Engine — separate gateway from Council (NEWS_AI_* in .env)."""
    from ashare.config_loaders import load_yaml_config

    news_cfg = load_yaml_config(cfg, "news")
    prof = dict(news_cfg.get("llm") or {})
    if not prof.get("base_url") or not prof.get("model"):
        return None
    prof.setdefault("api_key_env", "NEWS_AI_API_KEY")
    prof.setdefault("temperature", 0.1)
    prof.setdefault("timeout_sec", 120)
    # Do not inherit Council max_tokens=4096 — local mapping/intel needs short JSON.
    prof.setdefault("max_tokens", 768)
    return client_from_cfg(cfg, prof)


def parse_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("empty LLM content")
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1)
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("LLM JSON is not an object")
    return data

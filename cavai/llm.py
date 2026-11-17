"""Actual OpenAI-compatible /chat/completions HTTP client with Tool Calling."""
from __future__ import annotations
import ipaddress
import os
import time
from typing import Any
from urllib.parse import urlsplit
import httpx
from pydantic import BaseModel, Field, ConfigDict, SecretStr, model_validator

DEFAULT_URLS = {
    "DeepSeek": "https://api.deepseek.com",
    "OpenAI": "https://api.openai.com/v1",
    "Compatible": "",
}

class LLMError(RuntimeError):
    pass

class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = "DeepSeek"
    base_url: str = "https://api.deepseek.com"
    api_key: SecretStr = Field(min_length=1)
    model: str = Field(min_length=1, max_length=128, default="deepseek-chat")
    timeout_sec: float = Field(ge=5, le=180, default=45)
    max_rounds: int = Field(ge=2, le=12, default=5)
    max_tools: int = Field(ge=1, le=30, default=12)
    max_completion_tokens: int = Field(ge=100, le=8192, default=1200)
    max_total_tokens: int = Field(ge=200, le=250000, default=16000)
    retries: int = Field(ge=0, le=3, default=2)
    temperature: float | None = Field(default=None,ge=0,le=2)
    token_param: str = Field(default="max_tokens",pattern=r"^(max_tokens|max_completion_tokens)$")

    @model_validator(mode="after")
    def secure_url(self):
        url = urlsplit(self.base_url)
        if url.scheme not in {"http","https"} or not url.hostname or url.username or url.password:
            raise ValueError("Base URL must be a valid HTTPS endpoint without credentials")
        if url.query or url.fragment:
            raise ValueError("Base URL must have no query/fragment")
        hostname = url.hostname.lower()
        local = hostname == "localhost" or hostname.endswith(".localhost")
        try:
            addr = ipaddress.ip_address(hostname)
            local = local or not addr.is_global
        except ValueError:
            pass
        if local and os.getenv("CAVAI_ALLOW_LOCAL_API") != "1":
            raise ValueError("Local/private API endpoints are disabled. Explicitly set CAVAI_ALLOW_LOCAL_API=1 for trusted local use.")
        if url.scheme != "https" and not (local and os.getenv("CAVAI_ALLOW_LOCAL_API") == "1"):
            raise ValueError("HTTPS is required for external model endpoints")
        return self

class LLMClient:
    def __init__(self, cfg: LLMConfig, transport: httpx.BaseTransport | None = None):
        self.cfg = cfg
        self.transport = transport
        self.usage = {"prompt_tokens":0,"completion_tokens":0,"total_tokens":0,
                      "requests":0,"missing_usage_responses":0}

    def chat(self, messages: list, tools: list | None = None, tool_choice: str = "auto") -> dict[str,Any]:
        if self.usage["total_tokens"] >= self.cfg.max_total_tokens:
            raise LLMError("Reported token budget exhausted")
        url = self.cfg.base_url.rstrip("/") + "/chat/completions"
        request: dict[str,Any] = {
            "model":self.cfg.model, "messages":messages,
            self.cfg.token_param:self.cfg.max_completion_tokens,
            "stream":False,
        }
        if self.cfg.temperature is not None:
            request["temperature"] = self.cfg.temperature
        if tools:
            request["tools"] = tools
            request["tool_choice"] = tool_choice
        headers = {"Authorization":f"Bearer {self.cfg.api_key.get_secret_value()}",
                   "Content-Type":"application/json"}
        last_error = ""
        for attempt in range(self.cfg.retries + 1):
            try:
                with httpx.Client(timeout=self.cfg.timeout_sec, transport=self.transport,
                                  follow_redirects=False, trust_env=False) as client:
                    response = client.post(url, json=request, headers=headers)
                if response.status_code in (429,500,502,503,504) and attempt < self.cfg.retries:
                    time.sleep(min(1.5,0.3*(2**attempt)))
                    continue
                if response.status_code >= 400:
                    # Never relay provider response body: it may echo sensitive context.
                    raise LLMError(f"Provider returned HTTP {response.status_code}; check key, model and parameter compatibility")
                if len(response.content) > 3_000_000:
                    raise LLMError("Provider response is too large")
                answer = response.json()
                if not isinstance(answer,dict) or not answer.get("choices"):
                    raise LLMError("Provider response lacks Chat Completions choices")
                usage = answer.get("usage") or {}
                for name in ("prompt_tokens","completion_tokens","total_tokens"):
                    self.usage[name] += int(usage.get(name) or 0)
                self.usage["requests"] += 1
                if not usage or usage.get("total_tokens") is None:
                    self.usage["missing_usage_responses"] += 1
                return answer
            except (httpx.TimeoutException,httpx.TransportError) as exc:
                last_error = type(exc).__name__
                if attempt < self.cfg.retries:
                    time.sleep(min(1.5,0.3*(2**attempt)))
                else:
                    raise LLMError(f"API connection failed ({last_error}); verify endpoint/network") from exc
            except ValueError as exc:
                raise LLMError("Provider returned invalid JSON") from exc
        raise LLMError(f"API request failed: {last_error}")

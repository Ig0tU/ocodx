"""
OpenAI-compatible agent — covers every provider that speaks the
/v1/chat/completions protocol:

  openai       → https://api.openai.com/v1
  anthropic    → https://api.anthropic.com/v1  (via compat endpoint)
  deepseek     → https://api.deepseek.com/v1
  groq         → https://api.groq.com/openai/v1
  openrouter   → https://openrouter.ai/api/v1
  together     → https://api.together.xyz/v1
  mistral      → https://api.mistral.ai/v1
  xai          → https://api.x.ai/v1
  huggingface  → https://api-inference.huggingface.co/v1

Uses only stdlib (urllib) — no extra dependencies needed.
Supports streaming with <think>…</think> passthrough for reasoning models.
"""

import json
import logging
import urllib.request
import urllib.error
from typing import List, Dict, Optional, Generator

from open_codex.interfaces.llm_agent import LLMAgent

logger = logging.getLogger(__name__)


# ── Provider registry ─────────────────────────────────────────────────────────

PROVIDER_CONFIGS: dict[str, dict] = {
    "openai": {
        "base_url":      "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "name":          "OpenAI",
        "auth_header":   "Authorization",
        "auth_prefix":   "Bearer ",
    },
    "deepseek": {
        "base_url":      "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "name":          "DeepSeek",
        "auth_header":   "Authorization",
        "auth_prefix":   "Bearer ",
    },
    "groq": {
        "base_url":      "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "name":          "Groq",
        "auth_header":   "Authorization",
        "auth_prefix":   "Bearer ",
    },
    "openrouter": {
        "base_url":      "https://openrouter.ai/api/v1",
        "default_model": "anthropic/claude-3.5-sonnet",
        "name":          "OpenRouter",
        "auth_header":   "Authorization",
        "auth_prefix":   "Bearer ",
    },
    "together": {
        "base_url":      "https://api.together.xyz/v1",
        "default_model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "name":          "Together AI",
        "auth_header":   "Authorization",
        "auth_prefix":   "Bearer ",
    },
    "mistral": {
        "base_url":      "https://api.mistral.ai/v1",
        "default_model": "mistral-large-latest",
        "name":          "Mistral AI",
        "auth_header":   "Authorization",
        "auth_prefix":   "Bearer ",
    },
    "xai": {
        "base_url":      "https://api.x.ai/v1",
        "default_model": "grok-3",
        "name":          "xAI (Grok)",
        "auth_header":   "Authorization",
        "auth_prefix":   "Bearer ",
    },
    "huggingface": {
        "base_url":      "https://api-inference.huggingface.co/v1",
        "default_model": "meta-llama/Llama-3.1-8B-Instruct",
        "name":          "HuggingFace",
        "auth_header":   "Authorization",
        "auth_prefix":   "Bearer ",
    },
}


def _user_error(provider_name: str, api_key: str, raw: Exception) -> str:
    msg = str(raw).lower()
    if not api_key:
        return f"{provider_name} API key not set. Add it in Settings (⚙)."
    if "401" in msg or "unauthorized" in msg or "invalid" in msg and "key" in msg:
        return f"Invalid {provider_name} API key. Check your key and try again."
    if "402" in msg or "insufficient" in msg or "billing" in msg:
        return f"{provider_name} billing issue — check your account balance."
    if "429" in msg or "rate" in msg:
        return f"{provider_name} rate limit hit. Wait a moment and retry."
    if "quota" in msg or "exhausted" in msg:
        return f"{provider_name} quota exceeded. Check your usage limits."
    if "model" in msg and ("not found" in msg or "does not exist" in msg):
        return f"{provider_name}: model not found. Check the model name."
    if "connection" in msg or "refused" in msg or "timeout" in msg:
        return f"Cannot reach {provider_name} API. Check your internet connection."
    return f"{provider_name} error: {raw}"


# ── Agent ─────────────────────────────────────────────────────────────────────

class OpenAICompatAgent(LLMAgent):
    """
    Chat-completion agent for any OpenAI-compatible API endpoint.
    Streaming is used internally; callers get the full accumulated string.
    """

    def __init__(
        self,
        system_prompt: str,
        provider: str,                    # key in PROVIDER_CONFIGS
        model_name: Optional[str] = None,
        api_key: str = "",
        base_url: Optional[str] = None,   # override for custom endpoints
        temperature: float = 0.2,
        max_tokens: int = 4096,
        timeout: int = 300,
    ):
        cfg = PROVIDER_CONFIGS.get(provider, {})
        self.system_prompt = system_prompt
        self.provider      = provider
        self.provider_name = cfg.get("name", provider)
        self.model_name    = model_name or cfg.get("default_model", "gpt-4o-mini")
        self.api_key       = api_key
        self.base_url      = (base_url or cfg.get("base_url", "")).rstrip("/")
        self.auth_header   = cfg.get("auth_header", "Authorization")
        self.auth_prefix   = cfg.get("auth_prefix", "Bearer ")
        self.temperature   = temperature
        self.max_tokens    = max_tokens
        self.timeout       = timeout

    # ── Health ────────────────────────────────────────────────────────────────

    def health(self) -> dict:
        if not self.api_key:
            return {
                "ok":   False,
                "hint": f"{self.provider_name} API key not set. Add it in Settings (⚙).",
            }
        try:
            url = f"{self.base_url}/models"
            req = urllib.request.Request(url)
            req.add_header(self.auth_header, f"{self.auth_prefix}{self.api_key}")
            req.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                models = [m.get("id", "") for m in data.get("data", [])]
                return {"ok": True, "models": models[:15], "hint": None}
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                return {"ok": False, "hint": f"Invalid {self.provider_name} API key."}
            return {"ok": False, "hint": f"{self.provider_name} HTTP {e.code}: {e.reason}"}
        except Exception as e:
            # Some providers don't expose /models — treat as healthy if we have key
            if self.api_key:
                return {"ok": True, "models": [self.model_name], "hint": None}
            return {"ok": False, "hint": str(e)}

    # ── Streaming ─────────────────────────────────────────────────────────────

    def _stream_tokens(self, messages: List[Dict[str, str]]) -> Generator[str, None, None]:
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model":       self.model_name,
            "messages":    messages,
            "temperature": self.temperature,
            "max_tokens":  self.max_tokens,
            "stream":      True,
        }
        data = json.dumps(payload).encode("utf-8")
        req  = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header(self.auth_header, f"{self.auth_prefix}{self.api_key}")

        # OpenRouter requires these extra headers
        if self.provider == "openrouter":
            req.add_header("HTTP-Referer", "https://github.com/Ig0tU/ocodx")
            req.add_header("X-Title", "Open Codex SLM")

        try:
            in_think = False
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or line == "data: [DONE]":
                        continue
                    if not line.startswith("data: "):
                        continue
                    try:
                        chunk = json.loads(line[6:])
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        reasoning = delta.get("reasoning_content") or ""
                        content   = delta.get("content") or ""

                        if reasoning:
                            if not in_think:
                                in_think = True
                                yield "<think>"
                            yield reasoning

                        if content:
                            if in_think:
                                in_think = False
                                yield "</think>"
                            yield content

                    except (json.JSONDecodeError, IndexError, KeyError):
                        continue

            if in_think:
                yield "</think>"

        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode()
            except Exception:
                pass
            raise ConnectionError(
                _user_error(self.provider_name, self.api_key, Exception(f"HTTP {e.code} {body[:200]}"))
            )
        except ConnectionError:
            raise
        except Exception as e:
            raise ConnectionError(_user_error(self.provider_name, self.api_key, e))

    # ── Blocking completion ───────────────────────────────────────────────────

    def _generate_completion(self, messages: List[Dict[str, str]]) -> str:
        if not self.api_key:
            raise ConnectionError(
                f"{self.provider_name} API key not configured. Add it in Settings (⚙)."
            )
        return "".join(self._stream_tokens(messages))

    # ── One-shot ──────────────────────────────────────────────────────────────

    def one_shot_mode(self, user_input: str) -> str:
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user",   "content": user_input},
        ]
        return self._generate_completion(messages)

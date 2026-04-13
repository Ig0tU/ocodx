import json
import logging
import urllib.request
import urllib.error
from typing import List, Dict, Optional, Generator

from open_codex.interfaces.llm_agent import LLMAgent

logger = logging.getLogger(__name__)


# ── Human-readable error translation ─────────────────────────────────────────

def _lmstudio_user_error(host: str, raw: Exception) -> str:
    msg = str(raw).lower()
    if any(k in msg for k in ("connection refused", "failed to connect",
                               "connection error", "errno 61",
                               "nodename nor servname")):
        return (
            "LM Studio is not running or its local server is off.\n"
            "Fix:\n"
            "  1. Open LM Studio\n"
            "  2. Go to the 'Local Server' tab (left sidebar)\n"
            "  3. Click 'Start Server'\n"
            f"  4. Make sure the host here is set to: {host}"
        )
    if "401" in msg or "unauthorized" in msg:
        return "LM Studio server returned 401 Unauthorized — check your server config."
    if "no models" in msg or "no model" in msg:
        return (
            "LM Studio has no model loaded.\n"
            "Fix: open LM Studio → load a model → then start the server."
        )
    return f"LM Studio error: {raw}"


class LMStudioAgent(LLMAgent):
    """
    Agent that connects to LM Studio's OpenAI-compatible local server.
    Uses SSE streaming so the frontend receives token-by-token output.
    """

    def __init__(self,
                 system_prompt: str,
                 model_name: Optional[str] = None,
                 host: str = "http://localhost:1234",
                 temperature: float = 0.2,
                 max_tokens: int = 2048,
                 timeout: int = 300):
        self.system_prompt = system_prompt
        self.host          = host.rstrip("/")
        self.temperature   = temperature
        self.max_tokens    = max_tokens
        self.timeout       = timeout
        self.model_name    = model_name

    # ── Model discovery ───────────────────────────────────────────────────────

    def _get_available_models(self) -> List[str]:
        """Fetch loaded models from LM Studio (/v1/models)."""
        try:
            url = f"{self.host}/v1/models"
            with urllib.request.urlopen(url, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                return [m["id"] for m in data.get("data", [])]
        except urllib.error.URLError as e:
            logger.error("LM Studio models fetch failed: %s", e)
            return []
        except Exception as e:
            logger.error("Unexpected error fetching LM Studio models: %s", e)
            return []

    def _select_best_model(self, models: List[str]) -> str:
        for keyword in ("coder", "instruct", "qwen"):
            matches = [m for m in models if keyword in m.lower()]
            if matches:
                return matches[0]
        return models[0]

    def _resolve_model(self) -> None:
        """Ensure self.model_name is set to a loaded model."""
        models = self._get_available_models()
        if not models:
            raise ConnectionError(
                _lmstudio_user_error(self.host, Exception("connection refused"))
            )
        if not self.model_name:
            self.model_name = self._select_best_model(models)
            logger.info("Auto-selected model: %s", self.model_name)
        elif self.model_name not in models:
            partial = [m for m in models if self.model_name.lower() in m.lower()]
            if partial:
                self.model_name = partial[0]
            elif len(models) == 1:
                self.model_name = models[0]

    # ── Health check ──────────────────────────────────────────────────────────

    def health(self) -> dict:
        models = self._get_available_models()
        if not models:
            return {
                "ok":   False,
                "hint": _lmstudio_user_error(self.host, Exception("connection refused")),
            }
        return {"ok": True, "models": models, "hint": None}

    # ── Streaming completion ──────────────────────────────────────────────────

    def _stream_tokens(self, messages: List[Dict[str, str]]) -> Generator[str, None, None]:
        """
        Call /v1/chat/completions with stream=true and yield each text token.
        Raises ConnectionError with a user-friendly message on failure.
        """
        self._resolve_model()

        url     = f"{self.host}/v1/chat/completions"
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

        try:
            in_think = False
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8").strip()
                    if not line or line == "data: [DONE]":
                        continue
                    if line.startswith("data: "):
                        try:
                            chunk = json.loads(line[6:])
                            delta = chunk.get("choices", [{}])[0].get("delta", {})
                            reasoning = delta.get("reasoning_content") or ""
                            content   = delta.get("content") or ""

                            # Thinking models (e.g. Qwen3.5, DeepSeek-R1) emit
                            # reasoning_content during chain-of-thought, then
                            # switch to content for the actual response.
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

        except ConnectionError:
            raise
        except urllib.error.URLError as e:
            raise ConnectionError(_lmstudio_user_error(self.host, e))
        except Exception as e:
            raise ConnectionError(f"LM Studio streaming error: {e}")

    # ── Non-streaming fallback (used by CodingAgent tool loop) ───────────────

    def _generate_completion(self, messages: List[Dict[str, str]]) -> str:
        """
        Accumulate all streaming tokens into a single string.
        This is what CodingAgent calls for its ACTION/DONE loop.
        """
        parts: List[str] = []
        for token in self._stream_tokens(messages):
            parts.append(token)
        return "".join(parts)

    # ── One-shot (CLI / TUI) ──────────────────────────────────────────────────

    def one_shot_mode(self, user_input: str) -> str:
        # Resolve model before calling _generate_completion so tests that
        # mock _generate_completion still see the correct self.model_name.
        models = self._get_available_models()
        if not models:
            raise ConnectionError(
                _lmstudio_user_error(self.host, Exception("connection refused"))
            )
        if not self.model_name:
            self.model_name = self._select_best_model(models)
        elif self.model_name not in models:
            partial = [m for m in models if self.model_name.lower() in m.lower()]
            if partial:
                self.model_name = partial[0]
            elif len(models) == 1:
                self.model_name = models[0]

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user",   "content": user_input},
        ]
        return self._generate_completion(messages)

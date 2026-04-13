from typing import List, Dict, Optional
import logging
import ollama

from open_codex.interfaces.llm_agent import LLMAgent

logger = logging.getLogger(__name__)


# ── Human-readable error translation ─────────────────────────────────────────

def _ollama_user_error(host: str, model: str, raw: Exception) -> str:
    """
    Convert a raw Ollama SDK exception into a clear, actionable message
    that the UI can display directly to the user.
    """
    msg = str(raw).lower()
    is_cloud = "ollama.com" in host

    # Connection refused / server not running
    if any(k in msg for k in ("connection refused", "failed to connect",
                               "connection error", "nodename nor servname")):
        if is_cloud:
            return (
                "Cannot reach Ollama Cloud. Check your internet connection "
                "and that your API key is correct."
            )
        return (
            "Ollama is not running locally.\n"
            "Fix: open a terminal and run →  ollama serve\n"
            f"Then make sure host is set to:  {host}"
        )

    # Path not found (double-/api regression, wrong URL)
    if "not found" in msg and ("path" in msg or "404" in msg):
        return (
            f"Bad Ollama endpoint — the URL '{host}' produced a 404.\n"
            "Fix: set host to 'http://localhost:11434' (local) "
            "or 'https://ollama.com' (cloud). Do NOT add /api."
        )

    # Model not pulled
    if "model" in msg and ("not found" in msg or "doesn't exist" in msg
                            or "pull" in msg):
        return (
            f"Model '{model}' is not pulled yet.\n"
            f"Fix: run →  ollama pull {model}"
        )

    # Auth / API key
    if any(k in msg for k in ("unauthorized", "401", "403", "forbidden",
                               "invalid api key")):
        return (
            "Ollama Cloud authentication failed.\n"
            "Fix: paste a valid API key in the API Key field."
        )

    return f"Ollama error: {raw}"


class OllamaAgent(LLMAgent):
    """
    Agent that connects to Ollama (local or cloud) using the official
    Python client.  Errors surface as clear, actionable messages.
    """

    def __init__(self,
                 system_prompt: str,
                 model_name: str,
                 host: str,
                 api_key: Optional[str] = None,
                 temperature: float = 0.2,
                 max_tokens: int = 500):
        self.system_prompt = system_prompt
        self.model_name    = model_name
        self.host          = host
        self.api_key       = api_key
        self.temperature   = temperature
        self.max_tokens    = max_tokens

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        self._ollama_client = ollama.Client(host=self.host, headers=headers)

    # ── Model auto-detect ─────────────────────────────────────────────────────

    def _resolve_model(self) -> None:
        """
        Auto-detect the best available model if none is specified or if the
        specified model is not found in the local list.  For cloud, we trust
        the caller-supplied model name as-is.
        """
        is_cloud = "ollama.com" in self.host
        if is_cloud:
            return  # Cloud model names are opaque; don't try to list them
        try:
            models_resp = self._ollama_client.list()
            available   = [m.model for m in models_resp.models if m.model]
        except Exception:
            return  # Non-fatal; proceed with whatever model_name is set

        if not available:
            return
        if not self.model_name or self.model_name not in available:
            self.model_name = available[0]
            logger.info("Auto-selected Ollama model: %s", self.model_name)

    # ── Health check ──────────────────────────────────────────────────────────

    def _check_ollama_available(self) -> None:
        """
        Verify the server is up and the requested model exists.
        Raises ConnectionError with a user-friendly message on failure.
        """
        is_cloud = "ollama.com" in self.host
        try:
            models_resp      = self._ollama_client.list()
            available_models = [
                m.model for m in models_resp.models if m.model is not None
            ]

            if not is_cloud and available_models and \
                    self.model_name not in available_models:
                logger.warning(
                    "Model '%s' not found locally. Available: %s. "
                    "Pull it with:  ollama pull %s",
                    self.model_name, ", ".join(available_models),
                    self.model_name,
                )

        except Exception as e:
            raise ConnectionError(
                _ollama_user_error(self.host, self.model_name, e)
            )

    def health(self) -> dict:
        """Return a health-check dict suitable for the /api/health endpoint."""
        is_cloud = "ollama.com" in self.host
        try:
            models_resp      = self._ollama_client.list()
            available_models = [
                m.model for m in models_resp.models if m.model is not None
            ]
            model_ok = is_cloud or (self.model_name in available_models)
            return {
                "ok":     model_ok,
                "models": available_models,
                "hint":   (
                    None if model_ok else
                    f"Model '{self.model_name}' not pulled. "
                    f"Run: ollama pull {self.model_name}"
                ),
            }
        except Exception as e:
            return {
                "ok":  False,
                "hint": _ollama_user_error(self.host, self.model_name, e),
            }

    # ── Completion ────────────────────────────────────────────────────────────

    def one_shot_mode(self, user_input: str) -> str:
        self._resolve_model()
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user",   "content": user_input},
        ]
        return self._generate_completion(messages).strip()

    def _generate_completion(self, messages: List[Dict[str, str]]) -> str:
        self._resolve_model()
        try:
            response = self._ollama_client.chat(
                model=self.model_name,
                messages=messages,
                options={
                    "temperature": self.temperature,
                    "num_predict": self.max_tokens,
                },
            )
            # Ollama SDK returns a ChatResponse object; use attribute access.
            return response.message.content

        except ConnectionError:
            raise
        except Exception as e:
            raise ConnectionError(
                _ollama_user_error(self.host, self.model_name, e)
            )
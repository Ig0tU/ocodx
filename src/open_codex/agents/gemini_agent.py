from typing import List, Dict

from open_codex.interfaces.llm_agent import LLMAgent


def _gemini_user_error(raw: Exception) -> str:
    msg = str(raw).lower()
    if "api_key_invalid" in msg or "invalid api key" in msg or "api key not valid" in msg:
        return "Invalid Gemini API key. Check your key at https://aistudio.google.com/apikey"
    if "quota" in msg or "resource_exhausted" in msg:
        return "Gemini API quota exceeded. Check your usage at https://aistudio.google.com"
    if "permission_denied" in msg or "403" in msg:
        return "Gemini API permission denied. Verify your API key has the right permissions."
    if "model" in msg and ("not found" in msg or "not supported" in msg):
        return "Gemini model not found. Try: gemini-1.5-flash or gemini-2.0-flash"
    return f"Gemini API error: {raw}"


def _to_genai_contents(messages: List[Dict[str, str]]) -> tuple[str, list]:
    """Split OpenAI-style messages into (system_instruction, genai contents list)."""
    from google.genai import types
    system = ""
    contents = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            system = content
        else:
            genai_role = "model" if role == "assistant" else "user"
            contents.append(
                types.Content(role=genai_role, parts=[types.Part.from_text(text=content)])
            )
    return system, contents


class GeminiAgent(LLMAgent):

    def __init__(self,
                 system_prompt: str,
                 model_name: str = "gemini-2.0-flash",
                 api_key: str = "",
                 temperature: float = 0.2,
                 max_tokens: int = 2048):
        self.system_prompt = system_prompt
        self.model_name    = model_name
        self.api_key       = api_key
        self.temperature   = temperature
        self.max_tokens    = max_tokens

    def _client(self):
        from google import genai
        return genai.Client(api_key=self.api_key)

    def _config(self, system: str = ""):
        from google.genai import types
        effective = system or self.system_prompt
        return types.GenerateContentConfig(
            system_instruction=effective if effective else None,
            temperature=self.temperature,
            max_output_tokens=self.max_tokens,
        )

    def health(self) -> dict:
        if not self.api_key:
            return {"ok": False, "hint": "GEMINI_API_KEY not set. Add it in Settings (⚙)."}
        try:
            client = self._client()

            # 1. Fetch all models available to this key
            all_models = list(client.models.list())

            text_models  = []   # support generateContent → active ping
            media_models = []   # Imagen/Veo/Lyria/embeddings → presence-check only

            for m in all_models:
                methods = getattr(m, "supported_generation_methods", None) or []
                name    = (m.name or "").replace("models/", "")
                if "generateContent" in methods:
                    text_models.append(name)
                else:
                    media_models.append(name)

            # 2. Active 1-token ping on the configured model (or best available)
            ping_target = self.model_name if self.model_name in text_models else (
                next((n for n in text_models if "gemini-2" in n or "gemini-3" in n), None)
                or (text_models[0] if text_models else None)
            )

            ping_ok    = False
            ping_hint  = None
            if ping_target:
                try:
                    from google.genai import types as _types
                    resp = client.models.generate_content(
                        model=ping_target,
                        contents="Ping. Reply with 'Pong'.",
                        config=_types.GenerateContentConfig(
                            max_output_tokens=5,
                            temperature=0.0,
                        ),
                    )
                    ping_ok   = bool(resp.text)
                    ping_hint = None
                except Exception as e:
                    ping_ok   = False
                    ping_hint = _gemini_user_error(e)
            else:
                ping_hint = "No generateContent model available on this key."

            # 3. Identify accessible media models (presence-check)
            _media_kw   = ("imagen", "veo", "lyria", "embedding")
            media_active = [
                m for m in media_models
                if any(kw in m.lower() for kw in _media_kw)
            ]

            # 4. Surface model lists
            modern_families = ("gemini-2", "gemini-3", "gemini-exp",
                               "gemini-2.5", "gemini-flash", "gemini-pro")
            modern_text = [
                n for n in text_models
                if any(f in n for f in modern_families)
            ]

            return {
                "ok":           ping_ok,
                "ping_model":   ping_target,
                "models":       modern_text[:15],
                "media_models": media_active,
                "hint":         ping_hint,
            }

        except Exception as e:
            return {"ok": False, "hint": _gemini_user_error(e)}


    def _generate_completion(self, messages: List[Dict[str, str]]) -> str:
        if not self.api_key:
            raise ConnectionError(
                "GEMINI_API_KEY not configured. Add it in Settings (⚙)."
            )
        try:
            system, contents = _to_genai_contents(messages)
            if not contents:
                return ""
            client = self._client()
            cfg = self._config(system)
            resp = client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=cfg,
            )
            return resp.text or ""
        except ConnectionError:
            raise
        except Exception as e:
            raise ConnectionError(_gemini_user_error(e))

    def one_shot_mode(self, user_input: str) -> str:
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user",   "content": user_input},
        ]
        return self._generate_completion(messages)

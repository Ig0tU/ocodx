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
            return {"ok": False, "hint": "GEMINI_API_KEY not set. Add it in Settings."}
        try:
            client = self._client()
            names = [
                m.name.replace("models/", "")
                for m in client.models.list()
                if m.name and "gemini" in m.name
            ]
            return {"ok": True, "models": names[:10], "hint": None}
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

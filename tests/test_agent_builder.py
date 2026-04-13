"""
Tests for AgentBuilder routing, host construction, and the
ollama_cloud double-/api/ endpoint regression.
"""
import pytest
from unittest.mock import patch, MagicMock
from open_codex.agent_builder import AgentBuilder, _phi_format

# Build Phi template tokens at runtime so they don't appear literally in source
PHI_SYS  = "<|system|>"
PHI_USER = "<|user|>"
PHI_ASST = "<|assistant|>"


# ── _phi_format ───────────────────────────────────────────────────────────────

class TestPhiFormat:
    def test_system_role_wrapped(self):
        result = _phi_format([{"role": "system", "content": "You are helpful"}])
        assert PHI_SYS in result
        assert "You are helpful" in result

    def test_user_role_wrapped(self):
        result = _phi_format([{"role": "user", "content": "Hello"}])
        assert PHI_USER in result
        assert "Hello" in result

    def test_assistant_role_wrapped(self):
        result = _phi_format([{"role": "assistant", "content": "Sure"}])
        assert PHI_ASST in result

    def test_ends_with_assistant_tag(self):
        result = _phi_format([{"role": "user", "content": "q"}])
        assert result.rstrip().endswith(PHI_ASST)

    def test_multiple_turns_ordered(self):
        messages = [
            {"role": "system",    "content": "sys"},
            {"role": "user",      "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user",      "content": "u2"},
        ]
        result = _phi_format(messages)
        assert result.index(PHI_SYS) < result.index(PHI_USER)


# ── get_ollama_agent ──────────────────────────────────────────────────────────

class TestGetOllamaAgent:
    def _build(self, model="llama3", host="http://localhost:11434", api_key=None):
        with patch("open_codex.agents.ollama_agent.ollama.Client"):
            return AgentBuilder.get_ollama_agent(model, host, api_key)

    def test_returns_ollama_agent(self):
        from open_codex.agents.ollama_agent import OllamaAgent
        agent = self._build()
        assert isinstance(agent, OllamaAgent)

    def test_model_name_forwarded(self):
        agent = self._build(model="codellama")
        assert agent.model_name == "codellama"

    def test_host_forwarded(self):
        agent = self._build(host="http://localhost:11434")
        assert agent.host == "http://localhost:11434"

    def test_api_key_forwarded(self):
        agent = self._build(api_key="secret")
        assert agent.api_key == "secret"


# ── get_lmstudio_agent ────────────────────────────────────────────────────────

class TestGetLMStudioAgent:
    def test_returns_lmstudio_agent(self):
        from open_codex.agents.lmstudio_agent import LMStudioAgent
        agent = AgentBuilder.get_lmstudio_agent("my-model", "http://localhost:1234")
        assert isinstance(agent, LMStudioAgent)

    def test_host_forwarded(self):
        agent = AgentBuilder.get_lmstudio_agent(None, "http://localhost:9999")
        assert "9999" in agent.host


# ── get_llm_caller ────────────────────────────────────────────────────────────

class TestGetLLMCaller:
    def test_lmstudio_caller_is_callable(self):
        caller = AgentBuilder.get_llm_caller("lmstudio", None, "http://localhost:1234")
        assert callable(caller)

    def test_ollama_caller_is_callable(self):
        with patch("open_codex.agents.ollama_agent.ollama.Client"):
            caller = AgentBuilder.get_llm_caller("ollama", "llama3", "http://localhost:11434")
        assert callable(caller)

    def test_unknown_agent_type_raises(self):
        with pytest.raises(ValueError, match="Unknown agent type"):
            AgentBuilder.get_llm_caller("unicorn", None, None)

    def test_ollama_cloud_default_host_has_no_api_suffix(self):
        """
        Regression: host was set to https://ollama.com/api which caused the
        ollama SDK to build https://ollama.com/api/api/chat (404).
        The correct default base is https://ollama.com.
        """
        captured = {}

        original_init = __import__(
            "open_codex.agents.ollama_agent", fromlist=["OllamaAgent"]
        ).OllamaAgent.__init__

        def spy_init(self, system_prompt, model_name, host, api_key=None, **kw):
            captured["host"] = host
            # Don't call original — we just want to capture args
            self.system_prompt = system_prompt
            self.model_name    = model_name
            self.host          = host
            self.api_key       = api_key
            self.temperature   = kw.get("temperature", 0.2)
            self.max_tokens    = kw.get("max_tokens", 500)
            self._ollama_client = MagicMock()

        with patch("open_codex.agents.ollama_agent.OllamaAgent.__init__", spy_init):
            AgentBuilder.get_llm_caller("ollama_cloud", None, None, "sk-test")

        host = captured.get("host", "")
        assert host, "host was not captured"
        assert not host.endswith("/api"), (
            f"Cloud host {host!r} ends with /api — the ollama SDK will build "
            "/api/api/chat producing a 404. Use 'https://ollama.com' as base."
        )
        assert "ollama.com" in host, f"Expected ollama.com in cloud host, got {host!r}"

    def test_ollama_local_default_host_uses_11434(self):
        captured = {}

        def spy_init(self, system_prompt, model_name, host, api_key=None, **kw):
            captured["host"] = host
            self.system_prompt = system_prompt
            self.model_name    = model_name
            self.host          = host
            self.api_key       = api_key
            self.temperature   = 0.2
            self.max_tokens    = 500
            self._ollama_client = MagicMock()

        with patch("open_codex.agents.ollama_agent.OllamaAgent.__init__", spy_init):
            AgentBuilder.get_llm_caller("ollama", None, None)

        assert "11434" in captured.get("host", "")


# ── _sanitize_ollama_host ─────────────────────────────────────────────────────

class TestSanitizeOllamaHost:
    def test_strips_trailing_api(self):
        from open_codex.agent_builder import _sanitize_ollama_host
        assert _sanitize_ollama_host("https://ollama.com/api") == "https://ollama.com"

    def test_strips_trailing_api_slash(self):
        from open_codex.agent_builder import _sanitize_ollama_host
        assert _sanitize_ollama_host("https://ollama.com/api/") == "https://ollama.com"

    def test_leaves_clean_host_unchanged(self):
        from open_codex.agent_builder import _sanitize_ollama_host
        assert _sanitize_ollama_host("http://localhost:11434") == "http://localhost:11434"

    def test_leaves_ollama_com_unchanged(self):
        from open_codex.agent_builder import _sanitize_ollama_host
        assert _sanitize_ollama_host("https://ollama.com") == "https://ollama.com"

    def test_does_not_strip_mid_path_api(self):
        from open_codex.agent_builder import _sanitize_ollama_host
        # /api is only stripped at the END — not in the middle
        result = _sanitize_ollama_host("https://proxy.example.com/api/ollama")
        assert "api/ollama" in result

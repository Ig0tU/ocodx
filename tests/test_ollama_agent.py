"""
Tests for OllamaAgent (open_codex/agents/ollama_agent.py)

All network calls are mocked — no real Ollama server required.
"""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from open_codex.agents.ollama_agent import OllamaAgent


def _make_agent(host="http://localhost:11434", model="llama3", api_key=None):
    return OllamaAgent(
        system_prompt="You are helpful.",
        model_name=model,
        host=host,
        api_key=api_key,
    )


# ── Construction & client init ─────────────────────────────────────────────────

class TestOllamaAgentInit:
    def test_local_host_stored(self):
        agent = _make_agent()
        assert agent.host == "http://localhost:11434"

    def test_model_name_stored(self):
        agent = _make_agent(model="mistral")
        assert agent.model_name == "mistral"

    def test_api_key_adds_authorization_header(self):
        with patch("open_codex.agents.ollama_agent.ollama.Client") as MockClient:
            agent = _make_agent(api_key="sk-test")
            MockClient.assert_called_once()
            _, kwargs = MockClient.call_args
            assert kwargs.get("headers", {}).get("Authorization") == "Bearer sk-test"

    def test_no_api_key_no_auth_header(self):
        with patch("open_codex.agents.ollama_agent.ollama.Client") as MockClient:
            _make_agent()
            _, kwargs = MockClient.call_args
            assert not kwargs.get("headers")


# ── one_shot_mode ─────────────────────────────────────────────────────────────

class TestOllamaOneShotMode:
    def _mock_chat_response(self, content="Hello!"):
        """Build a fake response that behaves like ollama's ChatResponse."""
        resp = MagicMock()
        resp.__getitem__ = MagicMock(side_effect=lambda k: (
            {"message": {"content": content},
             "done": True}[k]
        ))
        resp.__contains__ = MagicMock(side_effect=lambda k: k in ["message", "done"])
        # Also support attribute access (newer SDK style)
        resp.message.content = content
        return resp

    def test_returns_stripped_content(self):
        agent = _make_agent()
        fake_resp = self._mock_chat_response("  World  ")
        agent._ollama_client = MagicMock()
        agent._ollama_client.chat.return_value = fake_resp
        result = agent.one_shot_mode("Say hello")
        assert result == "World"

    def test_passes_system_and_user_messages(self):
        agent = _make_agent()
        fake_resp = self._mock_chat_response("ok")
        agent._ollama_client = MagicMock()
        agent._ollama_client.chat.return_value = fake_resp
        agent.one_shot_mode("My question")
        call_args = agent._ollama_client.chat.call_args
        messages = call_args[1].get("messages") or call_args[0][1]
        roles = [m["role"] for m in messages]
        assert "system" in roles
        assert "user" in roles

    def test_uses_correct_model(self):
        agent = _make_agent(model="codellama")
        fake_resp = self._mock_chat_response("done")
        agent._ollama_client = MagicMock()
        agent._ollama_client.chat.return_value = fake_resp
        agent.one_shot_mode("q")
        call_args = agent._ollama_client.chat.call_args
        model_used = call_args[1].get("model") or call_args[0][0]
        assert model_used == "codellama"


# ── _generate_completion ──────────────────────────────────────────────────────

class TestOllamaGenerateCompletion:
    def _agent_with_mock_client(self, response_content="Hello"):
        agent = _make_agent()
        resp = MagicMock()
        resp.__getitem__ = MagicMock(side_effect=lambda k: (
            {"message": {"content": response_content}}[k]
        ))
        resp.__contains__ = MagicMock(return_value=True)
        agent._ollama_client = MagicMock()
        agent._ollama_client.chat.return_value = resp
        return agent

    def test_returns_string(self):
        agent = self._agent_with_mock_client("answer")
        result = agent._generate_completion([{"role": "user", "content": "q"}])
        assert isinstance(result, str)

    def test_raises_connection_error_on_exception(self):
        agent = _make_agent()
        agent._ollama_client = MagicMock()
        agent._ollama_client.chat.side_effect = Exception("connection refused")
        # The new doctor-style message mentions 'ollama serve' or 'not running'
        with pytest.raises(ConnectionError):
            agent._generate_completion([{"role": "user", "content": "q"}])


# ── _check_ollama_available ───────────────────────────────────────────────────

class TestCheckOllamaAvailable:
    def test_raises_connection_error_when_server_down(self):
        agent = _make_agent()
        agent._ollama_client = MagicMock()
        agent._ollama_client.list.side_effect = Exception("connection refused")
        with pytest.raises(ConnectionError):
            agent._check_ollama_available()

    def test_logs_warning_when_model_missing(self, caplog):
        import logging
        agent = _make_agent(model="missing-model")
        mock_model = MagicMock()
        mock_model.model = "some-other-model"
        agent._ollama_client = MagicMock()
        agent._ollama_client.list.return_value = MagicMock(models=[mock_model])
        # Rewritten agent logs at WARNING (not ERROR) for missing model
        with caplog.at_level(logging.WARNING):
            agent._check_ollama_available()
        assert any("missing-model" in r.message for r in caplog.records)


# ── Cloud host URL correctness ─────────────────────────────────────────────────

class TestOllamaCloudHostURL:
    """
    Regression: agent_builder used to pass 'https://ollama.com/api' as host.
    The ollama SDK appends /api/chat internally, resulting in /api/api/chat (404).
    The host should be 'https://ollama.com' so SDK builds the correct URL.
    """
    def test_cloud_host_does_not_double_api(self):
        """Verify the SDK is called with a host that won't produce /api/api/..."""
        with patch("open_codex.agents.ollama_agent.ollama.Client") as MockClient:
            # This is the CORRECT host — no trailing /api
            agent = OllamaAgent(
                system_prompt="",
                model_name="qwen3-coder:480b-cloud",
                host="https://ollama.com",
                api_key="sk-cloud",
            )
            host_used = MockClient.call_args[1].get("host") or MockClient.call_args[0][0]
            assert not host_used.endswith("/api"), (
                f"Host '{host_used}' ends with /api which causes double-path 404. "
                "Use 'https://ollama.com' as the base."
            )

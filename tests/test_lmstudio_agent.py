"""
Tests for LMStudioAgent (open_codex/agents/lmstudio_agent.py)

All HTTP calls are mocked — no real LM Studio server required.
"""
import json
import pytest
from unittest.mock import patch, MagicMock
from io import BytesIO

from open_codex.agents.lmstudio_agent import LMStudioAgent


def _make_agent(host="http://localhost:1234", model=None):
    return LMStudioAgent(
        system_prompt="You are a coder.",
        model_name=model,
        host=host,
    )


def _mock_urlopen(response_body: dict):
    """Return a context-manager mock for urllib.request.urlopen."""
    raw = json.dumps(response_body).encode()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=MagicMock(read=MagicMock(return_value=raw)))
    cm.__exit__ = MagicMock(return_value=False)
    return cm


# ── Construction ───────────────────────────────────────────────────────────────

class TestLMStudioAgentInit:
    def test_host_strips_trailing_slash(self):
        agent = LMStudioAgent(system_prompt="", host="http://localhost:1234/")
        assert not agent.host.endswith("/")

    def test_model_name_stored(self):
        agent = _make_agent(model="my-model")
        assert agent.model_name == "my-model"

    def test_default_host(self):
        agent = LMStudioAgent(system_prompt="")
        assert agent.host == "http://localhost:1234"

    def test_timeout_default(self):
        agent = LMStudioAgent(system_prompt="")
        assert agent.timeout == 300  # bumped from 30s


# ── _get_available_models ─────────────────────────────────────────────────────

class TestGetAvailableModels:
    def test_returns_model_ids(self):
        agent = _make_agent()
        body = {"data": [{"id": "model-a"}, {"id": "model-b"}]}
        with patch("open_codex.agents.lmstudio_agent.urllib.request.urlopen",
                   return_value=_mock_urlopen(body)):
            models = agent._get_available_models()
        assert models == ["model-a", "model-b"]

    def test_returns_empty_list_on_error(self):
        agent = _make_agent()
        with patch("open_codex.agents.lmstudio_agent.urllib.request.urlopen",
                   side_effect=Exception("refused")):
            models = agent._get_available_models()
        assert models == []

    def test_calls_v1_models_endpoint(self):
        agent = _make_agent(host="http://localhost:1234")
        with patch("open_codex.agents.lmstudio_agent.urllib.request.urlopen") as mock_open:
            mock_open.return_value = _mock_urlopen({"data": []})
            agent._get_available_models()
            url_called = mock_open.call_args[0][0]
            assert url_called == "http://localhost:1234/v1/models"


# ── _select_best_model ─────────────────────────────────────────────────────────

class TestSelectBestModel:
    def test_prefers_coder(self):
        agent = _make_agent()
        result = agent._select_best_model(["qwen-coder", "llama-instruct"])
        assert result == "qwen-coder"

    def test_falls_back_to_instruct(self):
        agent = _make_agent()
        result = agent._select_best_model(["llama-instruct", "gpt-neo"])
        assert result == "llama-instruct"

    def test_falls_back_to_qwen(self):
        agent = _make_agent()
        result = agent._select_best_model(["qwen-7b", "random"])
        assert result == "qwen-7b"

    def test_falls_back_to_first(self):
        agent = _make_agent()
        result = agent._select_best_model(["random-model"])
        assert result == "random-model"


# ── _generate_completion (now delegates to _stream_tokens) ───────────────────

class TestLMStudioGenerateCompletion:
    def test_returns_correct_content(self):
        """_generate_completion accumulates tokens from _stream_tokens."""
        agent = _make_agent(model="test-model")
        with patch.object(agent, "_stream_tokens", return_value=iter(["result", " text"])):
            result = agent._generate_completion([{"role": "user", "content": "q"}])
        assert result == "result text"

    def test_calls_stream_tokens_with_messages(self):
        """_generate_completion passes messages straight through to _stream_tokens."""
        agent = _make_agent(model="m")
        messages = [{"role": "user", "content": "q"}]
        with patch.object(agent, "_stream_tokens", return_value=iter(["ok"])) as mock_st:
            agent._generate_completion(messages)
        mock_st.assert_called_once_with(messages)

    def test_raises_connection_error_on_failure(self):
        """ConnectionError from _stream_tokens bubbles up unchanged."""
        agent = _make_agent(model="m")
        with patch.object(agent, "_stream_tokens",
                          side_effect=ConnectionError("LM Studio not running")):
            with pytest.raises(ConnectionError, match="LM Studio"):
                agent._generate_completion([{"role": "user", "content": "q"}])

    def test_raises_on_stream_tokens_exception(self):
        """Generic exceptions from _stream_tokens also raise ConnectionError."""
        agent = _make_agent(model="m")
        with patch.object(agent, "_stream_tokens",
                          side_effect=ConnectionError("LM Studio error")):
            with pytest.raises(ConnectionError):
                agent._generate_completion([{"role": "user", "content": "q"}])


# ── _stream_tokens ────────────────────────────────────────────────────────────

class TestStreamTokens:
    def _sse_bytes(self, *tokens: str, done=True):
        """Build a fake SSE byte stream from a list of tokens."""
        lines = []
        for token in tokens:
            chunk = {"choices": [{"delta": {"content": token}}]}
            lines.append(f"data: {json.dumps(chunk)}\n".encode())
        if done:
            lines.append(b"data: [DONE]\n")
        # Wrap as an iterable of lines
        return lines

    def test_yields_tokens(self):
        agent = _make_agent(model="m")
        sse = self._sse_bytes("hello", " world")
        mock_resp = MagicMock()
        mock_resp.__iter__ = MagicMock(return_value=iter(sse))
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        # _resolve_model tries to fetch /v1/models; skip it since model is set
        with patch.object(agent, "_resolve_model"):
            with patch("open_codex.agents.lmstudio_agent.urllib.request.urlopen",
                       return_value=mock_resp):
                tokens = list(agent._stream_tokens([{"role": "user", "content": "hi"}]))
        assert tokens == ["hello", " world"]

    def test_raises_connection_error_on_url_error(self):
        import urllib.error
        agent = _make_agent(model="m")
        with patch.object(agent, "_resolve_model"):
            with patch("open_codex.agents.lmstudio_agent.urllib.request.urlopen",
                       side_effect=urllib.error.URLError("refused")):
                with pytest.raises(ConnectionError, match="LM Studio"):
                    list(agent._stream_tokens([{"role": "user", "content": "q"}]))


# ── one_shot_mode ─────────────────────────────────────────────────────────────

class TestLMStudioOneShotMode:
    def test_raises_when_no_models(self):
        agent = _make_agent()
        with patch.object(agent, "_get_available_models", return_value=[]):
            with pytest.raises(ConnectionError, match="LM Studio"):
                agent.one_shot_mode("hello")

    def test_auto_selects_model_when_none_specified(self):
        """When model_name is None, one_shot_mode resolves and sets it."""
        agent = _make_agent()  # model_name=None
        with patch.object(agent, "_get_available_models", return_value=["coder-v2"]):
            with patch.object(agent, "_generate_completion", return_value="result"):
                result = agent.one_shot_mode("hello")
        # model_name should be set after one_shot_mode resolves it
        assert agent.model_name == "coder-v2"
        assert result == "result"

    def test_partial_match_fallback(self):
        """When exact model is not found, use a partial-match model."""
        agent = _make_agent(model="mistral")
        with patch.object(agent, "_get_available_models",
                          return_value=["mistral-7b-instruct"]):
            with patch.object(agent, "_generate_completion", return_value="ok"):
                agent.one_shot_mode("q")
        assert agent.model_name == "mistral-7b-instruct"

    def test_single_model_fallback(self):
        """When requested model is not found and only one model exists, use it."""
        agent = _make_agent(model="nonexistent")
        with patch.object(agent, "_get_available_models", return_value=["only-model"]):
            with patch.object(agent, "_generate_completion", return_value="ok"):
                agent.one_shot_mode("q")
        assert agent.model_name == "only-model"

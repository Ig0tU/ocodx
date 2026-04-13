import re
from importlib.resources import files
from typing import Callable, Optional


def _sanitize_ollama_host(host: str) -> str:
    """
    Strip any trailing /api or /api/ segment from an Ollama host URL.

    The official Ollama Python SDK appends /api/chat (or /api/...) to
    whatever host string it receives.  If the host already ends with /api
    the SDK builds the double-path  /api/api/chat  which returns 404.

    Examples
    --------
    'https://ollama.com/api'   -> 'https://ollama.com'
    'https://ollama.com/api/'  -> 'https://ollama.com'
    'http://localhost:11434'   -> 'http://localhost:11434'  (unchanged)
    """
    return re.sub(r'/api/?$', '', host.rstrip('/'))


class AgentBuilder:

    @staticmethod
    def get_system_prompt() -> str:
        return files("open_codex.resources") \
            .joinpath("prompt.txt") \
            .read_text(encoding="utf-8")

    # ── One-shot agents (CLI / TUI) ───────────────────────────────────────────

    @staticmethod
    def get_phi_agent():
        from open_codex.agents.phi_4_mini_agent import Phi4MiniAgent
        return Phi4MiniAgent(system_prompt=AgentBuilder.get_system_prompt())

    @staticmethod
    def get_ollama_agent(model: str, host: str, api_key: str = None):
        from open_codex.agents.ollama_agent import OllamaAgent
        return OllamaAgent(
            system_prompt=AgentBuilder.get_system_prompt(),
            model_name=model,
            host=_sanitize_ollama_host(host),
            api_key=api_key,
        )

    @staticmethod
    def get_lmstudio_agent(model: str, host: str):
        from open_codex.agents.lmstudio_agent import LMStudioAgent
        return LMStudioAgent(
            system_prompt=AgentBuilder.get_system_prompt(),
            model_name=model, host=host,
        )

    @staticmethod
    def get_gemini_agent(model: Optional[str], api_key: Optional[str]):
        from open_codex.agents.gemini_agent import GeminiAgent
        return GeminiAgent(
            system_prompt=AgentBuilder.get_system_prompt(),
            model_name=model or "gemini-2.0-flash",
            api_key=api_key or "",
        )

    # ── LLM caller for the coding agent ──────────────────────────────────────

    @staticmethod
    def get_llm_caller(
        agent_type: str,
        model: Optional[str],
        host: Optional[str],
        api_key: Optional[str] = None,
    ) -> Callable[[list], str]:
        """
        Return a callable(messages: list[dict]) -> str that the CodingAgent
        can use for its iterative tool loop.
        """
        if agent_type == "phi":
            from open_codex.agents.phi_4_mini_agent import Phi4MiniAgent
            phi = Phi4MiniAgent(system_prompt="")  # system injected via messages

            def phi_caller(messages: list) -> str:
                from typing import cast
                from llama_cpp import CreateCompletionResponse
                full_prompt = _phi_format(messages)
                with Phi4MiniAgent.suppress_native_stderr():
                    raw = phi.llm(prompt=full_prompt, max_tokens=800, temperature=0.2, stream=False)
                out = cast(CreateCompletionResponse, raw)
                return out["choices"][0]["text"].strip()

            return phi_caller

        elif agent_type == "lmstudio":
            agent = AgentBuilder.get_lmstudio_agent(model, host or "http://localhost:1234")
            return agent._generate_completion

        elif agent_type in ("ollama", "ollama_cloud"):
            # NOTE: the Ollama SDK appends /api/chat to the host internally.
            # _sanitize_ollama_host() strips any trailing /api so the SDK
            # never builds the double-path /api/api/chat (404).
            default_host = (
                "https://ollama.com" if agent_type == "ollama_cloud"
                else "http://localhost:11434"
            )
            default_model = (
                "llama3.2" if agent_type == "ollama" else "qwen3-coder:480b-cloud"
            )
            raw_host = host or default_host
            agent = AgentBuilder.get_ollama_agent(
                model or default_model,
                _sanitize_ollama_host(raw_host),
                api_key,
            )
            return agent._generate_completion

        elif agent_type == "gemini":
            agent = AgentBuilder.get_gemini_agent(model, api_key)
            return agent._generate_completion

        raise ValueError(f"Unknown agent type: {agent_type}")

    @staticmethod
    def read_file(file_path: str) -> str:
        with open(file_path, 'r') as f:
            return f.read()


def _phi_format(messages: list) -> str:
    """Format OpenAI-style messages for Phi-4-mini's chat template."""
    prompt = ""
    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        if role == "system":
            prompt += f"<|system|>\n{content}\n"
        elif role == "user":
            prompt += f"<|user|>\n{content}\n"
        else:
            prompt += f"<|assistant|>\n{content}\n"
    prompt += "<|assistant|>\n"
    return prompt

"""
Terminal AI Agent integration.

Detects and runs installed terminal AI agent CLIs (Claude Code, Gemini CLI,
OpenAI Codex, OpenClaw) as first-class coding agents within Open Codex.
"""
import json
import os
import shutil
import subprocess
import logging
from typing import Generator

logger = logging.getLogger(__name__)

# ── Registry ──────────────────────────────────────────────────────────────────

TERMINAL_AGENTS: dict[str, dict] = {
    "claude_code": {
        "label": "Claude Code",
        "binary": "claude",
        "icon": "◆",
        "description": "Anthropic's Claude Code CLI agent",
        "auth_hint": "Run: claude login",
    },
    "gemini_cli": {
        "label": "Gemini CLI",
        "binary": "gemini",
        "icon": "✦",
        "description": "Google's Gemini CLI coding agent",
        "auth_hint": "Set GEMINI_API_KEY or run: gemini auth",
    },
    "codex": {
        "label": "OpenAI Codex",
        "binary": "codex",
        "icon": "◈",
        "description": "OpenAI Codex CLI coding agent",
        "auth_hint": "Set OPENAI_API_KEY environment variable",
    },
    "openclaw": {
        "label": "OpenClaw",
        "binary": "openclaw",
        "icon": "⊛",
        "description": "OpenClaw AI coding agent",
        "auth_hint": "Run: openclaw auth",
    },
    "opencode": {
        "label": "OpenCode",
        "binary": "opencode",
        "icon": "⬡",
        "description": "OpenCode AI coding agent",
        "auth_hint": "Set OPENAI_API_KEY or ANTHROPIC_API_KEY",
    },
    "qwen_cli": {
        "label": "Qwen CLI",
        "binary": "qwen",
        "icon": "◉",
        "description": "Qwen AI coding agent (Alibaba)",
        "auth_hint": "Set DASHSCOPE_API_KEY or configure Ollama with a Qwen model",
    },
}


# ── Detection ─────────────────────────────────────────────────────────────────

def detect_terminal_agents() -> list[dict]:
    """Return status of all known terminal AI agent CLIs."""
    results = []
    for agent_id, info in TERMINAL_AGENTS.items():
        binary = info["binary"]
        path = shutil.which(binary)
        available = path is not None
        authenticated = False
        version = None

        if available:
            version = _get_version(binary)
            authenticated = _is_authenticated(agent_id)

        results.append({
            "id": agent_id,
            "label": info["label"],
            "icon": info["icon"],
            "description": info["description"],
            "auth_hint": info["auth_hint"],
            "available": available,
            "authenticated": authenticated,
            "version": version,
            "path": path,
        })
    return results


def _get_version(binary: str) -> str | None:
    try:
        r = subprocess.run(
            [binary, "--version"],
            capture_output=True, text=True, timeout=5,
        )
        out = (r.stdout or r.stderr or "").strip()
        return out.splitlines()[0] if out else None
    except Exception:
        return None


def _is_authenticated(agent_id: str) -> bool:
    if agent_id == "claude_code":
        claude_dir = os.path.expanduser("~/.claude")
        settings = os.path.join(claude_dir, "settings.json")
        return os.path.isfile(settings)

    elif agent_id == "gemini_cli":
        if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
            return True
        gemini_dir = os.path.expanduser("~/.gemini")
        return os.path.isdir(gemini_dir)

    elif agent_id == "codex":
        return bool(os.getenv("OPENAI_API_KEY"))

    elif agent_id == "openclaw":
        if os.getenv("OPENCLAW_API_KEY") or os.getenv("ANTHROPIC_API_KEY"):
            return True
        oc_dir = os.path.expanduser("~/.openclaw")
        return os.path.isdir(oc_dir)

    elif agent_id == "opencode":
        return bool(
            os.getenv("OPENAI_API_KEY")
            or os.getenv("ANTHROPIC_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
        )

    elif agent_id == "qwen_cli":
        return bool(
            os.getenv("DASHSCOPE_API_KEY")
            or shutil.which("ollama")  # Qwen models available via Ollama
        )

    return False


# ── Runner ────────────────────────────────────────────────────────────────────

# ── Matrix header (dynamic per orchestrator) ─────────────────────────────────

def _make_matrix_header(agent_id: str, label: str) -> str:
    """
    Return a personalised OCODX-MATRIX context block addressed to the
    specific orchestrator agent that is being invoked.  This tells the
    agent exactly who it is and what its role is within Open Codex,
    regardless of whether it reads env vars or external config files.
    """
    config_hint = {
        "claude_code": "Your CLAUDE.md contains the full matrix reference.",
        "gemini_cli":  "Your BUILD.md contains the full matrix reference.",
        "codex":       "Your AGENTS.md contains the full matrix reference.",
        "opencode":    "Your opencode.md contains the full matrix reference.",
        "openclaw":    "Your openclaw.md contains the full matrix reference.",
        "qwen_cli":    "Your qwen.md contains the full matrix reference.",
    }.get(agent_id, "The full matrix reference is embedded below.")

    return f"""[OCODX-MATRIX — Orchestrator: {label}]

You ({label}) are the SOVEREIGN LIQUID MATRIX ORCHESTRATOR for this session.
You have been invoked by Open Codex (http://localhost:8000/api/) to lead the
full SLM agent grid. {config_hint}

Your operating mandate:
1. Identify which matrix node(s) are best suited to the task below.
2. Announce the active node(s): e.g. "▶ A1 · Backend Architect active"
3. Execute in that agent's voice/persona, sequentially if multi-node.
4. Deliver concrete output: code, commands, config, or decisions.

Matrix quick-reference (full details in your config file):
  A1-A5 Architecture · L1-L7 Language · I1-I4 Cloud/Infra
  O1-O4 Operations  · D1-D5 AI/Data  · Q1-Q7 Quality
  B1-B3 Business    · G1-G3 Growth   · GYM Forge new agents

OCODX API endpoints available to you:
  GET  http://localhost:8000/api/slm/agents    — full matrix roster
  GET  http://localhost:8000/api/slm/phases    — workflow phases
  POST http://localhost:8000/api/chat/stream   — invoke any SLM agent
  POST http://localhost:8000/api/browser/run   — launch AI browser task
  GET  http://localhost:8000/api/gym/agents    — forged custom agents
  GET  http://localhost:8000/api/mcp/servers   — active MCP servers

--- USER REQUEST ---
"""


def run_terminal_agent(
    agent_id: str,
    prompt: str,
    project_dir: str,
) -> Generator[dict, None, None]:
    """Spawn a terminal agent CLI and yield SSE-compatible event dicts."""
    info = TERMINAL_AGENTS.get(agent_id)
    if not info:
        yield {"type": "error", "content": f"Unknown terminal agent: {agent_id}"}
        return

    binary = info["binary"]
    label  = info["label"]   # resolve before first use
    if not shutil.which(binary):
        yield {"type": "error", "content": f"{label} is not installed (binary: {binary})"}
        return

    # Prepend personalised OCODX-MATRIX header so every agent knows its role
    enriched_prompt = _make_matrix_header(agent_id, label) + prompt

    cmd = _build_cmd(agent_id, binary, enriched_prompt)
    logger.info("Terminal agent %s cmd: %s cwd: %s", agent_id, cmd, project_dir)

    yield {"type": "thinking", "content": f"{info['icon']} {label} activated as Matrix Orchestrator"}

    # Inject OCODX env vars — allows BUILD.md / CLAUDE.md / AGENTS.md etc.
    # to detect they are operating inside Open Codex and switch to orchestrator mode.
    env = os.environ.copy()
    env["OCODX"] = "1"
    env["OCODX_HOST"] = "http://localhost:8000"
    env["OCODX_AGENT"] = agent_id
    env["OCODX_ORCHESTRATOR"] = label  # e.g. "Claude Code", "Gemini CLI"

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=project_dir,
            env=env,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError:
        yield {"type": "error", "content": f"{binary} not found on PATH"}
        return
    except OSError as e:
        yield {"type": "error", "content": f"Failed to start {label}: {e}"}
        return

    collected: list[str] = []

    if agent_id == "claude_code":
        yield from _stream_claude_json(proc, collected)
    else:
        yield from _stream_raw(proc, label, collected)

    rc = proc.wait()
    if rc != 0 and not collected:
        yield {"type": "error", "content": f"{label} exited with code {rc}"}
        return

    full = "".join(collected).strip()
    if full:
        yield {"type": "message", "content": full}
    yield {"type": "done", "stats": {"files_changed": []}}


# ── Stream adapters ───────────────────────────────────────────────────────────

def _stream_raw(proc, label: str, collected: list[str]) -> Generator[dict, None, None]:
    """Stream plain-text output line by line as thinking_text events."""
    for line in proc.stdout:
        collected.append(line)
        stripped = line.rstrip()
        if stripped:
            yield {"type": "thinking_text", "content": stripped}


def _stream_claude_json(proc, collected: list[str]) -> Generator[dict, None, None]:
    """
    Parse Claude Code --output-format stream-json lines into typed events.
    Falls back to raw text for unrecognised lines.
    """
    for raw_line in proc.stdout:
        line = raw_line.rstrip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            collected.append(raw_line)
            if line:
                yield {"type": "thinking_text", "content": line}
            continue

        ev_type = obj.get("type", "")

        if ev_type == "assistant":
            msg = obj.get("message", {})
            for block in msg.get("content", []):
                if block.get("type") == "text":
                    text = block.get("text", "")
                    collected.append(text + "\n")
                    yield {"type": "thinking_text", "content": text}
                elif block.get("type") == "tool_use":
                    yield {
                        "type": "tool_call",
                        "tool": block.get("name", ""),
                        "args": block.get("input", {}),
                    }

        elif ev_type == "tool":
            yield {
                "type": "tool_call",
                "tool": obj.get("name", ""),
                "args": obj.get("input", {}),
            }

        elif ev_type == "tool_result":
            content = obj.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "") for b in content if isinstance(b, dict)
                )
            yield {"type": "tool_result", "tool": "", "result": str(content)}

        elif ev_type == "result":
            result_text = obj.get("result", "")
            if result_text:
                collected.append(result_text + "\n")

        elif ev_type == "error":
            msg = obj.get("message") or obj.get("error") or json.dumps(obj)
            yield {"type": "error", "content": f"Claude Code error: {msg}"}

        elif ev_type in ("system", "user", "rate_limit_event", "debug"):
            pass  # informational / echo — suppress from UI

        else:
            # Unknown type — show condensed so it doesn't flood the UI
            yield {"type": "thinking_text", "content": f"[{ev_type}]"}


# ── Command builders ──────────────────────────────────────────────────────────

def _build_cmd(agent_id: str, binary: str, prompt: str) -> list[str]:
    if agent_id == "claude_code":
        return [
            binary,
            "--dangerously-skip-permissions",
            "-p", prompt,
        ]
    elif agent_id == "gemini_cli":
        # gemini CLI: prompt as positional arg; -p flag not universal
        return [binary, prompt]
    elif agent_id == "codex":
        # openai/codex CLI
        return [binary, prompt]
    elif agent_id == "openclaw":
        return [binary, "-p", prompt]
    elif agent_id == "opencode":
        return [binary, prompt]
    elif agent_id == "qwen_cli":
        return [binary, prompt]
    return [binary, prompt]

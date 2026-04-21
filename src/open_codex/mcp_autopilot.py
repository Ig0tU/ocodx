"""
Auto-MCPilot — Autonomous Background Tool & Cluster Builder
============================================================

When enabled, runs recurring cycles that:
  1. Snapshot current MCP servers, clusters, and project context
  2. Ask the AI to generate expansion ideas (repos to add, clusters to forge,
     tool-chains to compose, scenarios to create)
  3. Execute those ideas autonomously
  4. Broadcast progress via SSE so the UI can show a live activity feed
  5. Log everything to ~/.open_codex/autopilot/log.jsonl

Toggle:  POST /api/autopilot/toggle  { "enabled": true/false, "interval_min": 10 }
Status:  GET  /api/autopilot/status
Logs:    GET  /api/autopilot/log?n=50
Stream:  GET  /api/autopilot/stream   (SSE — subscribe in the Gym panel)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

logger = logging.getLogger(__name__)

_PILOT_DIR = Path.home() / ".open_codex" / "autopilot"
_PILOT_DIR.mkdir(parents=True, exist_ok=True)
_LOG_FILE    = _PILOT_DIR / "log.jsonl"
_STATE_FILE  = _PILOT_DIR / "state.json"

# ── SSE subscriber queue pool ──────────────────────────────────────────────────
_subscribers: list[asyncio.Queue] = []

def _broadcast(event: dict) -> None:
    """Push an event to all live SSE subscribers."""
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


def _log(level: str, msg: str, detail: Any = None) -> dict:
    event = {
        "id":        str(uuid.uuid4())[:8],
        "ts":        datetime.now(timezone.utc).isoformat(),
        "level":     level,   # "info" | "success" | "warning" | "error" | "idea"
        "msg":       msg,
        "detail":    detail,
    }
    try:
        with _LOG_FILE.open("a") as f:
            f.write(json.dumps(event) + "\n")
    except Exception:
        pass
    _broadcast(event)
    logger.info("[AutoMCPilot] [%s] %s", level.upper(), msg)
    return event


async def subscribe() -> AsyncGenerator[dict, None]:
    """SSE generator — yields events as they are broadcast."""
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subscribers.append(q)
    try:
        while True:
            event = await q.get()
            yield event
    finally:
        _subscribers.remove(q)


# ── State ──────────────────────────────────────────────────────────────────────

def _load_state() -> dict:
    try:
        return json.loads(_STATE_FILE.read_text())
    except Exception:
        return {"enabled": False, "interval_min": 10, "runs": 0,
                "last_run": None, "total_built": 0}


def _save_state(state: dict) -> None:
    _STATE_FILE.write_text(json.dumps(state, indent=2))


def load_log(n: int = 100) -> list[dict]:
    try:
        lines = _LOG_FILE.read_text().splitlines()
        return [json.loads(l) for l in lines[-n:]]
    except Exception:
        return []


# ── Context snapshot ───────────────────────────────────────────────────────────

def _snapshot_context(bridge: Any) -> dict:
    """Gather current system state for the idea-generator prompt."""
    from open_codex.mcp_servers_gym import load_custom_clusters, load_scenarios, load_mcp_registry
    from open_codex.mcp_servers_repo import list_repos

    servers = []
    for srv in bridge.all_servers():
        servers.append({
            "id":       srv.id,
            "name":     srv.name,
            "category": srv.category,
            "tools":    [t.name for t in srv.tools],
        })

    repos    = [r.get("name", r.get("slug", "?")) for r in list_repos()]
    clusters = load_custom_clusters()
    scenarios = load_scenarios()
    mcp_reg  = load_mcp_registry()

    return {
        "mcp_servers":  servers,
        "repos_loaded": repos,
        "clusters":     [c.get("name") for c in clusters],
        "scenarios":    [s.get("name") for s in scenarios],
        "mcp_registry": [r.get("id") for r in mcp_reg][:20],
    }


# ── AI idea generator ──────────────────────────────────────────────────────────

_IDEA_SCHEMA = """\
Respond ONLY with a JSON object in this exact schema — no prose, no markdown fences:

{
  "ideas": [
    {
      "type": "repo",
      "url":  "https://github.com/owner/repo",
      "name": "short-name",
      "reason": "one sentence why this is useful"
    },
    {
      "type": "cluster",
      "name": "ClusterName",
      "agents": [
        {
          "coord": "A1",
          "cluster": "ClusterName",
          "name": "Agent Display Name",
          "keyword": "/keyword",
          "brilliance": "One sentence describing this agent's specialty and role."
        }
      ],
      "reason": "one sentence why this cluster is useful"
    },
    {
      "type": "scenario",
      "name": "Scenario Name",
      "description": "What this scenario tests or achieves",
      "goal": "The measurable success criterion",
      "reason": "why this is useful"
    }
  ]
}

Rules:
- Include 1-3 ideas total per run. Do not include duplicates of what already exists.
- For repos: only suggest real, well-known GitHub repos relevant to the current toolset.
- For clusters: 2-4 agents per cluster, each with a unique role.
- For scenarios: specific, actionable goals.
- Prefer quality over quantity. One excellent idea beats three mediocre ones.
"""

def _build_prompt(context: dict, max_per_run: int = 3) -> str:
    ctx_json = json.dumps(context, indent=2)
    return f"""You are the Auto-MCPilot — the autonomous expansion engine for Open Codex, a local-first agentic coding environment.

Your job: analyze the current system state and autonomously decide what tools, repos, and agent clusters to add next.

CURRENT SYSTEM STATE:
{ctx_json}

WHAT TO CONSIDER:
- What types of problems does the current toolset solve well? What gaps exist?
- What GitHub repositories would give agents new superpowers if added as MCP tools?
- What new agent cluster configurations would improve autonomous task coverage?
- What scenarios would help train the agents to handle real-world situations better?

Generate {max_per_run} concrete, high-value expansion ideas.

{_IDEA_SCHEMA}"""


def _call_ai(prompt: str, config: dict) -> str:
    """Synchronous AI call for use in background thread."""
    provider = (config.get("AI_PROVIDER") or os.getenv("JOOMLA_AI_PROVIDER") or "ollama").lower()
    try:
        if provider in ("ollama", ""):
            import ollama as _ol
            host  = re.sub(r"/api/?$", "",
                           (config.get("OLLAMA_HOST") or os.getenv("OLLAMA_HOST")
                            or "http://localhost:11434").rstrip("/"))
            model = config.get("OLLAMA_MODEL") or os.getenv("OLLAMA_MODEL") or "llama3"
            oc    = _ol.Client(host=host)
            resp  = oc.chat(model=model,
                            messages=[{"role": "user", "content": prompt}],
                            options={"num_predict": 1200, "temperature": 0.6})
            return resp["message"]["content"].strip()

        elif provider == "lmstudio":
            import httpx
            host  = (config.get("LMSTUDIO_HOST") or os.getenv("LMSTUDIO_HOST")
                     or "http://localhost:1234").rstrip("/")
            model = config.get("LMSTUDIO_MODEL") or os.getenv("LMSTUDIO_MODEL") or "local-model"
            r = httpx.post(f"{host}/v1/chat/completions", json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1200, "temperature": 0.6,
            }, timeout=90)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()

        elif provider == "gemini":
            import google.generativeai as genai
            genai.configure(api_key=config.get("GEMINI_API_KEY")
                            or os.getenv("GEMINI_API_KEY", ""))
            m = genai.GenerativeModel(
                config.get("GEMINI_MODEL") or "gemini-2.0-flash")
            return m.generate_content(prompt).text.strip()

        elif provider in ("anthropic", "claude"):
            import anthropic as _ant
            api_key = (config.get("ANTHROPIC_API_KEY")
                       or os.getenv("ANTHROPIC_API_KEY", ""))
            model = (config.get("ANTHROPIC_MODEL")
                     or os.getenv("ANTHROPIC_MODEL")
                     or "claude-haiku-4-5-20251001")
            client = _ant.Anthropic(api_key=api_key)
            resp = client.messages.create(
                model=model,
                max_tokens=1200,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text.strip()

        elif provider == "openai":
            import openai as _oai
            api_key = (config.get("OPENAI_API_KEY")
                       or os.getenv("OPENAI_API_KEY", ""))
            model = (config.get("OPENAI_MODEL")
                     or os.getenv("OPENAI_MODEL")
                     or "gpt-4o-mini")
            client = _oai.OpenAI(api_key=api_key)
            resp = client.chat.completions.create(
                model=model,
                max_tokens=1200,
                temperature=0.6,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.choices[0].message.content.strip()

        else:
            return ""
    except Exception as e:
        logger.warning("[AutoMCPilot] AI call failed (%s): %s", provider, e)
        return ""


def _parse_ideas(raw: str) -> list[dict]:
    """Extract the JSON ideas array from the AI response (tolerant parser)."""
    # Strip markdown fences
    raw = re.sub(r"```[a-z]*\n?", "", raw).strip()
    # Find the outermost {}
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start < 0 or end <= 0:
        return []
    try:
        data = json.loads(raw[start:end])
        ideas = data.get("ideas", [])
        if not isinstance(ideas, list):
            return []
        return [i for i in ideas if isinstance(i, dict) and "type" in i]
    except Exception as e:
        logger.warning("[AutoMCPilot] Failed to parse AI ideas: %s", e)
        return []


# ── Idea executors ─────────────────────────────────────────────────────────────

def _execute_repo(idea: dict, bridge: Any, ai_config: dict) -> str:
    from open_codex.mcp_servers_repo import add_repo, list_repos
    url  = idea.get("url", "").strip()
    name = idea.get("name", "").strip() or None
    if not url or not url.startswith("https://github.com/"):
        return f"Skipped: invalid URL '{url}'"
    # Don't re-add already loaded repos
    existing = [r.get("url", "") for r in list_repos()]
    if any(url.rstrip("/").rstrip(".git") in e for e in existing):
        return f"Skipped: '{url}' already loaded"
    try:
        manifest = add_repo(bridge, url=url, name=name, ai_config=ai_config)
        return f"✓ Repo added: {manifest['name']} ({len(manifest.get('public_symbols',[]))} symbols detected)"
    except Exception as e:
        return f"✗ Repo add failed: {e}"


def _execute_cluster(idea: dict) -> str:
    from open_codex.mcp_servers_gym import load_custom_clusters, save_custom_clusters
    name   = idea.get("name", "").strip()
    agents = idea.get("agents", [])
    if not name or not agents:
        return "Skipped: cluster missing name or agents"
    clusters = load_custom_clusters()
    if any(c.get("name") == name for c in clusters):
        return f"Skipped: cluster '{name}' already exists"
    record = {
        "id":       str(uuid.uuid4())[:8],
        "name":     name,
        "agents":   agents,
        "created":  datetime.now(timezone.utc).isoformat(),
        "source":   "autopilot",
    }
    clusters.append(record)
    save_custom_clusters(clusters)
    return f"✓ Cluster forged: '{name}' with {len(agents)} agents"


def _execute_scenario(idea: dict) -> str:
    from open_codex.mcp_servers_gym import load_scenarios, save_scenarios
    name = idea.get("name", "").strip()
    if not name:
        return "Skipped: scenario missing name"
    scenarios = load_scenarios()
    if any(s.get("name") == name for s in scenarios):
        return f"Skipped: scenario '{name}' already exists"
    record = {
        "id":          str(uuid.uuid4())[:8],
        "name":        name,
        "description": idea.get("description", ""),
        "goal":        idea.get("goal", ""),
        "source":      "autopilot",
        "created":     datetime.now(timezone.utc).isoformat(),
    }
    scenarios.append(record)
    save_scenarios(scenarios)
    return f"✓ Scenario created: '{name}'"


# ── Main run cycle ─────────────────────────────────────────────────────────────

def _run_cycle(bridge: Any, config: dict) -> dict:
    """
    One full autopilot tick:
    1. Snapshot context
    2. Generate ideas via AI
    3. Execute ideas
    4. Return summary
    """
    _log("info", "🤖 Auto-MCPilot cycle starting…")

    context = _snapshot_context(bridge)
    _log("info", f"Context: {len(context['mcp_servers'])} servers, "
         f"{len(context['repos_loaded'])} repos, "
         f"{len(context['clusters'])} clusters")

    prompt = _build_prompt(context)
    _log("info", "Requesting expansion ideas from AI…")

    raw = _call_ai(prompt, config)
    if not raw:
        _log("warning", "⚠ AI returned empty response — skipping cycle")
        return {"built": 0, "ideas": []}

    ideas = _parse_ideas(raw)
    if not ideas:
        _log("warning", f"⚠ Could not parse ideas from AI response: {raw[:200]}")
        return {"built": 0, "ideas": []}

    _log("idea", f"💡 {len(ideas)} idea(s) generated", ideas)

    built = 0
    results = []
    for idea in ideas:
        itype  = idea.get("type", "")
        reason = idea.get("reason", "")
        _log("info", f"Executing idea [{itype}]: {reason}")

        if itype == "repo":
            result = _execute_repo(idea, bridge, config)
        elif itype == "cluster":
            result = _execute_cluster(idea)
        elif itype == "scenario":
            result = _execute_scenario(idea)
        else:
            result = f"Unknown idea type: {itype}"

        ok = result.startswith("✓")
        if ok:
            built += 1
        _log("success" if ok else "warning", result, idea)
        results.append({"idea": idea, "result": result})

    _log("success" if built > 0 else "info",
         f"✅ Cycle complete — {built}/{len(ideas)} ideas executed successfully")
    return {"built": built, "ideas": results}


# ── Background loop ────────────────────────────────────────────────────────────

_task: Optional[asyncio.Task] = None
_state: dict = _load_state()


async def _loop(bridge: Any, config: dict) -> None:
    global _state
    while _state.get("enabled", False):
        interval_sec = max(60, int(_state.get("interval_min", 10)) * 60)
        try:
            loop = asyncio.get_event_loop()
            summary = await loop.run_in_executor(
                None, _run_cycle, bridge, config
            )
            _state["runs"]         += 1
            _state["last_run"]      = datetime.now(timezone.utc).isoformat()
            _state["total_built"]  += summary.get("built", 0)
            _save_state(_state)
        except Exception as e:
            _log("error", f"Cycle error: {e}")
        _log("info", f"💤 Sleeping {_state.get('interval_min', 10)} min until next cycle…")
        for _ in range(interval_sec):
            if not _state.get("enabled", False):
                break
            await asyncio.sleep(1)
    _log("info", "Auto-MCPilot stopped.")


# ── Public API ─────────────────────────────────────────────────────────────────

def toggle(enabled: bool, bridge: Any, config: dict,
           interval_min: int = 10) -> dict:
    """Enable or disable the autopilot background loop."""
    global _task, _state
    _state = _load_state()
    _state["enabled"]      = enabled
    _state["interval_min"] = max(1, interval_min)
    _save_state(_state)

    if enabled and (_task is None or _task.done()):
        loop = asyncio.get_event_loop()
        _task = loop.create_task(_loop(bridge, config))
        _log("success", f"🚀 Auto-MCPilot ENABLED — running every {interval_min} min")
    elif not enabled:
        _log("info", "🛑 Auto-MCPilot DISABLED")

    return get_status()


def get_status() -> dict:
    s = _load_state()
    return {
        "enabled":       s.get("enabled", False),
        "interval_min":  s.get("interval_min", 10),
        "runs":          s.get("runs", 0),
        "last_run":      s.get("last_run"),
        "total_built":   s.get("total_built", 0),
        "active":        _task is not None and not (_task.done() or _task.cancelled()),
    }


def run_now(bridge: Any, config: dict) -> None:
    """Trigger an immediate cycle (non-blocking)."""
    loop = asyncio.get_event_loop()
    async def _once():
        _log("info", "⚡ Manual trigger — running cycle now…")
        await loop.run_in_executor(None, _run_cycle, bridge, config)
    loop.create_task(_once())

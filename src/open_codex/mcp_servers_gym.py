"""
SLM Gym MCP Server — Agent Forge & Training Tools

The Instructor's dedicated toolset for:
  - Forging new SLM agents to the matrix
  - Building agentic clusters
  - Recording training scenarios / evaluations
  - Expanding the gym's MCP tool surface
  - Researching domains via web fetch
"""

import json
import os
import re
import subprocess
import uuid
from datetime import datetime
from typing import Dict, Any, Callable

from open_codex.mcp_bridge import NativeMCPServer, MCPTool

# ── Storage ───────────────────────────────────────────────────────────────────

GYM_DIR       = os.path.join(os.path.expanduser("~"), ".open_codex", "gym")
AGENTS_FILE   = os.path.join(GYM_DIR, "agents.json")
CLUSTERS_FILE = os.path.join(GYM_DIR, "clusters.json")
SCENARIOS_FILE= os.path.join(GYM_DIR, "scenarios.json")
MCP_REG_FILE  = os.path.join(GYM_DIR, "mcp_installs.json")


def _ensure():
    os.makedirs(GYM_DIR, exist_ok=True)


def load_custom_agents() -> list:
    try:
        with open(AGENTS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_custom_agents(agents: list):
    _ensure()
    with open(AGENTS_FILE, "w") as f:
        json.dump(agents, f, indent=2)


def load_custom_clusters() -> list:
    try:
        with open(CLUSTERS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_custom_clusters(clusters: list):
    _ensure()
    with open(CLUSTERS_FILE, "w") as f:
        json.dump(clusters, f, indent=2)


def load_scenarios() -> list:
    try:
        with open(SCENARIOS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_scenarios(scenarios: list):
    _ensure()
    with open(SCENARIOS_FILE, "w") as f:
        json.dump(scenarios, f, indent=2)


def load_mcp_registry() -> list:
    try:
        with open(MCP_REG_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


# ── GymMCPServer ──────────────────────────────────────────────────────────────

class GymMCPServer(NativeMCPServer):
    """Agent forge and training tools for the SLM Gym Instructor."""

    def __init__(self):
        super().__init__(
            id="gym",
            name="SLM Gym — Agent Forge",
            category="gym",
            icon="🏋️",
            description="Forge, train, and graduate new SLM agents and clusters. "
                        "Records scenarios, installs MCP tools, and researches domains.",
        )
        tools = [
            ("forge_agent",    self._forge_agent,    "Create and graduate a new SLM agent",
             {"coord":      {"type": "string", "required": True,  "description": "Unique ID e.g. GYM-01"},
              "cluster":    {"type": "string", "required": True,  "description": "Cluster name"},
              "name":       {"type": "string", "required": True,  "description": "Full role title"},
              "keyword":    {"type": "string", "required": True,  "description": "/kebab-case-keyword"},
              "brilliance": {"type": "string", "required": True,  "description": "2-4 word cognitive signature"}}),

            ("list_agents",    self._list_agents,    "List all custom agents forged in the gym", {}),

            ("delete_agent",   self._delete_agent,   "Delete a custom agent by coord",
             {"coord": {"type": "string", "required": True}}),

            ("forge_cluster",  self._forge_cluster,  "Create a named agentic cluster",
             {"name":         {"type": "string", "required": True},
              "description":  {"type": "string", "required": True},
              "agent_coords": {"type": "string", "description": "Comma-separated coord IDs of members"}}),

            ("list_clusters",  self._list_clusters,  "List all custom clusters", {}),

            ("run_scenario",   self._run_scenario,   "Record a training scenario / evaluation case",
             {"agent_keyword":   {"type": "string", "required": True},
              "scenario_name":   {"type": "string", "required": True},
              "scenario_prompt": {"type": "string", "required": True},
              "expected_output": {"type": "string"}}),

            ("list_scenarios", self._list_scenarios, "List training scenarios, optionally filtered by agent",
             {"agent_keyword": {"type": "string"}}),

            ("get_agent_info", self._get_agent_info, "Look up any agent by keyword or coord",
             {"query": {"type": "string", "required": True}}),

            ("search_web",     self._search_web,     "Fetch a URL and return its text (domain research)",
             {"url": {"type": "string", "required": True}}),

            ("install_mcp",    self._install_mcp,    "Install and register a new MCP server package",
             {"package_type": {"type": "string", "description": "npm | python"},
              "package_spec": {"type": "string", "required": True},
              "server_name":  {"type": "string", "required": True},
              "description":  {"type": "string"}}),

            ("list_mcp_installs", self._list_mcp_installs, "List all installed MCP packages", {}),
        ]
        for name, fn, desc, params in tools:
            self._register_tool(name, fn, MCPTool(name, desc, params, "gym"))

    # ── forge_agent ───────────────────────────────────────────────────────────

    def _forge_agent(self, params: Dict, project_dir: str) -> str:
        coord      = params.get("coord",      "").strip()
        cluster    = params.get("cluster",    "").strip()
        name       = params.get("name",       "").strip()
        keyword    = params.get("keyword",    "").strip()
        brilliance = params.get("brilliance", "").strip()

        if not all([coord, cluster, name, keyword, brilliance]):
            return "ERROR: coord, cluster, name, keyword, and brilliance are all required"

        if not keyword.startswith("/"):
            keyword = "/" + keyword

        agents = load_custom_agents()
        if any(a["coord"] == coord for a in agents):
            return f"ERROR: Agent '{coord}' already exists. Choose a different coord."
        if any(a["keyword"] == keyword for a in agents):
            return f"ERROR: Keyword '{keyword}' already taken. Choose a different keyword."

        agent = {
            "coord":      coord,
            "cluster":    cluster,
            "name":       name,
            "keyword":    keyword,
            "brilliance": brilliance,
            "created_at": datetime.utcnow().isoformat(),
            "custom":     True,
        }
        agents.append(agent)
        save_custom_agents(agents)

        return json.dumps({
            "status":  "graduated",
            "agent":   {k: v for k, v in agent.items() if k != "created_at"},
            "message": f"✓ {coord} '{name}' graduated to the SLM Matrix",
        }, indent=2)

    # ── list_agents ───────────────────────────────────────────────────────────

    def _list_agents(self, params: Dict, project_dir: str) -> str:
        agents = load_custom_agents()
        if not agents:
            return "No custom agents forged yet. Use forge_agent to graduate your first agent."
        return json.dumps(agents, indent=2)

    # ── delete_agent ──────────────────────────────────────────────────────────

    def _delete_agent(self, params: Dict, project_dir: str) -> str:
        coord = params.get("coord", "").strip()
        agents = load_custom_agents()
        before = len(agents)
        agents = [a for a in agents if a["coord"] != coord]
        if len(agents) == before:
            return f"ERROR: No agent with coord '{coord}' found"
        save_custom_agents(agents)
        return f"✓ Agent '{coord}' retired from the gym"

    # ── forge_cluster ─────────────────────────────────────────────────────────

    def _forge_cluster(self, params: Dict, project_dir: str) -> str:
        name        = params.get("name", "").strip()
        description = params.get("description", "").strip()
        coords_raw  = params.get("agent_coords", "")
        coords      = [c.strip() for c in coords_raw.split(",") if c.strip()]

        if not name or not description:
            return "ERROR: name and description are required"

        clusters = load_custom_clusters()
        rec = {
            "name":        name,
            "description": description,
            "agents":      coords,
            "created_at":  datetime.utcnow().isoformat(),
        }
        idx = next((i for i, c in enumerate(clusters) if c["name"] == name), None)
        if idx is not None:
            clusters[idx] = rec
        else:
            clusters.append(rec)
        save_custom_clusters(clusters)

        return json.dumps({"status": "forged", "cluster": rec}, indent=2)

    # ── list_clusters ─────────────────────────────────────────────────────────

    def _list_clusters(self, params: Dict, project_dir: str) -> str:
        clusters = load_custom_clusters()
        if not clusters:
            return "No custom clusters yet. Use forge_cluster to create one."
        return json.dumps(clusters, indent=2)

    # ── run_scenario ──────────────────────────────────────────────────────────

    def _run_scenario(self, params: Dict, project_dir: str) -> str:
        keyword  = params.get("agent_keyword",   "").strip()
        s_name   = params.get("scenario_name",   "").strip()
        s_prompt = params.get("scenario_prompt", "").strip()
        expected = params.get("expected_output", "")

        if not all([keyword, s_name, s_prompt]):
            return "ERROR: agent_keyword, scenario_name, and scenario_prompt are required"

        scenarios = load_scenarios()
        rec = {
            "id":            str(uuid.uuid4())[:8],
            "agent_keyword": keyword,
            "name":          s_name,
            "prompt":        s_prompt,
            "expected":      expected,
            "created_at":    datetime.utcnow().isoformat(),
        }
        scenarios.append(rec)
        save_scenarios(scenarios)
        return json.dumps({"status": "recorded", "scenario_id": rec["id"], "name": s_name}, indent=2)

    # ── list_scenarios ────────────────────────────────────────────────────────

    def _list_scenarios(self, params: Dict, project_dir: str) -> str:
        keyword   = params.get("agent_keyword", "")
        scenarios = load_scenarios()
        if keyword:
            scenarios = [s for s in scenarios if keyword in s.get("agent_keyword", "")]
        if not scenarios:
            return "No training scenarios recorded yet."
        return json.dumps(scenarios, indent=2)

    # ── get_agent_info ────────────────────────────────────────────────────────

    def _get_agent_info(self, params: Dict, project_dir: str) -> str:
        q = params.get("query", "").strip().lower()
        if not q:
            return "ERROR: query is required"

        for a in load_custom_agents():
            if q in a.get("coord", "").lower() or q in a.get("keyword", "").lower() or q in a.get("name", "").lower():
                return json.dumps({**a, "source": "custom"}, indent=2)

        try:
            import sys
            api_mod = sys.modules.get("open_codex.api")
            if api_mod:
                for a in getattr(api_mod, "SLM_AGENTS", []):
                    if q in a.get("coord", "").lower() or q in a.get("keyword", "").lower() or q in a.get("name", "").lower():
                        return json.dumps({**a, "source": "built-in"}, indent=2)
        except Exception:
            pass

        return f"No agent found matching '{q}'"

    # ── search_web ────────────────────────────────────────────────────────────

    def _search_web(self, params: Dict, project_dir: str) -> str:
        url = params.get("url", "").strip()
        if not url:
            return "ERROR: url is required"
        try:
            import urllib.request
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 Open-Codex-Gym/1.0"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("utf-8", errors="replace")

            # Strip HTML
            text = re.sub(r'<script[^>]*>.*?</script>', '', raw, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<style[^>]*>.*?</style>',  '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            return text[:4000] + ("…" if len(text) > 4000 else "")
        except Exception as e:
            return f"ERROR fetching {url}: {e}"

    # ── install_mcp ───────────────────────────────────────────────────────────

    _NPM_ALLOWED = (
        "@modelcontextprotocol/", "@anthropic/", "@openai/",
        "mcp-server-", "mcp-", "@mcp/", "claude-mcp",
    )
    _PY_ALLOWED = ("mcp-", "anthropic-mcp", "claude-mcp", "openai-mcp", "mcp_server_")

    def _install_mcp(self, params: Dict, project_dir: str) -> str:
        pkg_type = params.get("package_type", "npm").lower()
        spec     = params.get("package_spec", "").strip()
        srv_name = params.get("server_name",  "").strip()
        desc     = params.get("description",  f"MCP server: {srv_name}")

        if not spec or not srv_name:
            return "ERROR: package_spec and server_name are required"

        if pkg_type == "npm":
            if not any(spec.startswith(p) for p in self._NPM_ALLOWED):
                return (f"ERROR: npm package '{spec}' not in allowlist.\n"
                        f"Allowed prefixes: {self._NPM_ALLOWED}")
            cmd = ["npm", "install", "-g", spec]
        elif pkg_type == "python":
            if not any(spec.startswith(p) for p in self._PY_ALLOWED):
                return (f"ERROR: Python package '{spec}' not in allowlist.\n"
                        f"Allowed prefixes: {self._PY_ALLOWED}")
            cmd = ["pip", "install", spec]
        else:
            return f"ERROR: Unknown package_type '{pkg_type}'. Use 'npm' or 'python'."

        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            if r.returncode != 0:
                return f"ERROR: install failed:\n{r.stderr[:1200]}"

            _ensure()
            registry = load_mcp_registry()
            registry.append({
                "name":         srv_name,
                "type":         pkg_type,
                "spec":         spec,
                "description":  desc,
                "installed_at": datetime.utcnow().isoformat(),
            })
            with open(MCP_REG_FILE, "w") as f:
                json.dump(registry, f, indent=2)

            return (f"✓ Installed '{spec}' as MCP server '{srv_name}'\n"
                    f"Restart the app to load the new server.\n{r.stdout[:400]}")
        except Exception as e:
            return f"ERROR: {e}"

    # ── list_mcp_installs ─────────────────────────────────────────────────────

    def _list_mcp_installs(self, params: Dict, project_dir: str) -> str:
        reg = load_mcp_registry()
        if not reg:
            return "No MCP packages installed via the gym yet."
        return json.dumps(reg, indent=2)

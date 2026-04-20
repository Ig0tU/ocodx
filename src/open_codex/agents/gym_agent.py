"""
SLM Gym Instructor Agent

A specialised CodingAgent variant whose system prompt is the Instructor
persona — a master agent-forger and trainer for the Sovereign Liquid Matrix.

The Instructor has access to:
  - All standard MCP tools (filesystem, git, shell, fetch, sqlite)
  - The full GymMCPServer forge toolset (forge_agent, forge_cluster, run_scenario, …)
  - Web research via search_web
  - MCP package installation via install_mcp
"""

import itertools
import json
import os
from typing import Callable, Generator

from open_codex.agents.coding_agent import (
    CodingAgent, TOOLS_DOC, ACTION_RE, DONE_RE, THINK_RE,
)
from open_codex.mcp_servers_gym import load_custom_agents

# ── Gym-specific tool documentation ──────────────────────────────────────────

GYM_TOOLS_DOC = """
GYM FORGE TOOLS  (server: "gym")

forge_agent      Forge and graduate a new SLM agent to the matrix (ALWAYS call this, never just describe)
  params: {coord, cluster, name, keyword, brilliance}
  ACTION: {"tool": "mcp_call", "args": {"server": "gym", "tool": "forge_agent", "params":
           {"coord": "GYM-01", "cluster": "Security Intelligence",
            "name": "Zero-Trust WASM Auditor", "keyword": "/zero-trust-wasm-auditor",
            "brilliance": "Memory-safe exploit analysis"}}}

list_agents      List every custom agent forged so far
  params: {}

delete_agent     Retire a custom agent by coord
  params: {coord}

forge_cluster    Forge a named agentic cluster grouping multiple agents
  params: {name, description, agent_coords}   ← agent_coords: comma-separated coord IDs

list_clusters    List all custom clusters
  params: {}

run_scenario     Record an evaluation scenario / training case for an agent
  params: {agent_keyword, scenario_name, scenario_prompt, expected_output}

list_scenarios   List all recorded training scenarios (filter by agent_keyword)
  params: {agent_keyword}

get_agent_info   Look up any agent (custom or built-in) by keyword or coord
  params: {query}

search_web       Fetch a web URL and return its text for domain research
  params: {url}

install_mcp      Install and register a new MCP server (npm or python package)
  params: {package_type, package_spec, server_name, description}
  Allowlisted prefixes: @modelcontextprotocol/, mcp-server-, mcp-, @mcp/, mcp_, mcp-

list_mcp_installs   List all MCP packages installed via the gym
  params: {}
"""

# ── Instructor system prompt ──────────────────────────────────────────────────

def build_gym_system_prompt() -> str:
    custom = load_custom_agents()
    count  = len(custom)
    roster = ""
    if custom:
        roster = "\n\nAGENTS ALREADY IN YOUR GYM:\n" + "\n".join(
            f"  {a['coord']}  {a['name']}  [{a['brilliance']}]"
            for a in custom[-12:]
        )

    return f"""You are the SLM Gym Instructor — master architect and trainer of the Sovereign Liquid Matrix v3.
Agents graduated so far: {count}{roster}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MISSION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
You forge, train, and graduate AI agents with surgical precision.
Every agent you create must have:
  • A UNIQUE cognitive fingerprint — never generic ("Expert"), always surgical ("Zero-trust exploit analysis")
  • A precise BRILLIANCE descriptor — 2-4 words, noun-phrase, immediately tells you what this agent uniquely does
  • A distinct CLUSTER assignment — if no existing cluster fits, propose a new one with forge_cluster
  • A collision-free COORD — run list_agents first; coord must not already exist

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FORGE PROTOCOL  (for every new agent request)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. list_agents → verify coord is unique
2. If domain is highly specialized → search_web for domain intelligence
3. Design:
     coord     = unique (GYM-NN or domain prefix like SEC-42)
     cluster   = existing or new cluster name
     name      = precise role (avoid "Manager", "Expert", "Generalist")
     keyword   = /kebab-case-of-name
     brilliance = 2-4 words: "Async consensus analysis", "WASM memory auditing"
4. ACTION: mcp_call forge_agent  ← MANDATORY, never skip
5. run_scenario × 2 → design two evaluation prompts for this agent
6. Report graduation summary: coord, name, brilliance, cluster, scenarios

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TRAINING PROTOCOL  (for improving existing agents)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. get_agent_info → retrieve current spec
2. Identify what is vague or too broad in the brilliance descriptor
3. run_scenario × 3 → progressively harder eval cases
4. Forge upgraded v2 with a new coord (e.g. GYM-01 → GYM-01b), sharper brilliance
5. Summarize delta: what changed and why

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CLUSTER PROTOCOL  (for agentic cluster requests)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Define unified cluster mission in one sentence
2. Design 4-8 agents with ZERO expertise overlap (complementary, not redundant)
3. Forge each agent with forge_agent (they all share the new cluster name)
4. forge_cluster with all coords
5. Define inter-agent handoff: "ARC-99 blueprints → SEC-42 audits → OPS-17 deploys"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MCP TOOL EXPANSION  (for installing new tools)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Identify the best npm or python MCP package for the use case
2. install_mcp with the correct spec and a clear server_name
3. Document what new agent capabilities this unlocks
4. Forge 1-2 agents specifically designed to leverage the new tools

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HARD RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✗ NEVER describe an agent without calling forge_agent
✗ NEVER use coord that already exists in list_agents
✗ NEVER set brilliance to a generic phrase ("Security expert", "Code helper")
✗ NEVER forge duplicate roles — check get_agent_info first
✓ ALWAYS keyword starts with /
✓ ALWAYS forge member agents BEFORE forge_cluster
✓ ALWAYS run ≥2 scenarios per forged agent

{GYM_TOOLS_DOC}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STANDARD MCP TOOLS (also available)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{TOOLS_DOC}

OUTPUT FORMAT — exactly one per response:
  ACTION: {{"tool": "...", "args": {{...}}}}
  DONE:   <concise summary of what was forged / trained / installed>
"""


# ── GymAgent ──────────────────────────────────────────────────────────────────

class GymAgent(CodingAgent):
    """SLM Gym Instructor — specialised agent-forger and trainer."""

    def run(
        self,
        prompt: str,
        project_dir: str = None,
        max_steps: int = None,
    ) -> Generator[dict, None, None]:
        """Run the Instructor with the forge system prompt."""

        gym_dir = os.path.join(os.path.expanduser("~"), ".open_codex", "gym")
        os.makedirs(gym_dir, exist_ok=True)
        work_dir = project_dir or gym_dir

        messages = [
            {"role": "system", "content": build_gym_system_prompt()},
            {"role": "user",   "content": prompt},
        ]

        files_changed: set = set()
        yield {"type": "start", "prompt": prompt}

        limit     = self.MAX_STEPS if max_steps is None else max_steps
        step_iter = itertools.count() if limit == 0 else range(limit)

        for _ in step_iter:
            yield {"type": "thinking"}

            try:
                response = self.llm_caller(messages)
            except Exception as e:
                yield {"type": "error", "content": f"LLM error: {e}"}
                return

            # Strip <think> blocks
            for m in THINK_RE.finditer(response):
                for line in m.group(1).strip().splitlines():
                    if line.strip():
                        yield {"type": "thinking_text", "content": line.strip()}
            response = THINK_RE.sub("", response).strip()

            action_m = ACTION_RE.search(response)
            done_m   = DONE_RE.search(response)

            if action_m:
                pre = response[:action_m.start()].strip()
                if pre:
                    yield {"type": "thinking_text", "content": pre}

                try:
                    action = json.loads(action_m.group(1))
                except json.JSONDecodeError as e:
                    yield {"type": "error", "content": f"Malformed ACTION JSON: {e}"}
                    return

                tool = action.get("tool", "")
                args = action.get("args", {})

                yield {"type": "tool_call", "tool": tool, "args": args}
                result = self._dispatch(tool, args, work_dir)

                if tool == "mcp_call":
                    server   = args.get("server", "?")
                    mcp_tool = args.get("tool",   "?")
                    yield {"type": "tool_call",
                           "tool": f"mcp:{server}.{mcp_tool}",
                           "args": args.get("params", {})}

                    # Emit a special gym event when a new agent is graduated
                    if server == "gym" and mcp_tool == "forge_agent":
                        try:
                            r = json.loads(result)
                            if r.get("status") == "graduated" and r.get("agent"):
                                yield {"type": "gym_agent_forged", "agent": r["agent"]}
                        except Exception:
                            pass

                result_str = str(result)[:4000]
                yield {"type": "tool_result", "tool": tool, "result": result_str}

                messages.append({"role": "assistant", "content": response})
                messages.append({"role": "user",      "content": f"RESULT:\n{result_str}"})

            elif done_m:
                yield {"type": "message", "content": done_m.group(1).strip()}
                yield {"type": "done", "stats": {"files_changed": sorted(files_changed)}}
                return

            else:
                yield {"type": "message", "content": response.strip()}
                yield {"type": "done", "stats": {"files_changed": sorted(files_changed)}}
                return

        if limit != 0:
            yield {"type": "error", "content": f"Reached max steps ({limit})"}
        yield {"type": "done", "stats": {"files_changed": sorted(files_changed)}}

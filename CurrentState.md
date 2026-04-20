# Open Codex — Current State
**Last updated:** 2026-04-20 · Build ✓ (TypeScript + Vite clean, zero errors)

---

## ✅ Completed This Session

### SLM Gym — Full Integration
Agent-forging and training infrastructure is now 100% wired end-to-end.

#### Backend (`src/open_codex/api.py`)
- `GymMCPServer` registered with `_mcp_bridge` at startup
- `gym_instructor` added as a routable `agent_type` in `/api/chat/stream`
  - Provider inferred from `req.slm_context` (e.g. `"ollama"`, `"gemini"`)
- `/api/slm/agents` now **merges** built-in SLM agents with custom Gym agents (custom coord wins on collision)
- New REST endpoints:
  - `GET /api/gym/agents` — list forged agents
  - `GET /api/gym/clusters` — list forged clusters
  - `GET /api/gym/scenarios` — list training scenarios

#### Frontend (`App.tsx` + `App.css`)
- **🏋️ SLM Gym** sidebar button (badge shows forged agent count)
- **Gym Panel** — 4 tabs:
  - 💬 **Instructor** — live streaming chat with `GymAgent`; renders thinking, tool-calls, and `gym_agent_forged` events inline
  - 🤖 **Agents** — cluster-color-coded cards with ▶ Activate to inject into active chat
  - 🔗 **Clusters** — forged multi-agent clusters + training scenarios
  - 📋 **Scenarios** — standalone scenario view
- **Graduation flash banner** — animated gold banner on `gym_agent_forged` SSE event
- After any forge, auto-refreshes Gym roster + Agent Matrix so new agents appear immediately
- Stores conversation in component state (no thread persistence — Instructor is stateful within session)

### Theme System
- **4 themes** — selectable via colored dot swatches in the sidebar bottom bar, persisted to `localStorage`:
  | Key | Name | Accent |
  |-----|------|--------|
  | `void` | Void (default) | Electric violet |
  | `slate` | Slate | Steel blue |
  | `ember` | Ember | Warm amber / obsidian |
  | `light` | Light | Teal on white |
- Zero component-level changes — all themes work via `[data-theme]` CSS attribute overrides on `<html>`
- Per-theme scrollbar colors
- Choice persisted in `localStorage` as `ocdx-theme`

### manage.sh / manage.bat — No Changes Required
- Gym uses only stdlib Python (`json`, `os`, `uuid`, `datetime`, `subprocess`, `re`) — no new pip deps
- Frontend changes are inside the existing Vite bundle — `npm run build` picks them up automatically

---

## Previously Completed

⏺ All routes are registered correctly. Here's a summary of everything
  implemented:

  ---
  Slash Commands — Type / in the input to see a dropdown with 10 commands:
  - /help, /status, /log [n], /diff, /commit <msg>, /push, /pull, /clear, /phase
   <1-6>, /agent <name>
  - Arrow keys + Enter/Tab to navigate the menu; Escape to dismiss
  - Commands execute inline and inject results as chat messages

  Phase Launcher — Fixed: removed the stale-closure setTimeout hack;
  sendMessage(phase.prompt) is now called directly with the correct render-time
  state

  Git Operations — Full push/pull support:
  - New push() / pull() in git_tools.py
  - New POST /api/git/push and POST /api/git/pull endpoints
  - Pull ↓ and Push ↑ buttons added to the commit popover in the topbar

  AI Browser Panel (🌐) — Now accessible from the sidebar:
  - Task textarea + optional starting URL
  - Live frame viewer (base64 JPEG screenshots as the agent navigates)
  - Real-time log stream with auto-scroll
  - Abort button; running indicator in sidebar badge

  Automations Panel (⚡) — Now accessible from the sidebar:
  - Category filter bar
  - Cards for all 20+ automations with Run / 🌐 Browse buttons
  - Non-browser automations send prompt to chat; browser automations pre-fill
  the AI Browser panel

✻ Churned for 15m 34s

❯ give it a gym and instructor that will train/teach the sims/make new trained  
  sims or agents or agentic clusters by integrating new, super powerful mcp     
  tools/servers/etc                                                             

                                              11:30 AM claude-sonnet-4-6
⏺ Let me first explore the existing agent/MCP architecture deeply before
  designing the Gym.

⏺ Explore(Deep dive into agent/MCP architecture)
  ⎿  Prompt:
       Explore the codebase at "/Users/arcsillc/Downloads/ocodx-main 4". I
       need to deeply understand:

       1. src/open_codex/agents/coding_agent.py - Full implementation of
       the ReAct agent loop, how it calls the LLM, how it uses MCP tools,
       how it streams events
       2. src/open_codex/mcp_servers.py - ALL native MCP server
       implementations (especially their _register_tool pattern and how
       tools are called)
       3. src/open_codex/mcp_bridge.py - How the bridge registry works, how
        tools are dispatched
       4. src/open_codex/api.py lines 1-200 and 460-540 - The
       SLM_AGENTS/SLM_PHASES data structure and the /api/slm/* endpoints
       5. src/open_codex/api.py around the /api/chat/stream endpoint - how
       it initializes the agent and calls it
       6. How agents persist/load - is there a storage layer for custom
       agents?

       Report: exact function signatures, tool registration pattern, event
       streaming format, agent data schema (what fields does an SLM agent
       have), and how the /api/chat/stream endpoint wires everything
       together. Include line numbers.
  ⎿  Read(/Users/arcsillc/Downloads/ocodx-main
  ⎿  Read(/Users/arcsillc/Downloads/ocodx-main
  ⎿  Read(/Users/arcsillc/Downloads/ocodx-main
  ⎿  Read(/Users/arcsillc/Downloads/ocodx-main 4/src/open_codex/api.py ·
  ⎿  Read(/Users/arcsillc/Downloads/ocodx-main 4/src/open_codex/api.py ·
  ⎿  Read(/Users/arcsillc/Downloads/ocodx-main 4/src/open_codex/api.py ·
  ⎿  Search(pattern: "**/*.py", path: "/Users/arcsillc/Downloads/ocodx-main
  ⎿  Read(/Users/arcsillc/Downloads/ocodx-main 4/src/open_codex/api.py ·
  ⎿  Read(/Users/arcsillc/Downloads/ocodx-main
  ⎿  Read(/Users/arcsillc/Downloads/ocodx-main 4/src/open_codex/api.py ·
  ⎿  Search(pattern: "custom.agent|agent.storage|save.agent|load.agent|agen
  ⎿  Read(/Users/arcsillc/Downloads/ocodx-main 4/src/open_codex/api.py ·
  ⎿  Read(/Users/arcsillc/Downloads/ocodx-main
  ⎿  Read(/Users/arcsillc/Downloads/ocodx-main 4/src/open_codex/api.py ·
  ⎿  Search(pattern: "@app\.(get|post|put|patch|delete)", path:
  ⎿  Response:
       I now have a complete picture of the entire codebase. Here is the
       full technical report:

       ---
       Deep Codebase Report: Open Codex

       1. coding_agent.py — ReAct Agent Loop

       File: /Users/arcsillc/Downloads/ocodx-main
       4/src/open_codex/agents/coding_agent.py

       Class and Constructor

       class CodingAgent:
           MAX_STEPS = 25

           def __init__(self, llm_caller: Callable[[list], str]):
       - llm_caller is a Callable[[list[dict]], str] — it takes
       OpenAI-format message history and returns a string response. It is
       injected from outside (never instantiated internally).

       Main Loop Signature

       def run(self, prompt: str, project_dir: str, max_steps: int = None)
       -> Generator[dict, None, None]:
       - Line 161. Yields SSE-style event dicts.
       - project_dir is resolved to an absolute real path at line 163.
       - Builds the initial message list (lines 165-168): system prompt
       from _build_system_prompt(project_dir) + user prompt.
       - Loops up to MAX_STEPS (25) or max_steps if provided; max_steps=0
       means unlimited (line 174).

       ReAct Step Sequence (lines 176-254)

       Each iteration:
       1. Yields {"type": "thinking"} (line 177).
       2. Calls self.llm_caller(messages) — raw string response (line 180).
       3. Strips <think>…</think> blocks (thinking models) — emits each
       line as {"type": "thinking_text", "content": line} (lines 188-193).
       4. Applies two regexes to the cleaned response:
         - ACTION_RE = re.compile(r'^ACTION:\s*(\{.+\})\s*$', re.MULTILINE)
        (line 81)
         - DONE_RE   = re.compile(r'^DONE:\s*(.+)', re.MULTILINE |
       re.DOTALL) (line 82)

       If ACTION matched (lines 199-230):
       - Parses action["tool"] and action["args"] from JSON.
       - Yields {"type": "tool_call", "tool": tool, "args": args}.
       - Calls self._dispatch(tool, args, project_dir).
       - If tool == "mcp_call", additionally yields {"type": "tool_call",
       "tool": "mcp:<server>.<mcp_tool>", "args": params}.
       - If tool == "write_file" and no error, yields {"type":
       "file_changed", "path": args["path"]}.
       - Yields {"type": "tool_result", "tool": tool, "result": result_str}
        (result truncated to 3000 chars).
       - Appends assistant response and RESULT:\n{result_str} as user turn
       to message history.

       If DONE matched (lines 232-241):
       - Yields {"type": "message", "content": final_text}.
       - Yields {"type": "done", "stats": {"files_changed": [...],
       ...git_diff_stats}}.
       - Returns.

       If neither (lines 243-250): Treats entire response as final answer;
       yields message + done.

       On step limit (lines 252-254): Yields {"type": "error", "content":
       "Reached max steps (N)"} then {"type": "done", ...}.

       Tool Dispatcher (lines 258-289)

       def _dispatch(self, tool: str, args: dict, project_dir: str) -> str:
       Routes: list_directory, read_file, write_file, run_command,
       search_files, mcp_call.

       For mcp_call (lines 273-288):
       - Lazy-imports MCPBridge.
       - Retrieves the singleton _mcp_bridge from
       sys.modules["open_codex.api"]._mcp_bridge.
       - Calls bridge.call(server_id, mcp_tool, params, project_dir).
       - Returns result["result"] or result["error"].

       Full SSE Event Type Taxonomy

       ┌───────────────┬─────────────────────────────┐
       │     Type      │           Fields            │
       ├───────────────┼─────────────────────────────┤
       │ start         │ prompt                      │
       ├───────────────┼─────────────────────────────┤
       │ thinking      │ (none)                      │
       ├───────────────┼─────────────────────────────┤
       │ thinking_text │ content                     │
       ├───────────────┼─────────────────────────────┤
       │ tool_call     │ tool, args                  │
       ├───────────────┼─────────────────────────────┤
       │ tool_result   │ tool, result                │
       ├───────────────┼─────────────────────────────┤
       │ file_changed  │ path                        │
       ├───────────────┼─────────────────────────────┤
       │ message       │ content                     │
       ├───────────────┼─────────────────────────────┤
       │ done          │ stats: {files_changed, ...} │
       ├───────────────┼─────────────────────────────┤
       │ error         │ content                     │
       ├───────────────┼─────────────────────────────┤
       │ aborted       │ stream_id                   │
       └───────────────┴─────────────────────────────┘

       ---
       2. mcp_servers.py — Native MCP Server Implementations

       File: /Users/arcsillc/Downloads/ocodx-main
       4/src/open_codex/mcp_servers.py

       _register_tool Pattern

       Defined in NativeMCPServer (in mcp_bridge.py, line 127):
       def _register_tool(self, name: str, fn: Callable, tool: MCPTool):
           self._dispatch[name] = fn
           self.tools.append(tool)
       Every call adds the handler function to self._dispatch dict and
       appends an MCPTool descriptor to self.tools. The call() method on
       NativeMCPServer (line 131) does:
       def call(self, tool: str, params: Dict[str, Any], project_dir: str =
        ".") -> str:
           fn = self._dispatch.get(tool)
           if fn is None:
               return f"ERROR: Unknown tool '{tool}' on server '{self.id}'"
           return fn(params, project_dir)

       All five native servers use this pattern. Tool handlers all have
       signature: def _tool_name(self, params: Dict, project_dir: str) ->
       str.

       Five Native Servers (lines 28-506)

       Class: FilesystemMCPServer
       id: "filesystem"
       Tool count: 10
       Tools: read_file, write_file, append_file, list_dir, tree,
       search_files,
         move_file, copy_file, delete_file, make_dir
       ────────────────────────────────────────
       Class: GitMCPServer
       id: "git"
       Tool count: 8
       Tools: git_status, git_log, git_diff, git_branch, git_checkout,
       git_commit,
         git_push, git_pull
       ────────────────────────────────────────
       Class: ShellMCPServer
       id: "shell"
       Tool count: 5
       Tools: run, run_piped, which, env, ps
       ────────────────────────────────────────
       Class: FetchMCPServer
       id: "fetch"
       Tool count: 4
       Tools: fetch_url, extract_links, download_file, get_headers
       ────────────────────────────────────────
       Class: SQLiteMCPServer
       id: "sqlite"
       Tool count: 6
       Tools: query, execute, schema, tables, create_table, export_csv

       Factory function at line 497:
       def build_native_servers() -> list:
           return [FilesystemMCPServer(), GitMCPServer(), ShellMCPServer(),
        FetchMCPServer(), SQLiteMCPServer()]

       ---
       3. mcp_bridge.py — Bridge Registry and Dispatch

       File: /Users/arcsillc/Downloads/ocodx-main
       4/src/open_codex/mcp_bridge.py

       MCPTool Dataclass (lines 40-44)

       @dataclass
       class MCPTool:
           name: str
           description: str
           parameters: Dict[str, Any]
           server_id: str = ""

       MCPServer Dataclass (lines 48-62)

       @dataclass
       class MCPServer:
           id: str
           name: str
           category: str
           icon: str
           description: str
           tools: List[MCPTool] = field(default_factory=list)
           healthy: bool = False
           config: Dict[str, str] = field(default_factory=dict)

       MCPBridge Class (lines 69-115)

       def __init__(self):
           self._servers: Dict[str, MCPServer] = {}

       def register(self, server: MCPServer):           # key: server.id
       def get(self, server_id: str) -> Optional[MCPServer]:
       def all_servers(self) -> List[MCPServer]:        # runs
       health_check() on each
       def call(self, server_id, tool, params, project_dir=".") ->
       Dict[str, Any]:
       def configure(self, server_id, config: Dict[str, str]):  # merges
       config dict
       def tool_manifest(self) -> List[Dict]:           # flat list of all
       tools

       call() return shape (line 94):
       {"result": result, "error": None, "tool": tool, "server": server_id}
       # or on error:
       {"error": str(exc), "result": None, "tool": tool, "server":
       server_id}

       The singleton _mcp_bridge is created at api.py line 31 and is the
       only instance. The JoomlaMCPServer (also in mcp_bridge.py, lines
       145-637) is a non-native server that dispatches via its own call()
       method using httpx for Joomla REST calls and direct AI SDK calls for
        AI tools. It does NOT use _register_tool/NativeMCPServer.

       ---
       4. api.py — SLM_AGENTS/SLM_PHASES Data Structure

       File: /Users/arcsillc/Downloads/ocodx-main 4/src/open_codex/api.py

       SLM_AGENTS (lines 380-468)

       A plain Python list of dicts. Each agent dict has exactly 4 fields:

       {
           "coord":      str,   # e.g. "ARC-01"   — cluster prefix +
       sequence number
           "cluster":    str,   # e.g. "Architecture Core"
           "name":       str,   # e.g. "Principal Backend Systems
       Architect"
           "keyword":    str,   # e.g.
       "/principal-backend-systems-architect"
           "brilliance": str,   # e.g. "Scale-first orchestration"
       }

       There are 77 agents total across 15 clusters: Architecture Core
       (10), Language Excellence (8), Cloud & Platform (5), Operations &
       Reliability (8), AI & Data Systems (6), Quality/Security/Performance
        (8), Business & Finance (3), Revenue & Sales (3), Modernization &
       Legacy (7), Engineering Systems (4), Data Intelligence (5),
       Reliability Engineering (4), Growth & Lifecycle (4), Governance &
       Risk (4), Experience Design (4), Product Strategy (4).

       SLM_PHASES (lines 470-519)

       A list of 6 phase dicts:
       {
           "id":          str,   # e.g. "phase-1"
           "name":        str,   # e.g. "Architecture Initialization"
           "description": str,
           "chain":       List[str],  # coord IDs, e.g. ["ARC-01",
       "ARC-02", "ARC-09", "ARC-10"]
           "prompt":      str,   # the prompt text injected when this phase
        fires
           "phase_num":   int,   # 1-6
       }

       /api/slm/agents endpoint (lines 522-538)

       @app.get("/api/slm/agents")
       async def get_slm_agents(cluster: str = None, search: str = None):
       - Optional query params: cluster (case-insensitive exact match on
       cluster field) and search (substring match on name, coord, or
       brilliance).
       - Returns: {"agents": [...], "clusters": {cluster_name:
       [agents...]}, "total": int}.

       /api/slm/phases endpoint (lines 541-544)

       @app.get("/api/slm/phases")
       async def get_slm_phases():
           return {"phases": SLM_PHASES}

       ---
       5. /api/chat/stream — Full Wire-Up (lines 770-848)

       Request Model (lines 203-214)

       class ChatStreamRequest(BaseModel):
           message: str
           project_dir: str
           agent_type: str          # "phi" | "lmstudio" | "ollama" |
       "ollama_cloud" | "gemini"
                                    # OR terminal: "claude_code" |
       "gemini_cli" | "codex" | "openclaw"
           model: Optional[str] = None
           host: Optional[str] = None
           api_key: Optional[str] = None
           thread_id: Optional[str] = None
           slm_context: Optional[str] = None   # SLM-v3 role preamble
       injected by matrix panel
           max_steps: Optional[int] = 25

       Endpoint Flow (lines 770-848)

       @app.post("/api/chat/stream")
       async def chat_stream(req: ChatStreamRequest):

       1. Validates project_dir exists (line 773).
       2. Creates stream_id = str(uuid.uuid4()) and stop_event =
       threading.Event() (lines 776-778). Registers in _active_streams dict
        (line 778).
       3. Creates asyncio.Queue for thread-safe producer/consumer bridging
       (line 781).
       4. Defines run_agent() function to run in a background thread (line
       783).

       Inside run_agent(), branching on agent_type:

       Terminal agents (line 785): _TERMINAL_AGENT_TYPES = {"claude_code",
       "gemini_cli", "codex", "openclaw"} (line 754)
       - If slm_context present, prepends it to the prompt: "[SLM-v3 ROLE
       CONTEXT]\n{slm_context}\n\n[USER REQUEST]\n{message}" (lines
       789-793).
       - Calls run_terminal_agent(req.agent_type, effective_prompt,
       req.project_dir) — yields events.

       Standard LLM agents (line 803):
       - Calls AgentBuilder.get_llm_caller(req.agent_type, req.model,
       req.host, req.api_key) → returns a Callable[[list], str].
       - If slm_context present, prepends it to req.message (lines
       808-811).
       - Instantiates CodingAgent(caller) (line 814).
       - Calls agent.run(effective_message, req.project_dir,
       max_steps=req.max_steps) (line 815) — a generator.
       - On each event: checks stop_event, then pushes JSON to queue via
       loop.call_soon_threadsafe(queue.put_nowait, json.dumps(event)) (line
        822).
       - On exception: pushes {"type": "error", "content": str(e)} (lines
       823-827).
       - On completion: pops stream_id from _active_streams, pushes None
       sentinel (lines 828-830).

       5. Starts a daemon thread: threading.Thread(target=run_agent,
       daemon=True).start() (line 833).
       6. generate() async generator (lines 835-842):
         - First yields data: {"type": "stream_id", "stream_id":
       stream_id}\n\n.
         - Then loops: item = await queue.get() — breaks on None, else
       yields data: {item}\n\n.
       7. Returns StreamingResponse(generate(),
       media_type="text/event-stream", headers={"Cache-Control":
       "no-cache", "X-Accel-Buffering": "no"}) (lines 844-848).

       Abort endpoint (lines 851-858):
       @app.post("/api/chat/abort/{stream_id}")
       async def abort_stream(stream_id: str):
           event = _active_streams.get(stream_id)
           event.set()
           return {"status": "abort_requested", "stream_id": stream_id}

       ---
       6. Agent Persistence / Storage

       There is NO persistence layer for custom agents. The SLM_AGENTS list
        is a hardcoded Python list defined entirely in api.py (lines
       380-468). It is read-only at runtime — there are no POST/PUT/PATCH
       endpoints that write to it, and there is no AGENTS_FILE or
       equivalent on disk.

       What IS persisted on disk (~/.open_codex/):
       - projects.json — list of project records {id, path, name, git}
       (line 133).
       - threads/<project_md5>.json — per-project conversation thread
       arrays (lines 134, 170-193). Thread records are arbitrary dicts
       passed through the upsert endpoint.

       The DATA_DIR = os.path.expanduser("~/.open_codex") is the entire
       persistence root (line 132). There is no agents storage file, no
       database, and no migration layer. Custom agent types cannot be added
        at runtime through any API endpoint.

       ---
       7. AgentBuilder.get_llm_caller — How LLM Callers Are Constructed

       File: /Users/arcsillc/Downloads/ocodx-main
       4/src/open_codex/agent_builder.py

       @staticmethod
       def get_llm_caller(
           agent_type: str,
           model: Optional[str],
           host: Optional[str],
           api_key: Optional[str] = None,
       ) -> Callable[[list], str]:
       (line 68)

       Returns agent._generate_completion for lmstudio, ollama,
       ollama_cloud, gemini. For phi, it wraps Phi4MiniAgent in a closure.
       The returned callable accepts OpenAI-format list[dict] messages and
       returns a str.

       Key detail: _sanitize_ollama_host() (line 6) strips /api or /api/
       suffixes from Ollama host URLs to prevent the SDK from building
       double-path /api/api/chat.
  ⎿  Done (15 tool uses · 62.7k tokens · 2m 12s)

                                              11:33 AM claude-sonnet-4-6
⏺ Now I have the full picture. Let me read the system prompt builder before
  designing the Gym:

⏺ Read(/Users/arcsillc/Downloads/ocodx-main
  4/src/open_codex/agents/coding_agent.py)
  ⎿  Read 306 lines

⏺ Read(/Users/arcsillc/Downloads/ocodx-main 4/src/open_codex/mcp_bridge.py ·
  lines 110-154)
  ⎿  Read 45 lines

⏺ Read(/Users/arcsillc/Downloads/ocodx-main 4/src/open_codex/api.py · lines
  18-47)
  ⎿  Read 30 lines

⏺ Bash(grep -n
  "build_native_servers\|_mcp_bridge.register\|_joomla_server\|build_yootheme"
  "/Users/arcsillc/Downloads/ocodx-main 4/src/open_codex/api.py" | head -20)
  ⎿  24:from open_codex.mcp_servers import build_native_servers
     25:from open_codex.mcp_servers_yoo import build_yootheme_server
     34:_joomla_server = JoomlaMCPServer(
     71:_mcp_bridge.register(_joomla_server)
     74:_yoo_server = build_yootheme_server(config={
     98:_mcp_bridge.register(_yoo_server)
     101:for _srv in build_native_servers():
     102:    _mcp_bridge.register(_srv)

                                              11:36 AM claude-sonnet-4-6
⏺ Now I have everything. Let me build the full Gym system — start writing all
  files in parallel:

⏺ Write(/Users/arcsillc/Downloads/ocodx-main
       4/src/open_codex/mcp_servers_gym.py)
  ⎿  Wrote 378 lines to /Users/arcsillc/Downloads/ocodx-main
     4/src/open_codex/mcp_servers_gym.py

⏺ Write(/Users/arcsillc/Downloads/ocodx-main
       4/src/open_codex/agents/gym_agent.py)
  ⎿  Wrote 256 lines to /Users/arcsillc/Downloads/ocodx-main
     4/src/open_codex/agents/gym_agent.py


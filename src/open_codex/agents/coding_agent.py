"""
Agentic coding agent with a ReAct-style tool loop.

The LLM iteratively calls tools (read/write files, run commands, search)
to fulfill the user's request, then signals completion with DONE.
"""

import json
import re
import os
import itertools
import subprocess
from typing import Callable, Generator

from open_codex.tools import file_tools, git_tools


# ── Tool definitions ─────────────────────────────────────────────────────────

TOOLS_DOC = """
AVAILABLE TOOLS:

list_directory  List files/folders in a directory
  args: {"path": "relative path, use '.' for project root"}

read_file       Read a file's contents
  args: {"path": "relative path"}

edit_file       Patch an existing file — replace an exact string with a new one
  args: {"path": "relative path", "old_string": "exact text to find", "new_string": "replacement text"}
  Optional: {"replace_all": true}  — replace every occurrence instead of just the first
  Rules: old_string must be unique in the file (add more context if not). Never truncate.

write_file      Create a new file, or fully overwrite when >50% of content changes
  args: {"path": "relative path", "content": "complete file content"}

run_command     Execute a shell command in the project directory
  args: {"command": "command string"}

search_files    Full-text search across all project files
  args: {"query": "text to find", "path": "optional subdirectory, default '.'"}

mcp_call        Call any registered MCP server tool
  args: {"server": "server_id", "tool": "tool_name", "params": {...}}

  Joomla CMS Server (server: "joomla") — Articles, categories, modules, menus
    {"server": "joomla", "tool": "create_article",          "params": {"article_text": "...", "category_id": 8}}
    {"server": "joomla", "tool": "generate_article",        "params": {"topic": "...", "ai_service": "gemini"}}
    {"server": "joomla", "tool": "enhance_article",         "params": {"content": "...", "enhancement_type": "improve_readability"}}
    {"server": "joomla", "tool": "create_ai_article_and_publish", "params": {"topic": "...", "ai_service": "ollama"}}

  YOOtheme Builder Server (server: "yootheme") — Full YOOtheme Pro page builder agent
    YOO Layout JSON: {"type":"layout","version":"4.5.33","children":[{"type":"section","props":{"style":"default|muted|primary|secondary","name":"Hero"},"children":[{"type":"row","props":{"gutter":"medium"},"children":[{"type":"column","props":{"width_bp":"1-1"},"children":[{"type":"headline","props":{"content":"Title","title_element":"h1"}},{"type":"text","props":{"content":"<p>Body</p>"}},{"type":"button","props":{"content":"CTA","link":"#","button_style":"primary"}}]}]}]}]}
    Layouts are stored in Joomla article introtext as: <!--{"type":"layout",...}-->

    AI Layout Generation:
      {"server": "yootheme", "tool": "yoo_generate_page",   "params": {"request": "Landing page for a plumbing company", "sections": ["hero","features","contact"]}}
      {"server": "yootheme", "tool": "yoo_add_section",     "params": {"section_type": "hero", "description": "Blue background, bold white headline, CTA button"}}
      {"server": "yootheme", "tool": "yoo_compose_layout",  "params": {"topic": "Photography studio", "sections": ["hero","gallery","pricing","contact"]}}
      {"server": "yootheme", "tool": "yoo_image_to_layout", "params": {"url": "https://example.com", "description": "Corporate site with hero and 3 features"}}

    Layout Engine (CRUD on JSON tree with undo/redo):
      {"server": "yootheme", "tool": "yoo_get_layout_json",  "params": {"session_id": "my-page"}}
      {"server": "yootheme", "tool": "yoo_remove_section",   "params": {"index": 2}}
      {"server": "yootheme", "tool": "yoo_move_section",     "params": {"from_index": 0, "to_index": 2}}
      {"server": "yootheme", "tool": "yoo_update_element",   "params": {"path": [0,0,0,0], "props": {"content": "New Headline"}}}
      {"server": "yootheme", "tool": "yoo_undo",             "params": {}}
      {"server": "yootheme", "tool": "yoo_validate_layout",  "params": {}}

    Save to Joomla (REST or MySQL):
      {"server": "yootheme", "tool": "yoo_set_layout",            "params": {"article_id": 42}}
      {"server": "yootheme", "tool": "yoo_mysql_write_layout",    "params": {"article_id": 42}}
      {"server": "yootheme", "tool": "yoo_read_layout_from_article","params": {"article_id": 42}}
      {"server": "yootheme", "tool": "yoo_list_articles_with_layouts", "params": {"limit": 30}}
      {"server": "yootheme", "tool": "yoo_mysql_list_articles",   "params": {"only_with_layouts": true}}

    All AI tools accept ai_service: ollama | ollama_cloud | lmstudio | gemini
    All layout tools accept session_id (default: "default") for multi-page workflows

  Native Servers:
    {"server": "git",    "tool": "git_commit",    "params": {"message": "feat: add X"}}
    {"server": "fetch",  "tool": "fetch_url",    "params": {"url": "https://example.com"}}
    {"server": "sqlite", "tool": "query",        "params": {"db": "data.db", "sql": "SELECT * FROM users"}}
"""

ACTION_RE = re.compile(r'^ACTION:\s*(\{.+\})\s*$', re.MULTILINE)
DONE_RE   = re.compile(r'^DONE:\s*(.+)', re.MULTILINE | re.DOTALL)
THINK_RE  = re.compile(r'<think>(.*?)</think>', re.DOTALL)

# Matches fenced code blocks: ```lang\n<content>\n```
_FENCE_RE = re.compile(r'```([a-zA-Z0-9_+-]*)\n([\s\S]+?)```', re.MULTILINE)

_LANG_EXT = {
    "html": ".html", "htm": ".html",
    "javascript": ".js", "js": ".js", "typescript": ".ts", "ts": ".ts",
    "jsx": ".jsx", "tsx": ".tsx",
    "python": ".py", "py": ".py",
    "css": ".css", "scss": ".scss", "sass": ".sass",
    "json": ".json", "yaml": ".yaml", "yml": ".yml",
    "go": ".go", "rust": ".rs", "c": ".c", "cpp": ".cpp",
    "sh": ".sh", "bash": ".sh", "shell": ".sh",
    "sql": ".sql", "lua": ".lua", "gdscript": ".gd",
}


def _infer_filename(lang: str, prose_before: str, existing_names: set[str]) -> str:
    """Infer a file path from language hint and surrounding prose."""
    ext = _LANG_EXT.get(lang.lower(), f".{lang.lower()}" if lang else ".txt")

    # Look for a quoted filename in the prose immediately before the block
    for pattern in (
        r'[`"\']([^\s`"\']+\.[a-zA-Z0-9]+)[`"\']',   # `foo.html` or "foo.js"
        r'\b([\w.-]+' + re.escape(ext) + r')\b',        # bare word matching ext
    ):
        m = re.search(pattern, prose_before[-300:])
        if m:
            name = m.group(1).lstrip('/').lstrip('./')
            if '/' not in name or name.count('/') <= 3:
                return name

    # Default name: index for html/js roots, main otherwise
    base = "index" if ext in (".html", ".js", ".ts") else "main"
    candidate = base + ext
    # Avoid clobbering a name we've already written this session
    n = 2
    while candidate in existing_names:
        candidate = f"{base}_{n}{ext}"
        n += 1
    return candidate


def _extract_code_files(response: str, written: set[str]) -> list[tuple[str, str]]:
    """Return [(path, content), ...] for every substantial fenced block in response."""
    results = []
    pos = 0
    for m in _FENCE_RE.finditer(response):
        lang = (m.group(1) or "").strip()
        content = m.group(2).rstrip()
        if len(content) < 80:          # skip tiny snippets
            continue
        prose_before = response[pos:m.start()]
        path = _infer_filename(lang, prose_before, written | {p for p, _ in results})
        results.append((path, content))
        pos = m.end()
    return results


def _build_system_prompt(project_dir: str) -> str:
    name = os.path.basename(os.path.abspath(project_dir))
    git_line = ""
    if git_tools.is_git_repo(project_dir):
        status = git_tools.get_status(project_dir)
        git_line = f"\nGit branch: {status.get('branch', 'unknown')}"

    return f"""You are Open Codex — a Sovereign Liquid Matrix (SLM-v3) coding agent.
Working directory: {project_dir}
Project: {name}{git_line}

You embody a unified hive of specialist subagents operating under the
Recursive Context Mediation kernel (U1-RCM). Every response is the
synthesized output of the full matrix firing in parallel before you act.

ACTIVE SUBAGENT CLUSTERS (all fire simultaneously per step):
  ARC  [Architecture]   - Backend, Frontend, Mobile, GraphQL, API Gateway,
                          Event-Driven, Multi-Modal, Resilience, AI Integration
  LNG  [Language]       - Python, JavaScript/TypeScript, Go, Rust, C, C++, SQL
  CLD  [Cloud/Platform] - Cloud IaC, Network, Serverless, Release engineering
  OPS  [Operations]     - DevOps SRE, Incident command, DB ops & performance
  AID  [AI & Data]      - Applied AI, ML/MLOps, Data pipelines, Data science
  QSP  [Quality]        - Security audit/hardening, Code review, Debug, Perf, Test
  LEG  [Modernization]  - Context orchestration, Prompt systems, Legacy migration
  GOV  [Governance]     - Compliance, Policy, Risk assessment, Ethics & trust

INTERNAL EXECUTION PROTOCOL - U1-RCM (runs before every output):
  Phase 1 ARC  -> Blueprint the architectural approach
  Phase 2 LNG  -> Select the optimal language/toolchain pattern
  Phase 3 QSP  -> Validate safety & security; flag data loss risks
  Phase 4 OPS  -> Ensure idempotency, observability, error handling
  Phase 5 LEG  -> Update global context state (U1 mediator)
  Phase 6 GOV  -> Ethics + compliance gate
  -> EMIT: exactly one ACTION or DONE

{TOOLS_DOC}

STEP-BY-STEP EXECUTION PROTOCOL — follow this exactly:

STEP 1 — EXPLORE (always first, no exceptions):
  ACTION: {{"tool": "list_directory", "args": {{"path": "."}}}}

STEP 2 — READ ALL SOURCE FILES:
  After seeing the directory listing, read every file that contains code.
  Source files: .js .ts .py .html .css .jsx .tsx .go .rs .c .cpp .lua .gd .json .yaml
  Read them ALL before writing anything. One read_file ACTION per response.
  Example: ACTION: {{"tool": "read_file", "args": {{"path": "game.js"}}}}

STEP 3 — ACT WITH EXPERT JUDGMENT (after all files are read):
  Make real, substantive improvements — not trivial tweaks.
  Think like a senior engineer who owns this codebase.

  CHOOSING THE RIGHT WRITE TOOL:
  - Modifying an existing file → use edit_file with the exact old_string and new_string.
    Include enough surrounding lines in old_string to make it unique in the file.
    One edit_file call per logical change. Chain multiple calls for multiple changes.
  - Creating a new file → use write_file with complete content.
  - Rewriting >50% of an existing file → write_file is acceptable.

  TASK PATTERNS:
  - "enhance / improve / upgrade": patch specific sections with edit_file; don't rewrite whole files unless they are entirely new or trivially short.
  - "fix bugs": edit_file each broken section precisely — surgical, not wholesale.
  - "add X": add new code via edit_file (insert after the right anchor) or write_file for new files.
  - "refactor": use edit_file with replace_all=true for renames; write_file when structure changes completely.

STEP 4 — VERIFY:
  After writing files, run the relevant build/test/lint command if one exists.
  Example: ACTION: {{"tool": "run_command", "args": {{"command": "npm test"}}}}

STEP 5 — DONE:
  DONE: <comprehensive summary of every change made and why>

DECISION TREE — after each tool result:
  list_directory → read the first source file you see
  read_file      → if more source files remain, read the next; if all read, start patching
  edit_file      → apply next targeted patch, or run build/test if all changes done
  write_file     → same as edit_file — continue or run build/test
  run_command    → fix errors if any, otherwise output DONE

OUTPUT FORMAT — ONLY these two lines are valid output, nothing else:
  ACTION: {{"tool": "tool_name", "args": {{...}}}}
  DONE: <summary>

HARD RULES:
- ONE ACTION per response. Wait for RESULT.
- edit_file: old_string must be the EXACT text from the file — copy it character-for-character. Include enough surrounding lines to make it unique.
- write_file: content must be COMPLETE — never truncated. Only use for new files or near-total rewrites.
- Never ask questions. Never explain what you are about to do. Just do it.
- Make real, meaningful improvements. Go deep. Don't stop at the surface.
- Keep going until the FULL task is complete.
"""



# ── Coding Agent ─────────────────────────────────────────────────────────────

class CodingAgent:
    MAX_STEPS = 25

    def __init__(self, llm_caller: Callable[[list], str]):
        """
        llm_caller: callable(messages: list[dict]) -> str
        where messages follow OpenAI chat format: [{"role": "...", "content": "..."}]
        """
        self.llm_caller = llm_caller

    def run(self, prompt: str, project_dir: str, max_steps: int = None) -> Generator[dict, None, None]:
        """Yield SSE-style event dicts as the agent works."""
        project_dir = os.path.realpath(os.path.abspath(project_dir))

        messages = [
            {"role": "system", "content": _build_system_prompt(project_dir)},
            {"role": "user",   "content": prompt},
        ]

        files_changed: set[str] = set()
        yield {"type": "start", "prompt": prompt}

        limit = self.MAX_STEPS if max_steps is None else max_steps
        step_iter = itertools.count() if limit == 0 else range(limit)

        for step in step_iter:
            yield {"type": "thinking"}

            try:
                response = self.llm_caller(messages)
            except Exception as e:
                yield {"type": "error", "content": f"LLM error: {e}"}
                return

            # ── Strip <think> blocks (thinking/reasoning models) ───────────
            # Emit chain-of-thought as thinking_text events, then remove from
            # response so ACTION/DONE regexes only see the actual output.
            for think_m in THINK_RE.finditer(response):
                for line in think_m.group(1).strip().splitlines():
                    line = line.strip()
                    if line:
                        yield {"type": "thinking_text", "content": line}
            response = THINK_RE.sub("", response).strip()

            # ── Check for tool action ──────────────────────────────────────
            action_m = ACTION_RE.search(response)
            done_m   = DONE_RE.search(response)

            if action_m:
                # Strip the ACTION line from any preceding text
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

                result = self._dispatch(tool, args, project_dir)

                if tool == "mcp_call":
                    server = args.get("server", "?")
                    mcp_tool = args.get("tool", "?")
                    yield {"type": "tool_call", "tool": f"mcp:{server}.{mcp_tool}", "args": args.get("params", {})}
                if tool == "write_file" and "path" in args and not result.startswith("ERROR"):
                    files_changed.add(args["path"])
                    yield {"type": "file_changed", "path": args["path"]}

                result_str = str(result)[:3000]
                yield {"type": "tool_result", "tool": tool, "result": result_str}

                messages.append({"role": "assistant", "content": response})
                if result_str.startswith("ERROR") or result_str.startswith("[exit "):
                    recovery = (
                        f"RESULT:\n{result_str}\n\n"
                        "RECOVERY REQUIRED: That tool call failed. Do NOT repeat it unchanged.\n"
                        "Apply intelligent heuristics:\n"
                        "- Tool not found / denied → use a different available tool for the same goal\n"
                        "- Command failed → analyze the error, adjust the command or use a file tool instead\n"
                        "- MCP error → fall back to read_file / write_file / run_command equivalents\n"
                        "- Unknown tool → pick the closest matching tool from AVAILABLE TOOLS above\n"
                        "Emit your next ACTION using a working alternative approach."
                    )
                    messages.append({"role": "user", "content": recovery})
                else:
                    messages.append({"role": "user", "content": f"RESULT:\n{result_str}"})

            elif done_m:
                final = done_m.group(1).strip()

                stats: dict = {"files_changed": sorted(files_changed)}
                if git_tools.is_git_repo(project_dir):
                    stats.update(git_tools.get_diff_stats(project_dir))

                yield {"type": "message", "content": final}
                yield {"type": "done",    "stats": stats}
                return

            else:
                # Model output neither ACTION nor DONE.
                # First: rescue any fenced code blocks it included as prose and
                # write them to disk automatically — then re-prompt for DONE.
                extracted = _extract_code_files(response, files_changed)
                if extracted:
                    written_paths = []
                    for path, content in extracted:
                        result = file_tools.write_file(path, content, project_dir)
                        if not result.startswith("ERROR"):
                            files_changed.add(path)
                            written_paths.append(path)
                            yield {"type": "file_changed", "path": path}
                        yield {"type": "tool_result", "tool": "write_file",
                               "result": result[:500]}
                    recovery_msg = (
                        f"Auto-rescued: wrote {written_paths} from your prose output. "
                        "Now output:\n"
                        "  DONE: <summary of everything that was written and why>"
                    )
                    messages.append({"role": "assistant", "content": response})
                    messages.append({"role": "user", "content": recovery_msg})
                else:
                    if response.strip():
                        yield {"type": "thinking_text", "content": f"[no ACTION/DONE — re-prompting] {response[:200]}"}
                    correction = (
                        "Your last response was not valid. "
                        "You MUST output exactly one of:\n"
                        "  ACTION: {\"tool\": \"...\", \"args\": {...}}\n"
                        "  DONE: <summary>\n"
                        "Do NOT write prose or explanations. "
                        "If you have not yet explored the project, start with:\n"
                        'ACTION: {"tool": "list_directory", "args": {"path": "."}}'
                    )
                    messages.append({"role": "assistant", "content": response or "(empty)"})
                    messages.append({"role": "user",      "content": correction})
                # continue the loop — do NOT return

        if limit != 0:
            yield {"type": "error",  "content": f"Reached max steps ({limit})"}
        yield {"type": "done",   "stats": {"files_changed": sorted(files_changed)}}

    # ── Tool dispatcher ───────────────────────────────────────────────────────

    def _dispatch(self, tool: str, args: dict, project_dir: str) -> str:
        if tool == "list_directory":
            return file_tools.list_directory(args.get("path", "."), project_dir)
        if tool == "read_file":
            return file_tools.read_file(args.get("path", ""), project_dir)
        if tool == "edit_file":
            return file_tools.edit_file(
                args.get("path", ""),
                args.get("old_string", ""),
                args.get("new_string", ""),
                project_dir,
                args.get("replace_all", False),
            )
        if tool == "write_file":
            return file_tools.write_file(
                args.get("path", ""), args.get("content", ""), project_dir
            )
        if tool == "run_command":
            return self._run_command(args.get("command", ""), project_dir)
        if tool == "search_files":
            return file_tools.search_files(
                args.get("query", ""), project_dir, args.get("path", ".")
            )
        if tool == "mcp_call":
            try:
                from open_codex.mcp_bridge import MCPBridge
                # Import the singleton bridge from api (lazy, avoids circular import)
                import sys
                api_mod = sys.modules.get("open_codex.api")
                bridge = getattr(api_mod, "_mcp_bridge", None) if api_mod else None
                if bridge is None:
                    return "ERROR: MCP bridge not available in this context"
                server_id = args.get("server", "")
                mcp_tool  = args.get("tool", "")
                params    = args.get("params", {})
                result = bridge.call(server_id, mcp_tool, params, project_dir)
                return result.get("result") or result.get("error") or str(result)
            except Exception as e:
                return f"ERROR: MCP call failed: {e}"
        return f"ERROR: Unknown tool '{tool}'"

    def _run_command(self, command: str, cwd: str) -> str:
        if not command.strip():
            return "ERROR: Empty command"
        try:
            r = subprocess.run(
                command, shell=True, cwd=cwd,
                capture_output=True, text=True, timeout=60
            )
            out = "\n".join(filter(None, [r.stdout.strip(), r.stderr.strip()])) or "(no output)"
            prefix = f"[exit {r.returncode}] " if r.returncode != 0 else ""
            return (prefix + out)[:4000]
        except subprocess.TimeoutExpired:
            return "ERROR: Command timed out after 60s"
        except Exception as e:
            return f"ERROR: {e}"

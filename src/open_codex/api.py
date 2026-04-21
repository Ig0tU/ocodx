import os
import json
import hashlib
import logging
import subprocess
import threading
import asyncio
from typing import List, Optional

logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from open_codex.agent_builder import AgentBuilder
from open_codex.tools import file_tools, git_tools

# ── MCP Bridge — Sovereign Liquid Matrix tool layer ───────────────────────────
from open_codex.mcp_bridge import MCPBridge
from open_codex.mcp_bridge import JoomlaMCPServer
from open_codex.mcp_servers import build_native_servers
from open_codex.mcp_servers_yoo import build_yootheme_server
from open_codex.mcp_servers_gym import GymMCPServer, load_custom_agents, load_custom_clusters, load_scenarios
from open_codex.mcp_servers_cryptkeeper import (
    CryptKeeperMCPServer,
    env_set, env_delete, env_list_names,
    list_requests, dismiss_request, deny_request,
)
from open_codex.mcp_servers_repo import (
    add_repo, remove_repo, reload_all as _repo_reload_all, list_repos,
)
import open_codex.mcp_autopilot as _autopilot

_JOOMCPLA_SCRIPT = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "joomcpla-main", "main.py"
)

_mcp_bridge = MCPBridge()

# Register Joomla MCP server — config seeded from env, overridable via MCP Hub UI
_joomla_server = JoomlaMCPServer(
    script_path=_JOOMCPLA_SCRIPT,
    config={
        # Joomla REST API credentials
        "JOOMLA_BASE_URL":        os.getenv("JOOMLA_BASE_URL", ""),
        "BEARER_TOKEN":           os.getenv("JOOMLA_BEARER_TOKEN", ""),

        # Default AI provider: ollama | ollama_cloud | lmstudio | gemini | huggingface
        "AI_PROVIDER":            os.getenv("JOOMLA_AI_PROVIDER", "gemini"),

        # ── Ollama LOCAL ──────────────────────────────────────────────────────
        # Uses local Ollama daemon. Auth is optional (for protected servers).
        # Models: whatever you have pulled (ollama pull llama3, etc.)
        "OLLAMA_HOST":            os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        "OLLAMA_MODEL":           os.getenv("OLLAMA_MODEL", "llama3"),
        "OLLAMA_API_KEY":         os.getenv("OLLAMA_API_KEY", ""),          # optional

        # ── Ollama CLOUD ──────────────────────────────────────────────────────
        # Separate credentials — host is always https://ollama.com (per docs)
        # Get key: https://ollama.com/settings/keys
        # Models: cloud tags e.g. gpt-oss:120b, llama4:scout
        "OLLAMA_CLOUD_API_KEY":   os.getenv("OLLAMA_CLOUD_API_KEY", ""),    # required
        "OLLAMA_CLOUD_MODEL":     os.getenv("OLLAMA_CLOUD_MODEL", "gpt-oss:120b"),

        # ── LM Studio ────────────────────────────────────────────────────────
        # OpenAI-compatible REST API served by LM Studio locally
        "LMSTUDIO_HOST":          os.getenv("LMSTUDIO_HOST", "http://localhost:1234"),
        "LMSTUDIO_MODEL":         os.getenv("LMSTUDIO_MODEL", "local-model"),

        # ── Google Gemini ─────────────────────────────────────────────────────
        "GEMINI_API_KEY":         os.getenv("GEMINI_API_KEY", ""),
        "GEMINI_MODEL":           os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),

        # ── HuggingFace ───────────────────────────────────────────────────────
        "HUGGINGFACE_API_TOKEN":  os.getenv("HUGGINGFACE_API_TOKEN", ""),
    },
)
_mcp_bridge.register(_joomla_server)

# Register YOOtheme Builder MCP server — shares AI provider config with Joomla server
_yoo_server = build_yootheme_server(config={
    # AI providers (shared with Joomla server)
    "AI_PROVIDER":            os.getenv("JOOMLA_AI_PROVIDER", "gemini"),
    "OLLAMA_HOST":            os.getenv("OLLAMA_HOST", "http://localhost:11434"),
    "OLLAMA_MODEL":           os.getenv("OLLAMA_MODEL", "llama3"),
    "OLLAMA_API_KEY":         os.getenv("OLLAMA_API_KEY", ""),
    "OLLAMA_CLOUD_API_KEY":   os.getenv("OLLAMA_CLOUD_API_KEY", ""),
    "OLLAMA_CLOUD_MODEL":     os.getenv("OLLAMA_CLOUD_MODEL", "gpt-oss:120b"),
    "LMSTUDIO_HOST":          os.getenv("LMSTUDIO_HOST", "http://localhost:1234"),
    "LMSTUDIO_MODEL":         os.getenv("LMSTUDIO_MODEL", "local-model"),
    "GEMINI_API_KEY":         os.getenv("GEMINI_API_KEY", ""),
    "GEMINI_MODEL":           os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
    # Joomla REST (for REST-based layout r/w)
    "JOOMLA_BASE_URL":        os.getenv("JOOMLA_BASE_URL", ""),
    "BEARER_TOKEN":           os.getenv("JOOMLA_BEARER_TOKEN", ""),
    # MySQL direct (for layout injection bypassing REST)
    # prefix: YOOMYSQL_ — all optional, enables direct DB layout surgery
    "YOOMYSQL_HOST":          os.getenv("YOOMYSQL_HOST", ""),
    "YOOMYSQL_PORT":          os.getenv("YOOMYSQL_PORT", "3306"),
    "YOOMYSQL_USER":          os.getenv("YOOMYSQL_USER", ""),
    "YOOMYSQL_PASSWORD":      os.getenv("YOOMYSQL_PASSWORD", ""),
    "YOOMYSQL_DATABASE":      os.getenv("YOOMYSQL_DATABASE", ""),
    "YOOMYSQL_PREFIX":        os.getenv("YOOMYSQL_PREFIX", "jos_"),
})
_mcp_bridge.register(_yoo_server)

# Register all native MCP servers
for _srv in build_native_servers():
    _mcp_bridge.register(_srv)

# Register the SLM Gym Forge server
_gym_server = GymMCPServer()
_mcp_bridge.register(_gym_server)

# Register the CryptKeeper secret management server
_cryptkeeper_server = CryptKeeperMCPServer(_mcp_bridge)

# Re-register any previously saved Repo→MCP servers
_repo_reload_all(_mcp_bridge)

# Restore autopilot state from disk (re-enable loop if it was on)
_autopilot_config = {
    "AI_PROVIDER":    os.getenv("JOOMLA_AI_PROVIDER", "ollama"),
    "OLLAMA_HOST":    os.getenv("OLLAMA_HOST", "http://localhost:11434"),
    "OLLAMA_MODEL":   os.getenv("OLLAMA_MODEL", "llama3"),
    "LMSTUDIO_HOST":  os.getenv("LMSTUDIO_HOST", "http://localhost:1234"),
    "LMSTUDIO_MODEL": os.getenv("LMSTUDIO_MODEL", "local-model"),
    "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY", ""),
    "GEMINI_MODEL":   os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
}

app = FastAPI(title="Open Codex API", version="0.1.18")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

# ── CSP header (fixes Opera/Chrome blocking Vite bundle eval) ─────────────────

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

class CSPMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "connect-src 'self' http://localhost:* ws://localhost:*; "
            "img-src 'self' data: blob: *; "
            "font-src 'self' data: https://fonts.gstatic.com;"
        )
        return response

app.add_middleware(CSPMiddleware)

# ── Storage paths ─────────────────────────────────────────────────────────────

DATA_DIR     = os.path.expanduser("~/.open_codex")
PROJECTS_FILE = os.path.join(DATA_DIR, "projects.json")
THREADS_DIR   = os.path.join(DATA_DIR, "threads")


def _ensure_dirs():
    os.makedirs(DATA_DIR,    exist_ok=True)
    os.makedirs(THREADS_DIR, exist_ok=True)


def _project_id(path: str) -> str:
    return hashlib.md5(os.path.realpath(path).encode()).hexdigest()[:8]


def _load_projects() -> list:
    _ensure_dirs()
    if not os.path.exists(PROJECTS_FILE):
        return []
    try:
        with open(PROJECTS_FILE) as f:
            content = f.read().strip()
            if not content:
                return []
            return json.loads(content)
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"Failed to load projects: {e}")
        return []


def _save_projects(projects: list):
    _ensure_dirs()
    try:
        with open(PROJECTS_FILE, "w") as f:
            json.dump(projects, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save projects: {e}")


def _threads_file(project_path: str) -> str:
    pid = _project_id(project_path)
    return os.path.join(THREADS_DIR, f"{pid}.json")


def _load_threads(project_path: str) -> list:
    _ensure_dirs()
    tf = _threads_file(project_path)
    if not os.path.exists(tf):
        return []
    try:
        with open(tf) as f:
            content = f.read().strip()
            if not content:
                return []
            return json.loads(content)
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"Failed to load threads for {project_path}: {e}")
        return []


def _save_threads(project_path: str, threads: list):
    _ensure_dirs()
    with open(_threads_file(project_path), "w") as f:
        json.dump(threads, f, indent=2)


# ── Pydantic models ───────────────────────────────────────────────────────────

class AddProjectRequest(BaseModel):
    path: str
    name: Optional[str] = None

class ChatStreamRequest(BaseModel):
    message: str
    project_dir: str
    # phi | lmstudio | ollama | ollama_cloud | gemini
    # terminal: claude_code | gemini_cli | codex | openclaw
    agent_type: str
    model: Optional[str] = None
    host: Optional[str] = None
    api_key: Optional[str] = None
    thread_id: Optional[str] = None
    slm_context: Optional[str] = None  # SLM-v3 role preamble injected by matrix panel
    max_steps: Optional[int] = 25
    team_mode: bool = False  # SLM multi-agent swarm mode

class CommitRequest(BaseModel):
    project_dir: str
    message: str

class PushPullRequest(BaseModel):
    project_dir: str
    remote: str = 'origin'
    branch: str = ''

class ThreadUpsertRequest(BaseModel):
    project_dir: str
    thread: dict

class GenerateRequest(BaseModel):
    prompt: str
    agent_type: str
    model: Optional[str] = None
    host: Optional[str] = None
    api_key: Optional[str] = None

class ExecuteRequest(BaseModel):
    command: str
    cwd: Optional[str] = None

class DeleteMessageRequest(BaseModel):
    project_dir: str
    thread_id: str
    message_index: int   # 0-based index into thread["messages"]



@app.get("/api/config")
async def get_config():
    return {
        "version": "0.1.18",
        "platform": os.name,
        "cwd": os.getcwd(),
        "default_agent": "ollama",
        "lmstudio_host": "http://localhost:1234",
        "ollama_host": "http://localhost:11434",
    }


@app.on_event("startup")
async def startup_event():
    _ensure_dirs()
    cwd = os.getcwd()
    projects = _load_projects()
    pid = _project_id(cwd)
    if not any(p["id"] == pid for p in projects):
        name = os.path.basename(cwd) or "root"
        git = git_tools.is_git_repo(cwd)
        projects.append({"id": pid, "path": cwd, "name": name, "git": git})
        _save_projects(projects)


@app.get("/api/automations")
async def list_automations():
    """Return all available automations grouped by category."""
    return [
        # ── Code Quality ───────────────────────────────
        {
            "id": "auto-fix", "name": "Auto-Fix", "category": "Code Quality", "icon": "🔧",
            "description": "Scan and auto-fix linting, formatting, and style issues across the entire project.",
            "browser": False,
            "task_template": (
                "▶ Q3 · Code Reviewer + Q6 · Perf Engineer active.\n\n"
                "Run a full lint, format, and style sweep on this project and fix every issue found.\n\n"
                "STEP 1 — Detect project type: read package.json / pyproject.toml / go.mod / Cargo.toml / composer.json.\n"
                "STEP 2 — Read any lint config files (.eslintrc, .prettierrc, ruff.toml, .flake8, .golangci.yml).\n"
                "STEP 3 — Run the appropriate auto-fix commands:\n"
                "  Node/TS: npx eslint --fix . && npx prettier --write .\n"
                "  Python:  ruff check --fix . && ruff format .  (fallback: black . && isort .)\n"
                "  Go:      gofmt -w . && golangci-lint run --fix\n"
                "  Rust:    cargo fmt && cargo clippy --fix --allow-dirty\n"
                "  PHP:     ./vendor/bin/php-cs-fixer fix .\n"
                "STEP 4 — Run the linter again to verify zero remaining errors.\n"
                "STEP 5 — If any files still have unfixable issues, edit_file them directly.\n"
                "DONE: List every file changed, issues fixed, and any remaining manual items."
            ),
        },
        {
            "id": "gen-tests", "name": "Gen Tests", "category": "Code Quality", "icon": "✅",
            "description": "Generate comprehensive unit and integration tests for all new functions and modules.",
            "browser": False,
            "task_template": (
                "▶ Q1 · Security Auditor + Q3 · Code Reviewer active.\n\n"
                "Generate comprehensive tests for every untested function and module in this project.\n\n"
                "STEP 1 — list_directory to discover all source files.\n"
                "STEP 2 — Detect test framework: look for jest.config.*, pytest.ini, go.mod (go test), vitest.config.*.\n"
                "STEP 3 — Read each source file. For every exported function/class/route, write tests covering:\n"
                "  • Happy path with realistic inputs\n"
                "  • Edge cases: empty, null/None, boundary values, large inputs\n"
                "  • Error paths: invalid input, missing deps, permission errors\n"
                "  • Integration tests for any HTTP routes (use supertest/httpx/net/http/test)\n"
                "STEP 4 — write_file each test file alongside its source (e.g. src/foo.ts → src/foo.test.ts).\n"
                "STEP 5 — run_command to execute the test suite and fix any failures.\n"
                "DONE: Summary of test files created, functions covered, and overall coverage estimate."
            ),
        },
        {
            "id": "security-scan", "name": "Security Scan", "category": "Code Quality", "icon": "🛡️",
            "description": "Run SAST, dependency vulnerability scan, and secrets detection with remediation plan.",
            "browser": False,
            "task_template": (
                "▶ Q1 · Security Auditor active.\n\n"
                "Perform a full security audit of this project: SAST, dependency CVEs, and secrets detection.\n\n"
                "STEP 1 — Detect language/stack from project files.\n"
                "STEP 2 — Run dependency vulnerability scan:\n"
                "  Node: npm audit --json\n"
                "  Python: pip-audit --format json  (fallback: safety check)\n"
                "  Go: govulncheck ./...\n"
                "  Rust: cargo audit\n"
                "STEP 3 — Scan for hardcoded secrets: search_files for patterns like 'api_key', 'secret', 'password', 'token', 'BEGIN RSA', 'sk-' across all source files.\n"
                "STEP 4 — Read all route handlers, input parsers, and DB query files. Look for:\n"
                "  • SQL injection (string-concatenated queries)\n"
                "  • XSS (unescaped user input rendered to HTML)\n"
                "  • Insecure deserialization, path traversal, SSRF\n"
                "  • Missing auth/authz checks on sensitive routes\n"
                "STEP 5 — For each finding: edit_file to apply the fix or add a // SECURITY: comment with the remediation.\n"
                "STEP 6 — write_file SECURITY_REPORT.md with: severity-ranked findings, CVEs, remediation status.\n"
                "DONE: Summary of vulnerabilities found, fixed, and remaining."
            ),
        },
        {
            "id": "perf-profile", "name": "Perf Profile", "category": "Code Quality", "icon": "⚡",
            "description": "Profile CPU/memory hotspots and emit a prioritized optimization backlog.",
            "browser": False,
            "task_template": (
                "▶ Q6 · Perf Engineer active.\n\n"
                "Profile this project for CPU and memory hotspots and produce a prioritized optimization backlog.\n\n"
                "STEP 1 — Read all source files to identify hot paths: loops, DB queries, file I/O, network calls.\n"
                "STEP 2 — Run profiling where possible:\n"
                "  Python: python -m cProfile -o profile.out main.py  (or pytest --profile)\n"
                "  Node: node --prof index.js  then node --prof-process\n"
                "  Go: go test -bench=. -benchmem ./...\n"
                "  Rust: cargo bench\n"
                "STEP 3 — Analyze each hot path for:\n"
                "  • N+1 query patterns (loop + individual DB fetch)\n"
                "  • Missing indexes on frequently-filtered columns\n"
                "  • Redundant re-computation (add memoization/caching)\n"
                "  • Synchronous blocking I/O that should be async\n"
                "  • Unnecessary object allocations in tight loops\n"
                "STEP 4 — Apply the top 3 highest-impact optimizations with edit_file.\n"
                "STEP 5 — write_file PERF_BACKLOG.md with: issue, estimated impact (High/Med/Low), suggested fix, effort.\n"
                "DONE: Summary of optimizations applied and backlog items documented."
            ),
        },
        {
            "id": "arch-review", "name": "Arch Review", "category": "Code Quality", "icon": "🏗️",
            "description": "Audit project structure against SLM-v3 patterns and emit an architecture decision record.",
            "browser": False,
            "task_template": (
                "▶ A1 · Backend Architect + A5 · Architecture Quality Guardian active.\n\n"
                "Audit this project's architecture against SLM-v3 best practices and produce an ADR.\n\n"
                "STEP 1 — Map the full project structure with list_directory (recursively explore key dirs).\n"
                "STEP 2 — Read all entry points, routers, models, and service files.\n"
                "STEP 3 — Evaluate against these patterns:\n"
                "  • Separation of concerns (controllers vs services vs data layer)\n"
                "  • Dependency injection / inversion of control\n"
                "  • Error boundary placement and propagation\n"
                "  • Config/secret management (no hardcoded values)\n"
                "  • Logging and observability (structured logs, trace IDs)\n"
                "  • API contract consistency (versioning, error shapes)\n"
                "  • Test pyramid alignment (unit > integration > e2e)\n"
                "STEP 4 — For each violation: suggest a concrete refactor with before/after code snippet.\n"
                "STEP 5 — write_file ARCHITECTURE_DECISION_RECORD.md with:\n"
                "  Status, Context, Decision, Consequences, and Action Items ranked by priority.\n"
                "DONE: ADR written with all findings and recommendations."
            ),
        },
        {
            "id": "dependency-audit", "name": "Dependency Audit", "category": "Code Quality", "icon": "📦",
            "description": "Check all dependencies for outdated versions, CVEs, and license conflicts.",
            "browser": False,
            "task_template": (
                "▶ Q1 · Security Auditor + O1 · DevOps SRE active.\n\n"
                "Audit all project dependencies for outdated versions, known CVEs, and license issues.\n\n"
                "STEP 1 — Read all dependency manifests: package.json, requirements.txt, pyproject.toml, go.mod, Cargo.toml.\n"
                "STEP 2 — Run outdated check:\n"
                "  Node: npm outdated --json\n"
                "  Python: pip list --outdated --format json\n"
                "  Go: go list -m -u all\n"
                "  Rust: cargo outdated\n"
                "STEP 3 — Run CVE scan (see security-scan step 2 commands).\n"
                "STEP 4 — Check licenses: for each dep, note its license (MIT/Apache/GPL/LGPL/etc).\n"
                "  Flag any GPL/AGPL deps in a commercial or proprietary codebase.\n"
                "STEP 5 — write_file DEPENDENCY_AUDIT.md with three tables:\n"
                "  1. Outdated deps (current → latest, breaking changes noted)\n"
                "  2. CVEs (dep, severity, CVE ID, fix version)\n"
                "  3. License conflicts (dep, license, risk level)\n"
                "STEP 6 — Apply safe patch-level upgrades automatically where possible.\n"
                "DONE: Audit report written, safe upgrades applied."
            ),
        },
        # ── Documentation ────────────────────────────
        {
            "id": "doc-sync", "name": "Doc Sync", "category": "Documentation", "icon": "📝",
            "description": "Keep README, CHANGELOG, and inline docstrings in sync with the latest code changes.",
            "browser": False,
            "task_template": (
                "▶ Q3 · Code Reviewer + L1 · Python Pro active.\n\n"
                "Sync all documentation with the current state of the codebase.\n\n"
                "STEP 1 — Read README.md (if exists). Read all source files.\n"
                "STEP 2 — For each public function/class/method that lacks a docstring, add one.\n"
                "  Python: \"\"\"One-line summary. Args: ... Returns: ...\"\"\"\n"
                "  JS/TS: /** @param ... @returns ... */\n"
                "  Go: // FunctionName does X.\n"
                "STEP 3 — Read CHANGELOG.md (create if missing). Run: git log --oneline -30\n"
                "  Add any commits since the last changelog entry under the correct version heading.\n"
                "STEP 4 — Update README.md:\n"
                "  • Ensure install/run instructions match current package.json/pyproject.toml scripts\n"
                "  • Update any API endpoint tables to match current routes\n"
                "  • Update environment variable tables to match current .env.example or config\n"
                "STEP 5 — write_file each updated file with complete content.\n"
                "DONE: List of files updated and specific sections changed."
            ),
        },
        {
            "id": "readme-gen", "name": "README Gen", "category": "Documentation", "icon": "📖",
            "description": "Auto-generate a rich README from code, docstrings, and project structure.",
            "browser": False,
            "task_template": (
                "▶ A1 · Backend Architect + Q3 · Code Reviewer active.\n\n"
                "Generate a comprehensive, production-grade README.md for this project.\n\n"
                "STEP 1 — Explore the full project: list_directory, read package.json/pyproject.toml/go.mod, read main entry points.\n"
                "STEP 2 — Read all route handlers / API surface to document endpoints.\n"
                "STEP 3 — Read any existing .env.example or config files to document env vars.\n"
                "STEP 4 — write_file README.md with these sections:\n"
                "  # Project Name — one-line description\n"
                "  ## Features — bullet list of key capabilities\n"
                "  ## Tech Stack — languages, frameworks, key deps\n"
                "  ## Prerequisites — node/python/go version, required tools\n"
                "  ## Installation — step-by-step clone + install commands\n"
                "  ## Configuration — table of all env vars with description and defaults\n"
                "  ## Running — dev, prod, and test commands\n"
                "  ## API Reference — table of endpoints (method, path, description, auth)\n"
                "  ## Project Structure — annotated directory tree\n"
                "  ## Contributing — PR workflow, code style guide\n"
                "  ## License\n"
                "DONE: README.md written with full documentation."
            ),
        },
        {
            "id": "changelog-sync", "name": "Changelog Sync", "category": "Documentation", "icon": "📄",
            "description": "Synthesize git log into a structured CHANGELOG.md with semantic versioning.",
            "browser": False,
            "task_template": (
                "▶ O1 · DevOps SRE active.\n\n"
                "Synthesize the git history into a structured CHANGELOG.md following Keep a Changelog format.\n\n"
                "STEP 1 — run_command: git log --oneline --no-merges -100\n"
                "STEP 2 — run_command: git tag --sort=-version:refname | head -20  (to find version tags)\n"
                "STEP 3 — run_command: git log --format='%H %s' --no-merges  (full commit list)\n"
                "STEP 4 — Read existing CHANGELOG.md if present.\n"
                "STEP 5 — Categorize commits by type:\n"
                "  Added: feat, add, new\n"
                "  Changed: refactor, update, change, improve\n"
                "  Fixed: fix, bug, patch, resolve\n"
                "  Removed: remove, delete, drop\n"
                "  Security: security, cve, vuln, auth\n"
                "STEP 6 — write_file CHANGELOG.md using Keep a Changelog format:\n"
                "  ## [Unreleased] — commits since last tag\n"
                "  ## [x.y.z] — YYYY-MM-DD — commits per tag\n"
                "  Each section has Added / Changed / Fixed / Removed / Security sub-sections.\n"
                "DONE: CHANGELOG.md written with full history."
            ),
        },
        {
            "id": "api-docs", "name": "API Docs", "category": "Documentation", "icon": "🔗",
            "description": "Generate OpenAPI/Swagger documentation from route handlers and type annotations.",
            "browser": False,
            "task_template": (
                "▶ A1 · Backend Architect + A6 · API Gateway Architect active.\n\n"
                "Generate complete OpenAPI 3.0 documentation for all API routes in this project.\n\n"
                "STEP 1 — Find all route definition files: search_files for '@app.', 'router.', 'app.get(', 'app.post('.\n"
                "STEP 2 — Read every route file. For each endpoint, extract:\n"
                "  • HTTP method and path\n"
                "  • Path/query parameters and their types\n"
                "  • Request body schema (from Pydantic models, TypeScript interfaces, etc.)\n"
                "  • Response schema and status codes\n"
                "  • Auth requirements\n"
                "STEP 3 — Write openapi.yaml with:\n"
                "  openapi: 3.0.0, info (title, version, description)\n"
                "  paths: each route with get/post/put/delete operations\n"
                "  components/schemas: all request/response models\n"
                "  components/securitySchemes: bearer token / API key if used\n"
                "STEP 4 — Also write a concise API_REFERENCE.md table:\n"
                "  | Method | Path | Description | Auth | Request Body | Response |\n"
                "DONE: openapi.yaml and API_REFERENCE.md written."
            ),
        },
        # ── DevOps & Infra ───────────────────────────
        {
            "id": "ci-gen", "name": "CI Pipeline Gen", "category": "DevOps", "icon": "♾️",
            "description": "Generate GitHub Actions / GitLab CI pipeline config from project type and commands.",
            "browser": False,
            "task_template": (
                "▶ I4 · Deploy Engineer + O1 · DevOps SRE active.\n\n"
                "Generate a production-ready CI/CD pipeline for this project.\n\n"
                "STEP 1 — Detect project type from: package.json, pyproject.toml, go.mod, Cargo.toml, Dockerfile.\n"
                "STEP 2 — Read existing scripts (npm scripts, Makefile, justfile) to find test/build/lint commands.\n"
                "STEP 3 — Check for existing .github/workflows/ or .gitlab-ci.yml.\n"
                "STEP 4 — Generate .github/workflows/ci.yml with jobs:\n"
                "  lint:  checkout → setup runtime → install deps → run linter\n"
                "  test:  checkout → setup runtime → install deps → run tests with coverage\n"
                "  build: checkout → setup runtime → install deps → build artifacts\n"
                "  security: run dependency audit + secrets scan\n"
                "  Use matrix strategy for multiple runtime versions where appropriate.\n"
                "STEP 5 — If Dockerfile exists, also write .github/workflows/docker.yml to build+push on tags.\n"
                "STEP 6 — write_file each workflow file.\n"
                "DONE: CI pipeline files written with all jobs configured."
            ),
        },
        {
            "id": "docker-gen", "name": "Dockerize", "category": "DevOps", "icon": "🐳",
            "description": "Generate optimized Dockerfile + docker-compose.yml for the current project stack.",
            "browser": False,
            "task_template": (
                "▶ I4 · Deploy Engineer + I1 · Cloud Architect active.\n\n"
                "Generate an optimized Dockerfile and docker-compose.yml for this project.\n\n"
                "STEP 1 — Detect stack: read package.json (Node version), pyproject.toml (Python version), go.mod, etc.\n"
                "STEP 2 — Read entry point files to understand the start command.\n"
                "STEP 3 — Check for .env.example to identify required env vars.\n"
                "STEP 4 — write_file Dockerfile with:\n"
                "  • Multi-stage build (builder stage + slim runtime stage)\n"
                "  • Non-root user for security\n"
                "  • .dockerignore-friendly COPY patterns\n"
                "  • Correct EXPOSE port\n"
                "  • Health check instruction\n"
                "  • Minimal final image (alpine or distroless)\n"
                "STEP 5 — write_file docker-compose.yml with:\n"
                "  • app service with build context, ports, env_file\n"
                "  • Any required services (postgres, redis, etc.) detected from deps\n"
                "  • Named volumes for persistent data\n"
                "  • Networks config\n"
                "STEP 6 — write_file .dockerignore with node_modules, __pycache__, .git, .env, dist, build.\n"
                "DONE: Dockerfile, docker-compose.yml, and .dockerignore written."
            ),
        },
        {
            "id": "git-activity", "name": "Git Activity Report", "category": "DevOps", "icon": "⚛️",
            "description": "Analyze git history and generate a developer activity + hotspot heatmap report.",
            "browser": False,
            "task_template": (
                "▶ O1 · DevOps SRE + D4 · Data Engineer active.\n\n"
                "Analyze git history and produce a developer activity and code hotspot report.\n\n"
                "STEP 1 — run_command: git log --format='%ae %ad %s' --date=short -500\n"
                "STEP 2 — run_command: git log --numstat --no-merges -200 (files changed per commit)\n"
                "STEP 3 — run_command: git shortlog -sn --no-merges (commits per author)\n"
                "STEP 4 — run_command: git log --format='' --name-only | sort | uniq -c | sort -rn | head -30 (hotspot files)\n"
                "STEP 5 — Analyze the data:\n"
                "  • Commit frequency by week / by author\n"
                "  • Most-changed files (churn hotspots = refactor candidates)\n"
                "  • Largest single commits (risk signal)\n"
                "  • Files changed together frequently (coupling)\n"
                "STEP 6 — write_file GIT_ACTIVITY_REPORT.md with:\n"
                "  Contributor summary table, weekly activity chart (ASCII), top 10 hotspot files, coupling analysis, recommendations.\n"
                "DONE: GIT_ACTIVITY_REPORT.md written."
            ),
        },
        {
            "id": "license-check", "name": "License Check", "category": "DevOps", "icon": "⚖️",
            "description": "Scan all dependency licenses for incompatibilities and output a compliance report.",
            "browser": False,
            "task_template": (
                "▶ Q1 · Security Auditor + G3 · Governance active.\n\n"
                "Scan all dependency licenses for incompatibilities and produce a compliance report.\n\n"
                "STEP 1 — Read all dependency manifests (package.json, requirements.txt, pyproject.toml, go.mod).\n"
                "STEP 2 — Run license extraction:\n"
                "  Node: npx license-checker --json --out licenses.json\n"
                "  Python: pip-licenses --format json\n"
                "  Go: go-licenses report ./...\n"
                "STEP 3 — Read the project's own LICENSE file to determine its type (MIT/Apache/GPL/Proprietary).\n"
                "STEP 4 — Flag incompatibilities:\n"
                "  • GPL/AGPL in any commercial or MIT/Apache project → RED: copyleft contamination risk\n"
                "  • LGPL → YELLOW: dynamic linking required, review needed\n"
                "  • No license / Unknown → RED: cannot legally use\n"
                "  • CC-BY-SA / CC-NC → YELLOW: review terms\n"
                "STEP 5 — write_file LICENSE_COMPLIANCE_REPORT.md with:\n"
                "  Project license, dependency count, RED/YELLOW/GREEN table, recommended actions.\n"
                "DONE: Compliance report written."
            ),
        },
        # ── Browser Automation (AIO-NUI) ───────────────────
        {
            "id": "web-research", "name": "Web Research", "category": "Browser", "icon": "🌐",
            "description": "Autonomously research a topic on the web, aggregate findings, and write a structured report.",
            "browser": True,
            "default_url": "https://www.google.com",
            "task_template": "Research the following topic thoroughly across multiple authoritative sources. Extract key facts, recent developments, expert opinions, and data points. Synthesize everything into a structured report with an executive summary, key findings, and sources.\n\nTOPIC: ",
        },
        {
            "id": "competitive-analysis", "name": "Competitive Analysis", "category": "Browser", "icon": "🔭",
            "description": "Browse competitor sites and GitHub repos to generate a structured competitive landscape.",
            "browser": True,
            "default_url": "https://github.com",
            "task_template": "Perform a competitive analysis. Find the top 5 competitors, visit their sites and GitHub repos, analyze features, pricing, positioning, tech stack, and recent activity. Output a structured comparison table with strengths, weaknesses, and market gaps.\n\nPRODUCT/SPACE: ",
        },
        {
            "id": "site-tester", "name": "Site Tester", "category": "Browser", "icon": "🧪",
            "description": "Navigate and interact with a website autonomously to test flows and report issues.",
            "browser": True,
            "default_url": "http://localhost:3000",
            "task_template": "Test this website thoroughly. Navigate all main routes, click all buttons and links, submit forms with valid and invalid data, check for console errors, verify responsive layout, and test any auth flows. Write a detailed QA report with screenshots of any issues found.\n\nURL: ",
        },
        {
            "id": "data-harvester", "name": "Data Harvester", "category": "Browser", "icon": "🌾",
            "description": "Scrape structured data from websites and export to JSON/CSV in the project directory.",
            "browser": True,
            "default_url": "https://www.google.com",
            "task_template": "Harvest structured data from web sources. Navigate relevant pages, extract all structured data (tables, lists, cards), clean and normalize it, then save as a JSON array to data/harvested.json and a CSV to data/harvested.csv.\n\nDATA TARGET: ",
        },
        {
            "id": "visual-regression", "name": "Visual Regression", "category": "Browser", "icon": "🖊️",
            "description": "Screenshot all key pages of a web app and flag visual anomalies vs baseline.",
            "browser": True,
            "default_url": "http://localhost:3000",
            "task_template": "Perform visual regression testing. Capture full-page screenshots of the homepage, all main navigation destinations, mobile viewport (375px wide), and any modal/overlay states. Compare against any existing baselines and flag visual regressions, layout breaks, or missing content.\n\nSITE URL: ",
        },
        {
            "id": "api-explorer", "name": "API Explorer", "category": "Browser", "icon": "🔎",
            "description": "Browse API documentation pages and generate client code snippets for key endpoints.",
            "browser": True,
            "default_url": "https://docs.github.com",
            "task_template": "Explore the API documentation at the given URL. Identify the most important endpoints, extract their request/response schemas, auth methods, and rate limits. Generate Python and JavaScript client code examples for the top 10 most useful endpoints.\n\nDOCS URL: ",
        },
        # ── Intelligence & Analysis ──────────────────────
        {
            "id": "tech-scout", "name": "Tech Stack Scout", "category": "Intelligence", "icon": "🚀",
            "description": "Discover and evaluate emerging tools, libraries, and frameworks for the project stack.",
            "browser": True,
            "default_url": "https://github.com/trending",
            "task_template": "Scout for emerging tools and libraries relevant to this project's stack. Check GitHub Trending, Hacker News (news.ycombinator.com), and npm/PyPI trending. For each candidate tool: evaluate maturity, community size, performance benchmarks, and fit for the project. Rank the top 10 with pros/cons and a recommendation.\n\nSTACK/TOPIC: ",
        },
        {
            "id": "report-builder", "name": "Report Builder", "category": "Intelligence", "icon": "📊",
            "description": "Generate an executive summary report from code analysis, git stats, and project metrics.",
            "browser": False,
            "task_template": (
                "▶ D4 · Data Engineer + A5 · Architecture Quality Guardian active.\n\n"
                "Generate a comprehensive executive summary report for this project.\n\n"
                "STEP 1 — Project overview: read_file README.md, package.json/pyproject.toml/go.mod.\n"
                "STEP 2 — Codebase metrics:\n"
                "  run_command: find . -name '*.py' -o -name '*.ts' -o -name '*.js' -o -name '*.go' | xargs wc -l 2>/dev/null | tail -1\n"
                "  run_command: git log --oneline | wc -l  (total commits)\n"
                "  run_command: git shortlog -sn --no-merges | head -10  (top contributors)\n"
                "STEP 3 — Health indicators:\n"
                "  run_command: git log --since='30 days ago' --oneline | wc -l  (30-day velocity)\n"
                "  Check for test files: search_files 'def test_' or 'it(' or 'describe('\n"
                "  Check for CI config: list_directory .github/workflows\n"
                "STEP 4 — Dependency count and staleness:\n"
                "  Count deps from manifest. Run outdated check.\n"
                "STEP 5 — write_file PROJECT_REPORT.md with:\n"
                "  Executive Summary, Health Score (0-100), Codebase Metrics table,\n"
                "  30-Day Velocity, Test Coverage estimate, Risk Factors, Top Recommendations.\n"
                "DONE: PROJECT_REPORT.md written with full analysis."
            ),
        },
    ]


@app.get("/api/skills")
async def list_skills():
    return [
        {"id": "python-expert", "name": "Python Expert", "icon": "🐍"},
        {"id": "react-architect", "name": "React Architect", "icon": "⚛️"},
        {"id": "devops-pro", "name": "DevOps Pro", "icon": "☁️"},
        {"id": "security-warden", "name": "Security Warden", "icon": "🛡️"},
        {"id": "rust-forge", "name": "Rust Forge", "icon": "🦀"},
        {"id": "data-alchemist", "name": "Data Alchemist", "icon": "🧬"},
        {"id": "ml-strategist", "name": "ML Strategist", "icon": "🤖"},
        {"id": "governance", "name": "Ethics Guardian", "icon": "⚖️"},
    ]


# ── SLM-v3 Sovereign Liquid Matrix endpoints ──────────────────────────────────

SLM_AGENTS = [
    {"coord":"ARC-01","cluster":"Architecture Core","name":"Principal Backend Systems Architect","keyword":"/principal-backend-systems-architect","brilliance":"Scale-first orchestration"},
    {"coord":"ARC-02","cluster":"Architecture Core","name":"Frontend Experience Architect","keyword":"/frontend-experience-architect","brilliance":"Front-end brilliance"},
    {"coord":"ARC-03","cluster":"Architecture Core","name":"Mobile Platform Architect","keyword":"/mobile-platform-architect","brilliance":"Mobile-grade excellence"},
    {"coord":"ARC-04","cluster":"Architecture Core","name":"GraphQL Platform Architect","keyword":"/graphql-platform-architect","brilliance":"Query architecture mastery"},
    {"coord":"ARC-05","cluster":"Architecture Core","name":"Architecture Quality Guardian","keyword":"/architecture-quality-guardian","brilliance":"Architecture guardianship"},
    {"coord":"ARC-06","cluster":"Architecture Core","name":"API Gateway Architect","keyword":"/api-gateway-architect","brilliance":"Gateway coherence"},
    {"coord":"ARC-07","cluster":"Architecture Core","name":"Event-Driven Systems Architect","keyword":"/event-driven-systems-architect","brilliance":"Event-stream mastery"},
    {"coord":"ARC-08","cluster":"Architecture Core","name":"Platform Resilience Architect","keyword":"/platform-resilience-architect","brilliance":"Resilience by design"},
    {"coord":"ARC-09","cluster":"Architecture Core","name":"AI Integration Architect","keyword":"/ai-integration-architect","brilliance":"AI-native architecture fusion"},
    {"coord":"ARC-10","cluster":"Architecture Core","name":"Multi-Modal Systems Architect","keyword":"/multi-modal-systems-architect","brilliance":"Multi-modal coherence"},
    {"coord":"LNG-01","cluster":"Language Excellence","name":"Python Platform Specialist","keyword":"/python-platform-specialist","brilliance":"Pythonic excellence"},
    {"coord":"LNG-02","cluster":"Language Excellence","name":"JavaScript Platform Specialist","keyword":"/javascript-platform-specialist","brilliance":"JavaScript mastery"},
    {"coord":"LNG-03","cluster":"Language Excellence","name":"Go Platform Specialist","keyword":"/go-platform-specialist","brilliance":"Go performance mastery"},
    {"coord":"LNG-04","cluster":"Language Excellence","name":"Rust Platform Specialist","keyword":"/rust-platform-specialist","brilliance":"Memory-safe acceleration"},
    {"coord":"LNG-05","cluster":"Language Excellence","name":"C Platform Specialist","keyword":"/c-platform-specialist","brilliance":"Bare-metal precision"},
    {"coord":"LNG-06","cluster":"Language Excellence","name":"C++ Platform Specialist","keyword":"/cpp-platform-specialist","brilliance":"High-performance craft"},
    {"coord":"LNG-07","cluster":"Language Excellence","name":"SQL Data Architect","keyword":"/sql-data-architect","brilliance":"Query precision"},
    {"coord":"LNG-11","cluster":"Language Excellence","name":"TypeScript Platform Specialist","keyword":"/typescript-platform-specialist","brilliance":"TypeScript supremacy"},
    {"coord":"CLD-01","cluster":"Cloud & Platform","name":"Cloud Infrastructure Principal","keyword":"/cloud-infrastructure-principal","brilliance":"Cloud-scale design"},
    {"coord":"CLD-02","cluster":"Cloud & Platform","name":"Infrastructure as Code Principal","keyword":"/infrastructure-as-code-principal","brilliance":"IaC precision"},
    {"coord":"CLD-03","cluster":"Cloud & Platform","name":"Network Reliability Architect","keyword":"/network-reliability-architect","brilliance":"Low-latency mastery"},
    {"coord":"CLD-04","cluster":"Cloud & Platform","name":"Release & Deployment Lead","keyword":"/release-and-deployment-lead","brilliance":"Seamless release flow"},
    {"coord":"CLD-08","cluster":"Cloud & Platform","name":"Serverless Platform Architect","keyword":"/serverless-platform-architect","brilliance":"Serverless velocity"},
    {"coord":"OPS-01","cluster":"Operations & Reliability","name":"DevOps Reliability Lead","keyword":"/devops-reliability-lead","brilliance":"Rapid recovery"},
    {"coord":"OPS-02","cluster":"Operations & Reliability","name":"Incident Response Commander","keyword":"/incident-response-commander","brilliance":"Crisis command"},
    {"coord":"OPS-03","cluster":"Operations & Reliability","name":"Database Operations Principal","keyword":"/database-operations-principal","brilliance":"Data reliability"},
    {"coord":"OPS-04","cluster":"Operations & Reliability","name":"Database Performance Principal","keyword":"/database-performance-principal","brilliance":"Query acceleration"},
    {"coord":"OPS-05","cluster":"Operations & Reliability","name":"Release Operations Principal","keyword":"/release-operations-principal","brilliance":"Release precision"},
    {"coord":"OPS-06","cluster":"Operations & Reliability","name":"Site Reliability Principal","keyword":"/site-reliability-principal","brilliance":"Reliability leadership"},
    {"coord":"OPS-07","cluster":"Operations & Reliability","name":"Incident Command Lead","keyword":"/incident-command-lead","brilliance":"Incident command"},
    {"coord":"OPS-08","cluster":"Operations & Reliability","name":"Cloud Cost Optimization Principal","keyword":"/cloud-cost-optimization-principal","brilliance":"Cost discipline"},
    {"coord":"AID-01","cluster":"AI & Data Systems","name":"Applied AI Principal","keyword":"/applied-ai-principal","brilliance":"Applied intelligence"},
    {"coord":"AID-02","cluster":"AI & Data Systems","name":"Machine Learning Principal","keyword":"/machine-learning-principal","brilliance":"Model rigor"},
    {"coord":"AID-03","cluster":"AI & Data Systems","name":"MLOps Platform Architect","keyword":"/mlops-platform-architect","brilliance":"MLOps velocity"},
    {"coord":"AID-04","cluster":"AI & Data Systems","name":"Data Pipeline Architect","keyword":"/data-pipeline-architect","brilliance":"Pipeline mastery"},
    {"coord":"AID-05","cluster":"AI & Data Systems","name":"Data Science Principal","keyword":"/data-science-principal","brilliance":"Insight rigor"},
    {"coord":"AID-09","cluster":"AI & Data Systems","name":"Agentic Workflow Architect","keyword":"/agentic-workflow-architect","brilliance":"Agentic orchestration"},
    {"coord":"QSP-01","cluster":"Quality, Security & Performance","name":"Security Audit Principal","keyword":"/security-audit-principal","brilliance":"Security assurance"},
    {"coord":"QSP-02","cluster":"Quality, Security & Performance","name":"Security Hardening Principal","keyword":"/security-hardening-principal","brilliance":"Hardening depth"},
    {"coord":"QSP-03","cluster":"Quality, Security & Performance","name":"Code Quality Principal","keyword":"/code-quality-principal","brilliance":"Code trust"},
    {"coord":"QSP-04","cluster":"Quality, Security & Performance","name":"Debugging Principal","keyword":"/debugging-principal","brilliance":"Bug eradication"},
    {"coord":"QSP-05","cluster":"Quality, Security & Performance","name":"Error Forensics Principal","keyword":"/error-forensics-principal","brilliance":"Failure forensics"},
    {"coord":"QSP-06","cluster":"Quality, Security & Performance","name":"Performance Engineering Principal","keyword":"/performance-engineering-principal","brilliance":"Speed dominance"},
    {"coord":"QSP-07","cluster":"Quality, Security & Performance","name":"Test Automation Principal","keyword":"/test-automation-principal","brilliance":"Test coverage"},
    {"coord":"QSP-11","cluster":"Quality, Security & Performance","name":"AI Safety Validation Lead","keyword":"/ai-safety-validation-lead","brilliance":"Safety validation"},
    {"coord":"BUS-01","cluster":"Business & Finance","name":"Business Intelligence Principal","keyword":"/business-intelligence-principal","brilliance":"Business clarity"},
    {"coord":"BUS-02","cluster":"Business & Finance","name":"Quant Strategy Principal","keyword":"/quant-strategy-principal","brilliance":"Quant edge"},
    {"coord":"BUS-03","cluster":"Business & Finance","name":"Risk Governance Principal","keyword":"/risk-governance-principal","brilliance":"Risk governance"},
    {"coord":"REV-01","cluster":"Revenue & Sales","name":"Content Strategy Principal","keyword":"/content-strategy-principal","brilliance":"Content resonance"},
    {"coord":"REV-02","cluster":"Revenue & Sales","name":"Sales Automation Principal","keyword":"/sales-automation-principal","brilliance":"Automation leverage"},
    {"coord":"REV-03","cluster":"Revenue & Sales","name":"Customer Support Principal","keyword":"/customer-support-principal","brilliance":"Support excellence"},
    {"coord":"LEG-01","cluster":"Modernization & Legacy","name":"Context Orchestration Principal","keyword":"/context-orchestration-principal","brilliance":"Context coherence"},
    {"coord":"LEG-02","cluster":"Modernization & Legacy","name":"Prompt Systems Principal","keyword":"/prompt-systems-principal","brilliance":"Prompt finesse"},
    {"coord":"LEG-03","cluster":"Modernization & Legacy","name":"Search Relevance Principal","keyword":"/search-relevance-principal","brilliance":"Search precision"},
    {"coord":"LEG-04","cluster":"Modernization & Legacy","name":"API Documentation Principal","keyword":"/api-documentation-principal","brilliance":"Docs excellence"},
    {"coord":"LEG-05","cluster":"Modernization & Legacy","name":"Developer Experience Principal","keyword":"/developer-experience-principal","brilliance":"Developer delight"},
    {"coord":"LEG-06","cluster":"Modernization & Legacy","name":"Legacy Modernization Principal","keyword":"/legacy-modernization-principal","brilliance":"Modernization leap"},
    {"coord":"LEG-08","cluster":"Modernization & Legacy","name":"Autonomous Migration Architect","keyword":"/autonomous-migration-architect","brilliance":"Autonomous modernization"},
    {"coord":"ENG-01","cluster":"Engineering Systems","name":"Systems Architecture Principal","keyword":"/systems-architecture-principal","brilliance":"Systems coherence"},
    {"coord":"ENG-02","cluster":"Engineering Systems","name":"API Experience Architect","keyword":"/api-experience-architect","brilliance":"API elegance"},
    {"coord":"ENG-03","cluster":"Engineering Systems","name":"Core Systems Principal","keyword":"/core-systems-principal","brilliance":"Core stability"},
    {"coord":"ENG-04","cluster":"Engineering Systems","name":"Integration Systems Principal","keyword":"/integration-systems-principal","brilliance":"Seamless integration"},
    {"coord":"DAT-01","cluster":"Data Intelligence","name":"Data Modeling Architect","keyword":"/data-modeling-architect","brilliance":"Data coherence"},
    {"coord":"DAT-02","cluster":"Data Intelligence","name":"Analytics Platform Architect","keyword":"/analytics-platform-architect","brilliance":"Metrics clarity"},
    {"coord":"DAT-03","cluster":"Data Intelligence","name":"ML Strategy Principal","keyword":"/ml-strategy-principal","brilliance":"Strategic ML"},
    {"coord":"DAT-04","cluster":"Data Intelligence","name":"Insight Synthesis Principal","keyword":"/insight-synthesis-principal","brilliance":"Signal synthesis"},
    {"coord":"DAT-07","cluster":"Data Intelligence","name":"Real-Time Analytics Architect","keyword":"/real-time-analytics-architect","brilliance":"Real-time insight"},
    {"coord":"REL-01","cluster":"Reliability Engineering","name":"Test Architecture Principal","keyword":"/test-architecture-principal","brilliance":"Test architecture"},
    {"coord":"REL-02","cluster":"Reliability Engineering","name":"Reliability Engineering Principal","keyword":"/reliability-engineering-principal","brilliance":"Reliability rigor"},
    {"coord":"REL-03","cluster":"Reliability Engineering","name":"Performance Insight Principal","keyword":"/performance-insight-principal","brilliance":"Performance insight"},
    {"coord":"REL-04","cluster":"Reliability Engineering","name":"Security Review Principal","keyword":"/security-review-principal","brilliance":"Security confidence"},
    {"coord":"GRW-01","cluster":"Growth & Lifecycle","name":"Acquisition Growth Principal","keyword":"/acquisition-growth-principal","brilliance":"Acquisition lift"},
    {"coord":"GRW-02","cluster":"Growth & Lifecycle","name":"Lifecycle Growth Principal","keyword":"/lifecycle-growth-principal","brilliance":"Lifecycle growth"},
    {"coord":"GRW-03","cluster":"Growth & Lifecycle","name":"Sales Enablement Principal","keyword":"/sales-enablement-principal","brilliance":"Sales momentum"},
    {"coord":"GRW-04","cluster":"Growth & Lifecycle","name":"Customer Success Principal","keyword":"/customer-success-principal","brilliance":"Customer outcomes"},
    {"coord":"GOV-01","cluster":"Governance & Risk","name":"Compliance Stewardship Principal","keyword":"/compliance-stewardship-principal","brilliance":"Compliance clarity"},
    {"coord":"GOV-02","cluster":"Governance & Risk","name":"Policy Engineering Principal","keyword":"/policy-engineering-principal","brilliance":"Policy precision"},
    {"coord":"GOV-03","cluster":"Governance & Risk","name":"Risk Assessment Principal","keyword":"/risk-assessment-principal","brilliance":"Risk insight"},
    {"coord":"GOV-04","cluster":"Governance & Risk","name":"Ethics & Trust Principal","keyword":"/ethics-and-trust-principal","brilliance":"Ethical integrity"},
    {"coord":"PST-01","cluster":"Product Strategy","name":"Vision Strategy Architect","keyword":"/vision-strategy-architect","brilliance":"Vision alignment"},
    {"coord":"PST-02","cluster":"Product Strategy","name":"Market Intelligence Principal","keyword":"/market-intelligence-principal","brilliance":"Market foresight"},
    {"coord":"PST-03","cluster":"Product Strategy","name":"Opportunity Discovery Principal","keyword":"/opportunity-discovery-principal","brilliance":"Opportunity signal"},
    {"coord":"PST-04","cluster":"Product Strategy","name":"Roadmap Strategy Architect","keyword":"/roadmap-strategy-architect","brilliance":"Roadmap coherence"},
    {"coord":"EXP-01","cluster":"Experience Design","name":"UX Systems Principal","keyword":"/ux-systems-principal","brilliance":"UX orchestration"},
    {"coord":"EXP-02","cluster":"Experience Design","name":"Visual Systems Architect","keyword":"/visual-systems-architect","brilliance":"Visual harmony"},
    {"coord":"EXP-03","cluster":"Experience Design","name":"Interaction Systems Architect","keyword":"/interaction-systems-architect","brilliance":"Interaction delight"},
    {"coord":"EXP-04","cluster":"Experience Design","name":"Accessibility Standards Principal","keyword":"/accessibility-standards-principal","brilliance":"Inclusive excellence"},
]

SLM_PHASES = [
    {
        "id": "phase-1",
        "name": "Architecture Initialization",
        "description": "Spawn global state — activate core architecture subagents",
        "chain": ["ARC-01", "ARC-02", "ARC-09", "ARC-10"],
        "prompt": "Activate subagents ARC-01, ARC-02, ARC-09, ARC-10. Output a comprehensive architecture blueprint for the current project.",
        "phase_num": 1,
    },
    {
        "id": "phase-2",
        "name": "Language & Platform Foundation",
        "description": "Polyglot core — activate language specialists",
        "chain": ["LNG-01", "LNG-02", "LNG-03", "LNG-11"],
        "prompt": "Activate subagents LNG-01, LNG-02, LNG-03, LNG-11. Generate language-specific implementations and best practices for the current codebase.",
        "phase_num": 2,
    },
    {
        "id": "phase-3",
        "name": "Cloud & Reliability Layer",
        "description": "Infrastructure hardening — cloud and reliability",
        "chain": ["CLD-01", "CLD-08", "OPS-01"],
        "prompt": "Activate subagents CLD-01, CLD-08, OPS-01. Provision cloud and reliability layers, outputting infrastructure recommendations.",
        "phase_num": 3,
    },
    {
        "id": "phase-4",
        "name": "AI & Data Intelligence",
        "description": "Cognitive core — AI/data pipeline synthesis",
        "chain": ["AID-01", "AID-09", "DAT-01", "DAT-07"],
        "prompt": "Activate subagents AID-01, AID-09, DAT-01, DAT-07. Synthesize AI/data pipelines for the current project.",
        "phase_num": 4,
    },
    {
        "id": "phase-5",
        "name": "Quality, Security & Governance",
        "description": "Validation and trust — security audit and ethics check",
        "chain": ["QSP-01", "QSP-11", "GOV-01", "LEG-08"],
        "prompt": "Activate subagents QSP-01, QSP-11, GOV-01, LEG-08. Perform a thorough security audit, ethics check, and legacy migration assessment.",
        "phase_num": 5,
    },
    {
        "id": "phase-6",
        "name": "Business & Experience Closure",
        "description": "Optional scaling — business alignment and UX closure",
        "chain": ["BUS-01", "PST-01", "EXP-01", "REV-01"],
        "prompt": "Activate subagents BUS-01, PST-01, EXP-01, REV-01. Finalize business alignment and UX refinement for the current project.",
        "phase_num": 6,
    },
]


@app.get("/api/slm/agents")
async def get_slm_agents(cluster: str = None, search: str = None):
    """Return the full SLM-v3 Sovereign Liquid Matrix agent registry, merged with custom Gym agents."""
    # Merge built-in + custom gym agents (custom wins on coord collision)
    custom = load_custom_agents()
    custom_coords = {a["coord"] for a in custom}
    agents = [a for a in SLM_AGENTS if a["coord"] not in custom_coords] + custom
    if cluster:
        agents = [a for a in agents if a["cluster"].lower() == cluster.lower()]
    if search:
        q = search.lower()
        agents = [a for a in agents if q in a["name"].lower() or q in a["coord"].lower() or q in a["brilliance"].lower()]
    # Group by cluster
    clusters: dict = {}
    for a in agents:
        c = a["cluster"]
        if c not in clusters:
            clusters[c] = []
        clusters[c].append(a)
    return {"agents": agents, "clusters": clusters, "total": len(agents)}


@app.get("/api/slm/phases")
async def get_slm_phases():
    """Return the SLM-v3 phased workflow sequences."""
    return {"phases": SLM_PHASES}


# ── SLM Gym endpoints ─────────────────────────────────────────────────────────

@app.get("/api/gym/agents")
async def gym_list_agents():
    """List all custom agents forged in the Gym."""
    return {"agents": load_custom_agents()}


@app.get("/api/gym/clusters")
async def gym_list_clusters():
    """List all custom clusters forged in the Gym."""
    return {"clusters": load_custom_clusters()}


@app.get("/api/gym/scenarios")
async def gym_list_scenarios():
    """List all training scenarios recorded in the Gym."""
    return {"scenarios": load_scenarios()}


# ── CryptKeeper endpoints ─────────────────────────────────────────────────────
# Manages ~/.open_codex/.env — the canonical env file sourced by all
# MCP servers.  Values are NEVER returned to the frontend; only key names.

class CKEnvRequest(BaseModel):
    name: str
    value: str

class CKDenyRequest(BaseModel):
    name: str
    reason: str = ""

@app.get("/api/cryptkeeper/env")
async def ck_get_env():
    """Return stored env var NAMES only — values stay on server."""
    return {"keys": env_list_names()}

@app.post("/api/cryptkeeper/env")
async def ck_set_env(req: CKEnvRequest):
    """Store/update a key=value in ~/.open_codex/.env and export to live process."""
    if not req.name.strip() or not req.value.strip():
        raise HTTPException(400, "name and value are required")
    env_set(req.name.strip(), req.value.strip())
    return {"ok": True, "name": req.name.strip()}

@app.delete("/api/cryptkeeper/env/{name}")
async def ck_del_env(name: str):
    """Remove a key from ~/.open_codex/.env."""
    env_delete(name)
    return {"ok": True, "name": name}

@app.get("/api/cryptkeeper/requests")
async def ck_get_requests():
    """Pending secret requests from Forge agents (name, reason, browser_alternative)."""
    return {"requests": list_requests()}

@app.post("/api/cryptkeeper/dismiss/{name}")
async def ck_dismiss(name: str):
    """Dismiss a pending request (without storing anything)."""
    dismiss_request(name)
    return {"ok": True}

@app.post("/api/cryptkeeper/deny")
async def ck_deny(req: CKDenyRequest):
    """Deny a secret request — agent should fall back to browser automation."""
    deny_request(req.name, req.reason)
    return {"ok": True}


# ── Repo→MCP endpoints ────────────────────────────────────────────────────────

class RepoAddRequest(BaseModel):
    url:        str
    name:       Optional[str] = None
    auth_token: Optional[str] = None
    branch:     Optional[str] = None

@app.post("/api/repos")
async def repo_add(req: RepoAddRequest):
    """Clone a GitHub repo and register it as an MCP server."""
    try:
        manifest = add_repo(
            _mcp_bridge,
            url=req.url,
            name=req.name,
            auth_token=req.auth_token,
            branch=req.branch,
            ai_config={
                "AI_PROVIDER":   os.getenv("JOOMLA_AI_PROVIDER", "ollama"),
                "OLLAMA_HOST":   os.getenv("OLLAMA_HOST", "http://localhost:11434"),
                "OLLAMA_MODEL":  os.getenv("OLLAMA_MODEL", "llama3"),
                "LMSTUDIO_HOST": os.getenv("LMSTUDIO_HOST", "http://localhost:1234"),
                "LMSTUDIO_MODEL":os.getenv("LMSTUDIO_MODEL", "local-model"),
            },
        )
        return {"ok": True, "repo": manifest}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))

@app.get("/api/repos")
async def repo_list():
    """List all registered Repo→MCP tools."""
    return {"repos": list_repos()}

@app.delete("/api/repos/{name}")
async def repo_remove(name: str):
    """Unregister and delete a Repo→MCP tool."""
    remove_repo(_mcp_bridge, name)
    return {"ok": True}

@app.post("/api/repos/{name}/pull")
async def repo_pull(name: str):
    """Pull latest changes for a registered repo."""
    from open_codex.mcp_servers_repo import get_repo
    srv = get_repo(name)
    if not srv:
        raise HTTPException(status_code=404, detail=f"Repo '{name}' not registered")
    result = srv._server.call(f"repo_{name.lower().replace('-','_')}_pull", {}, ".")
    return {"ok": True, "result": result}


# ── Legacy /api/project/tree alias (fixes broken frontend call) ───────────────

@app.get("/api/project/tree")
async def project_tree_alias(project_id: str):
    """Alias for /api/projects/{project_id}/tree to fix broken frontend reference."""
    return await project_tree(project_id)


# ── Project endpoints ─────────────────────────────────────────────────────────

@app.get("/api/projects")
async def list_projects():
    return _load_projects()


@app.post("/api/projects")
async def add_project(req: AddProjectRequest):
    path = os.path.realpath(os.path.expanduser(req.path))
    if not os.path.isdir(path):
        raise HTTPException(400, f"Directory not found: {path}")
    projects = _load_projects()
    pid = _project_id(path)
    if any(p["id"] == pid for p in projects):
        raise HTTPException(409, "Project already added")
    name = req.name or os.path.basename(path)
    git = git_tools.is_git_repo(path)
    project = {"id": pid, "path": path, "name": name, "git": git}
    projects.append(project)
    _save_projects(projects)
    return project


@app.delete("/api/projects/{project_id}")
async def remove_project(project_id: str):
    projects = _load_projects()
    projects = [p for p in projects if p["id"] != project_id]
    _save_projects(projects)
    return {"status": "ok"}


@app.post("/api/projects/pick")
async def pick_project_dialog():
    """Open a native folder picker dialog (macOS via osascript, fallback to tkinter)."""
    # 1. Try macOS osascript (AppleScript) first as it's more native
    if os.uname().sysname == "Darwin":
        try:
            cmd = "osascript -e 'POSIX path of (choose folder with prompt \"Select Project Folder\")'"
            r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if r.returncode == 0:
                path = r.stdout.strip()
                if path:
                    return {"path": path}
            # Cancelled or errored (don't return error yet, try fallback)
        except Exception as e:
            pass

    # 2. Try tkinter fallback
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.wm_attributes('-topmost', 1)
        path = filedialog.askdirectory(title="Select Project Folder")
        root.destroy()
        if path:
            return {"path": path}
        return {"path": None}
    except Exception as e:
        # If both fail, return None and let the frontend handle it or explain
        return {"path": None, "error": f"Native picker not available: {e}"}


@app.get("/api/projects/{project_id}/tree")
async def project_tree(project_id: str):
    projects = _load_projects()
    project = next((p for p in projects if p["id"] == project_id), None)
    if not project:
        raise HTTPException(404, "Project not found")
    tree = file_tools.get_file_tree(project["path"])

    # Normalise type: "dir" → "directory" to match frontend FileNode interface
    def _normalise(nodes: list) -> list:
        out = []
        for n in nodes:
            node = dict(n)
            if node.get("type") == "dir":
                node["type"] = "directory"
            if "children" in node:
                node["children"] = _normalise(node["children"])
            out.append(node)
        return out

    return {"tree": _normalise(tree)}


@app.get("/api/files")
@app.get("/api/file")
async def get_file_content(path: str, project: str):
    full_path = os.path.join(project, path) if not os.path.isabs(path) else path
    if not os.path.isfile(full_path):
        raise HTTPException(404, "File not found")
    try:
        content = file_tools.read_file(path if not os.path.isabs(path) else os.path.relpath(path, project), project)
        return {"content": content}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Git endpoints ─────────────────────────────────────────────────────────────

@app.get("/api/git/status")
async def git_status(project: str):
    if not os.path.isdir(project):
        raise HTTPException(400, "Invalid project directory")
    return git_tools.get_status(project)


@app.get("/api/git/diff")
async def git_diff(project: str, staged: bool = False):
    if not os.path.isdir(project):
        raise HTTPException(400, "Invalid project directory")
    diff = git_tools.get_diff(project, staged=staged)
    return {"diff": diff}


@app.get("/api/git/stats")
async def git_stats(project: str):
    if not os.path.isdir(project):
        raise HTTPException(400, "Invalid project directory")
    return git_tools.get_diff_stats(project)


@app.post("/api/git/commit")
async def git_commit(req: CommitRequest):
    if not os.path.isdir(req.project_dir):
        raise HTTPException(400, "Invalid project directory")
    result = git_tools.commit(req.project_dir, req.message)
    if not result["success"]:
        raise HTTPException(500, result.get("error", "Commit failed"))
    return result


@app.post("/api/git/push")
async def git_push_endpoint(req: PushPullRequest):
    if not os.path.isdir(req.project_dir):
        raise HTTPException(400, "Invalid project directory")
    result = git_tools.push(req.project_dir, req.remote, req.branch)
    if not result["success"]:
        raise HTTPException(500, result.get("output", "Push failed"))
    return result


@app.post("/api/git/pull")
async def git_pull_endpoint(req: PushPullRequest):
    if not os.path.isdir(req.project_dir):
        raise HTTPException(400, "Invalid project directory")
    result = git_tools.pull(req.project_dir, req.remote)
    if not result["success"]:
        raise HTTPException(500, result.get("output", "Pull failed"))
    return result


@app.get("/api/git/branches")
async def git_branches(project: str):
    if not os.path.isdir(project):
        raise HTTPException(400, "Invalid project directory")
    return git_tools.get_branches(project)


@app.get("/api/git/log")
async def git_log(project: str, n: int = 15):
    if not os.path.isdir(project):
        raise HTTPException(400, "Invalid project directory")
    return {"commits": git_tools.get_log(project, n)}


# ── Thread endpoints ──────────────────────────────────────────────────────────

@app.get("/api/threads")
async def get_threads(project: str):
    return _load_threads(project)


@app.post("/api/threads")
async def upsert_thread(req: ThreadUpsertRequest):
    threads = _load_threads(req.project_dir)
    tid = req.thread.get("id")
    idx = next((i for i, t in enumerate(threads) if t["id"] == tid), None)
    if idx is not None:
        threads[idx] = req.thread
    else:
        threads.insert(0, req.thread)
    _save_threads(req.project_dir, threads)
    return req.thread


@app.delete("/api/threads/{thread_id}")
async def delete_thread(thread_id: str, project: str):
    threads = _load_threads(project)
    threads = [t for t in threads if t["id"] != thread_id]
    _save_threads(project, threads)
    return {"status": "ok"}


# ── Terminal agent detection ──────────────────────────────────────────────────

_TERMINAL_AGENT_TYPES = {"claude_code", "gemini_cli", "codex", "openclaw"}


@app.get("/api/agents/terminal")
async def get_terminal_agents():
    """Detect installed & authenticated terminal AI agent CLIs."""
    from open_codex.agents.terminal_agents import detect_terminal_agents
    return {"agents": detect_terminal_agents()}


# ── Streaming chat (coding agent) ─────────────────────────────────────────────

# Registry: stream_id -> stop Event so the frontend can abort a stream
_active_streams: dict[str, threading.Event] = {}


@app.post("/api/chat/stream")
async def chat_stream(req: ChatStreamRequest):
    if not os.path.isdir(req.project_dir):
        raise HTTPException(400, f"Project directory not found: {req.project_dir}")

    import uuid
    stream_id = str(uuid.uuid4())
    stop_event = threading.Event()
    _active_streams[stream_id] = stop_event

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def run_agent():
        try:
            if req.agent_type in _TERMINAL_AGENT_TYPES:
                # ── Terminal CLI agent (Claude Code, Gemini CLI, Codex, OpenClaw) ──
                from open_codex.agents.terminal_agents import run_terminal_agent
                effective_prompt = req.message
                if req.slm_context:
                    effective_prompt = (
                        f"[SLM-v3 ROLE CONTEXT]\n{req.slm_context}\n\n"
                        f"[USER REQUEST]\n{req.message}"
                    )
                for event in run_terminal_agent(req.agent_type, effective_prompt, req.project_dir):
                    if stop_event.is_set():
                        loop.call_soon_threadsafe(
                            queue.put_nowait,
                            json.dumps({"type": "aborted", "stream_id": stream_id})
                        )
                        break
                    loop.call_soon_threadsafe(queue.put_nowait, json.dumps(event))
            elif req.agent_type == "gym_instructor":
                # ── SLM Gym Instructor — agent forge + training specialist ──────
                # req.slm_context carries the underlying provider type ("ollama", "lmstudio", "gemini", …)
                gym_provider = (req.slm_context or "ollama").strip() or "ollama"
                caller = AgentBuilder.get_llm_caller(
                    gym_provider, req.model, req.host, req.api_key
                )
                from open_codex.agents.gym_agent import GymAgent
                gym = GymAgent(caller)
                for event in gym.run(req.message, req.project_dir, max_steps=req.max_steps):
                    if stop_event.is_set():
                        loop.call_soon_threadsafe(
                            queue.put_nowait,
                            json.dumps({"type": "aborted", "stream_id": stream_id})
                        )
                        break
                    loop.call_soon_threadsafe(queue.put_nowait, json.dumps(event))
            else:
                # ── Standard LLM-backed coding agent ──────────────────────────────
                caller = AgentBuilder.get_llm_caller(
                    req.agent_type, req.model, req.host, req.api_key
                )

                # ── SLM-v3 role context injection ──────────────────────────────
                effective_message = req.message
                if req.slm_context:
                    effective_message = f"[SLM-v3 ROLE CONTEXT]\n{req.slm_context}\n\n[USER REQUEST]\n{req.message}"

                if req.team_mode:
                    # ── SLM Multi-agent swarm (TeamAgent) ─────────────────────
                    from open_codex.agents.team_agent import TeamAgent
                    agent = TeamAgent(caller, max_workers=4)
                    for event in agent.run(effective_message, req.project_dir, max_steps=req.max_steps):
                        if stop_event.is_set():
                            loop.call_soon_threadsafe(
                                queue.put_nowait,
                                json.dumps({"type": "aborted", "stream_id": stream_id})
                            )
                            break
                        loop.call_soon_threadsafe(queue.put_nowait, json.dumps(event))
                else:
                    from open_codex.agents.coding_agent import CodingAgent
                    agent = CodingAgent(caller)
                    for event in agent.run(effective_message, req.project_dir, max_steps=req.max_steps):
                        if stop_event.is_set():
                            loop.call_soon_threadsafe(
                                queue.put_nowait,
                                json.dumps({"type": "aborted", "stream_id": stream_id})
                            )
                            break
                        loop.call_soon_threadsafe(queue.put_nowait, json.dumps(event))
        except Exception as e:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                json.dumps({"type": "error", "content": str(e)})
            )
        finally:
            _active_streams.pop(stream_id, None)
            loop.call_soon_threadsafe(queue.put_nowait, None)


    threading.Thread(target=run_agent, daemon=True).start()

    async def generate():
        # Send the stream_id first so the client can abort later
        yield f"data: {json.dumps({'type': 'stream_id', 'stream_id': stream_id})}\n\n"
        while True:
            item = await queue.get()
            if item is None:
                break
            yield f"data: {item}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/chat/abort/{stream_id}")
async def abort_stream(stream_id: str):
    """Signal a running chat stream to stop after the current step."""
    event = _active_streams.get(stream_id)
    if event is None:
        raise HTTPException(404, f"No active stream: {stream_id}")
    event.set()
    return {"status": "abort_requested", "stream_id": stream_id}


# ── Chat message management ───────────────────────────────────────────────────

@app.delete("/api/chat/messages")
async def delete_message(req: DeleteMessageRequest):
    """
    Delete a single message (by 0-based index) from a stored thread.
    Deletes the message AND its paired partner (e.g. user+assistant pair).
    """
    threads = _load_threads(req.project_dir)
    thread = next((t for t in threads if t["id"] == req.thread_id), None)
    if thread is None:
        raise HTTPException(404, f"Thread not found: {req.thread_id}")
    messages = thread.get("messages", [])
    idx = req.message_index
    if idx < 0 or idx >= len(messages):
        raise HTTPException(400, f"Message index {idx} out of range (0–{len(messages)-1})")
    # Remove the message; also remove its pair if it exists
    messages.pop(idx)
    if idx < len(messages):          # the next message is the paired response
        messages.pop(idx)
    thread["messages"] = messages
    _save_threads(req.project_dir, threads)
    return {"status": "ok", "remaining": len(messages)}


@app.delete("/api/threads/{thread_id}/messages")
async def clear_thread_messages(thread_id: str, project: str):
    """Wipe all messages from a thread (keep the thread itself)."""
    threads = _load_threads(project)
    thread = next((t for t in threads if t["id"] == thread_id), None)
    if thread is None:
        raise HTTPException(404, f"Thread not found: {thread_id}")
    thread["messages"] = []
    _save_threads(project, threads)
    return {"status": "ok"}


# ── Provider health checks ────────────────────────────────────────────────────

@app.get("/api/health/{provider}")
async def provider_health(provider: str, host: str = None, api_key: str = None):
    """
    Check whether an LLM provider is reachable and ready.
    Returns {ok, models, hint} where hint is a human-readable fix if not ok.
    """
    try:
        if provider == "lmstudio":
            from open_codex.agents.lmstudio_agent import LMStudioAgent
            agent = LMStudioAgent(system_prompt="", host=host or "http://localhost:1234")
            return agent.health()

        elif provider in ("ollama", "ollama_cloud"):
            from open_codex.agents.ollama_agent import OllamaAgent
            from open_codex.agent_builder import _sanitize_ollama_host
            default_host  = "https://ollama.com" if provider == "ollama_cloud" else "http://localhost:11434"
            default_model = "qwen3-coder:480b-cloud" if provider == "ollama_cloud" else "llama3"
            agent = OllamaAgent(
                system_prompt="",
                model_name=default_model,
                host=_sanitize_ollama_host(host or default_host),
                api_key=api_key,
            )
            return agent.health()

        elif provider == "phi":
            return {"ok": True, "hint": None, "note": "Phi-4-mini loads on first use"}

        elif provider == "gemini":
            from open_codex.agents.gemini_agent import GeminiAgent
            key = api_key or os.getenv("GEMINI_API_KEY", "")
            agent = GeminiAgent(
                system_prompt="",
                model_name=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
                api_key=key,
            )
            return agent.health()

        elif provider in ("openai", "anthropic", "deepseek", "groq",
                          "openrouter", "together", "mistral", "xai",
                          "huggingface", "openai_compat"):
            from open_codex.agents.openai_compat_agent import OpenAICompatAgent, PROVIDER_CONFIGS
            # Each provider has a known env var fallback
            _ENV_KEYS = {
                "openai":      "OPENAI_API_KEY",
                "anthropic":   "ANTHROPIC_API_KEY",
                "deepseek":    "DEEPSEEK_API_KEY",
                "groq":        "GROQ_API_KEY",
                "openrouter":  "OPENROUTER_API_KEY",
                "together":    "TOGETHER_API_KEY",
                "mistral":     "MISTRAL_API_KEY",
                "xai":         "XAI_API_KEY",
                "huggingface": "HUGGINGFACE_API_TOKEN",
            }
            key = api_key or os.getenv(_ENV_KEYS.get(provider, ""), "")
            base_url = host or None
            if provider == "anthropic":
                base_url = base_url or "https://api.anthropic.com/v1"
            agent = OpenAICompatAgent(
                system_prompt="", provider=provider, api_key=key, base_url=base_url
            )
            return agent.health()

        else:
            return {"ok": False, "hint": f"Unknown provider: {provider}"}

    except HTTPException:
        raise
    except Exception as e:
        return {"ok": False, "hint": str(e)}


# ── Legacy one-shot generate (CLI compat) ────────────────────────────────────

@app.get("/api/models")
async def list_models(source: str, host: str = None):
    try:
        if source == "lmstudio":
            from open_codex.agents.lmstudio_agent import LMStudioAgent
            agent = LMStudioAgent(system_prompt="", host=host or "http://localhost:1234")
            return {"models": agent._get_available_models()}
        elif source == "ollama":
            import ollama
            client = ollama.Client(host=host or "http://localhost:11434")
            return {"models": [m.model for m in client.list().models if m.model]}
        elif source == "ollama_cloud":
            try:
                import ollama
                cloud_host = host or "https://ollama.com"
                client = ollama.Client(host=cloud_host)
                cloud_models = [m.model for m in client.list().models if m.model]
                if cloud_models:
                    return {"models": sorted(cloud_models)}
            except Exception:
                pass
            # Fallback to known-good cloud model list
            return {"models": [
                "qwen3-coder:480b-cloud", "qwen3.5:latest-cloud", "qwen3:235b-a22b-cloud",
                "deepseek-v3.1:671b-cloud", "deepseek-r2:671b-cloud",
                "llama4:maverick-cloud", "llama4:scout-cloud", "llama3.3:70b-cloud",
                "mistral:latest-cloud", "gemma3:27b-cloud", "phi4:cloud",
                "ministral-3:latest-cloud", "ministral-8:latest-cloud",
                "command-r-plus:cloud", "command-a:cloud",
            ]}
        elif source == "gemini":
            return {"models": ["gemini-2.5-pro", "gemini-2.5-flash",
                               "gemini-2.0-flash", "gemini-2.0-flash-lite"]}
        return {"models": []}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/generate")
async def generate_command(req: GenerateRequest):
    try:
        if req.agent_type == "phi":
            agent = AgentBuilder.get_phi_agent()
        elif req.agent_type == "lmstudio":
            agent = AgentBuilder.get_lmstudio_agent(req.model, req.host or "http://localhost:1234")
        elif req.agent_type == "ollama":
            agent = AgentBuilder.get_ollama_agent(
                req.model or "llama3",
                req.host or "http://localhost:11434",
            )
        elif req.agent_type == "ollama_cloud":
            agent = AgentBuilder.get_ollama_agent(
                req.model or "qwen3-coder:480b-cloud",
                req.host or "https://ollama.com",   # no /api — SDK adds it
                req.api_key,
            )
        elif req.agent_type == "gemini":
            agent = AgentBuilder.get_gemini_agent(req.model, req.api_key)
        else:
            raise HTTPException(400, "Invalid agent type")
        return {"command": agent.one_shot_mode(req.prompt)}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/execute")
async def execute_command(req: ExecuteRequest):
    try:
        cwd = req.cwd or os.getcwd()
        r = subprocess.run(req.command, shell=True, cwd=cwd, capture_output=True, text=True, timeout=30)
        return {"stdout": r.stdout, "stderr": r.stderr, "return_code": r.returncode}
    except subprocess.TimeoutExpired:
        raise HTTPException(408, "Command timed out")
    except Exception as e:
        raise HTTPException(500, str(e))


# ── MCP Hub endpoints ─────────────────────────────────────────────────────────

class MCPCallRequest(BaseModel):
    server_id: str
    tool: str
    params: dict = {}
    project_dir: Optional[str] = None


class MCPConfigRequest(BaseModel):
    config: dict  # {key: value} env / settings to merge


@app.get("/api/mcp/servers")
async def mcp_list_servers():
    """Return all registered MCP servers with tool manifests and health status."""
    servers = _mcp_bridge.all_servers()
    return {
        "servers": [
            {
                "id": s.id,
                "name": s.name,
                "category": s.category,
                "icon": s.icon,
                "description": s.description,
                "healthy": s.healthy,
                "tool_count": len(s.tools),
                "removable": getattr(s, "removable", False),
                "tools": [
                    {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    }
                    for t in s.tools
                ],
                "config_keys": [k for k in s.config.keys()],
                "config_set": {k: bool(v) for k, v in s.config.items()},
            }
            for s in servers
        ],
        "total_tools": sum(len(s.tools) for s in servers),
    }


@app.delete("/api/mcp/servers/{server_id}")
async def mcp_remove_server(server_id: str):
    """Remove any custom/removable MCP server (repo or user-added)."""
    srv = _mcp_bridge.get(server_id)
    if srv is None:
        raise HTTPException(status_code=404, detail=f"Server '{server_id}' not found.")
    if not getattr(srv, "removable", False):
        raise HTTPException(status_code=403,
                            detail=f"Server '{server_id}' is a built-in server and cannot be removed.")
    # If it's a repo server, also clean up the cloned files
    if server_id.startswith("repo_"):
        from open_codex.mcp_servers_repo import remove_repo
        # slug is everything after 'repo_'
        remove_repo(_mcp_bridge, server_id[len("repo_"):])
    else:
        _mcp_bridge.unregister(server_id)
    return {"ok": True, "removed": server_id}


@app.post("/api/mcp/call")
async def mcp_call_tool(req: MCPCallRequest):
    """Call a specific MCP tool on a registered server."""
    project_dir = req.project_dir or os.getcwd()
    # Run blocking call in thread pool to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: _mcp_bridge.call(req.server_id, req.tool, req.params, project_dir),
    )
    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@app.patch("/api/mcp/servers/{server_id}/config")
async def mcp_configure_server(server_id: str, req: MCPConfigRequest):
    """Update configuration (env vars / credentials) for an MCP server."""
    srv = _mcp_bridge.get(server_id)
    if not srv:
        raise HTTPException(404, f"MCP server not found: {server_id}")
    _mcp_bridge.configure(server_id, req.config)
    return {"status": "updated", "server_id": server_id, "keys_set": list(req.config.keys())}


@app.get("/api/mcp/servers/{server_id}/health")
async def mcp_server_health(server_id: str):
    """Run a health check on a specific MCP server."""
    srv = _mcp_bridge.get(server_id)
    if not srv:
        raise HTTPException(404, f"MCP server not found: {server_id}")
    loop = asyncio.get_event_loop()
    healthy = await loop.run_in_executor(None, srv.health_check)
    srv.healthy = healthy
    return {"server_id": server_id, "healthy": healthy}


@app.get("/api/mcp/manifest")
async def mcp_manifest():
    """Return flat tool manifest for injecting into agent system prompts."""
    return {"tools": _mcp_bridge.tool_manifest()}


# ── Browser Agent (AIO-NUI) endpoints ─────────────────────────────────────────

class BrowserRunRequest(BaseModel):
    task: str
    agent_type: str = "ollama"     # same providers as chat
    model: Optional[str] = None
    host: Optional[str] = None
    api_key: Optional[str] = None
    start_url: Optional[str] = None
    headless: bool = False          # False = headed (user can watch the browser live)
    project_dir: Optional[str] = None
    prior_context: Optional[str] = None  # summary from a previous session for continuity


# Active browser sessions: session_id -> abort threading.Event
_active_browser_sessions: dict[str, threading.Event] = {}


@app.post("/api/browser/run")
async def browser_run(req: BrowserRunRequest):
    """
    Launch the AIO-NUI autonomous browser agent and stream
    SSE frame events (base64 JPEG screenshots + logs) in real-time.
    """
    import uuid
    session_id = str(uuid.uuid4())
    abort_event = threading.Event()
    _active_browser_sessions[session_id] = abort_event

    loop = asyncio.get_event_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def run_browser():
        try:
            from open_codex.agents.browser_agent import BrowserAgent
            caller = AgentBuilder.get_llm_caller(
                req.agent_type, req.model, req.host, req.api_key
            )
            agent = BrowserAgent(
                llm_caller=caller,
                headless=req.headless,
            )
            for event in agent.run(
                task=req.task,
                start_url=req.start_url,
                abort_event=abort_event,
                prior_context=req.prior_context,
            ):
                if abort_event.is_set():
                    break
                loop.call_soon_threadsafe(queue.put_nowait, json.dumps(event))
        except Exception as e:
            loop.call_soon_threadsafe(
                queue.put_nowait,
                json.dumps({"type": "error", "content": str(e)})
            )
        finally:
            _active_browser_sessions.pop(session_id, None)
            loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=run_browser, daemon=True).start()

    async def generate():
        # Send session_id first so the client can abort
        yield f"data: {json.dumps({'type': 'session_id', 'session_id': session_id})}\n\n"
        while True:
            item = await queue.get()
            if item is None:
                break
            yield f"data: {item}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/browser/abort/{session_id}")
async def browser_abort(session_id: str):
    """Signal a running browser session to stop."""
    ev = _active_browser_sessions.get(session_id)
    if ev is None:
        raise HTTPException(404, f"No active browser session: {session_id}")
    ev.set()
    return {"status": "abort_requested", "session_id": session_id}


@app.get("/api/browser/sessions")
async def browser_sessions():
    """List IDs of all currently active browser sessions."""
    return {"sessions": list(_active_browser_sessions.keys())}


# ── Auto-MCPilot endpoints ────────────────────────────────────────────────────

class AutopilotToggleReq(BaseModel):
    enabled:      bool
    interval_min: int = 10

@app.post("/api/autopilot/toggle")
async def autopilot_toggle(req: AutopilotToggleReq):
    """Enable or disable the Auto-MCPilot background trainer."""
    status = _autopilot.toggle(
        enabled=req.enabled,
        bridge=_mcp_bridge,
        config=_autopilot_config,
        interval_min=req.interval_min,
    )
    return status

@app.get("/api/autopilot/status")
async def autopilot_status():
    return _autopilot.get_status()

@app.get("/api/autopilot/log")
async def autopilot_log(n: int = 100):
    return {"events": _autopilot.load_log(n)}

@app.post("/api/autopilot/run")
async def autopilot_run_now():
    """Trigger an immediate autopilot cycle regardless of the timer."""
    _autopilot.run_now(_mcp_bridge, _autopilot_config)
    return {"triggered": True}

@app.get("/api/autopilot/stream")
async def autopilot_stream():
    """SSE stream — yields autopilot events as they happen."""
    async def _gen():
        async for event in _autopilot.subscribe():
            yield f"data: {json.dumps(event)}\n\n"
    return StreamingResponse(_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# Restore autopilot on startup using an app lifespan event
@app.on_event("startup")
async def _restore_autopilot():
    saved = _autopilot.get_status()
    if saved.get("enabled"):
        _autopilot.toggle(
            enabled=True,
            bridge=_mcp_bridge,
            config=_autopilot_config,
            interval_min=saved.get("interval_min", 10),
        )


# ── Serve built frontend ──────────────────────────────────────────────────────

_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(_static_dir):
    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

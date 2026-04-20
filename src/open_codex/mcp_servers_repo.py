"""
RepoMCP — GitHub-to-MCP Intelligent Toolification Engine v2
============================================================

Transforms any cloned GitHub repo into a fully intelligent MCP server with
14 purpose-built tools that go far beyond file reading:

NAVIGATION & READING
  repo_<n>_info()              Manifest + detected capabilities summary
  repo_<n>_tree(max_files)     Smart file tree with size+language annotation
  repo_<n>_read(path, lines?)  Read file — optional line range, auto-truncate
  repo_<n>_search(pattern, glob?, case_sensitive?)  Regex search across codebase

CODE INTELLIGENCE
  repo_<n>_symbols(file_path?) AST-extract all functions/classes/methods with
                                signatures, docstrings, and line numbers
  repo_<n>_api_surface()       Full public API: exported callables + signatures
  repo_<n>_deps()              Parsed dependency list from any manifest format
  repo_<n>_summarize(path?)    AI-powered narrative summary of a file or repo

EXECUTION
  repo_<n>_run(command, timeout?)        Shell command in repo dir (safe-guarded)
  repo_<n>_call_py(module, function, kwargs?)  Import + invoke any Python fn
  repo_<n>_cli(args, timeout?)          Run the repo's CLI entrypoint safely
  repo_<n>_test(pattern?, timeout?)     Run the repo's test suite

GIT
  repo_<n>_log(n?)             Recent git commit history
  repo_<n>_diff(ref?)          Diff vs HEAD or a ref
  repo_<n>_pull()              Pull latest and refresh manifest
"""

from __future__ import annotations

import ast
import inspect
import importlib
import json
import logging
import os
import re
import subprocess
import shutil
import sys
import textwrap
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_REPOS_DIR = Path.home() / ".open_codex" / "repos"
_REPOS_DIR.mkdir(parents=True, exist_ok=True)
_MANIFEST_SUFFIX = ".manifest.json"

# ── slug / path helpers ────────────────────────────────────────────────────────

def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", name.lower()).strip("_")

def _repo_dir(name: str) -> Path:
    return _REPOS_DIR / _slug(name)

def _manifest_path(name: str) -> Path:
    return _REPOS_DIR / f"{_slug(name)}{_MANIFEST_SUFFIX}"

# ── file tree ──────────────────────────────────────────────────────────────────

_SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv",
              "dist", "build", ".next", ".cache", ".mypy_cache", ".pytest_cache",
              "target", "vendor", ".idea", ".vscode"}
_TEXT_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs",
    ".go", ".rs", ".rb", ".java", ".c", ".cpp", ".h", ".hpp",
    ".cs", ".swift", ".kt", ".scala", ".lua", ".php", ".r", ".jl",
    ".sh", ".bash", ".zsh", ".fish", ".ps1",
    ".md", ".txt", ".rst", ".adoc",
    ".yaml", ".yml", ".toml", ".json", ".jsonc", ".env.example",
    ".html", ".css", ".scss", ".sass", ".less",
    ".sql", ".graphql", ".proto", ".tf", ".hcl", ".nix",
    ".dockerfile", ".makefile",
}

def _file_tree(root: Path, max_files: int = 400, annotate: bool = False) -> list:
    results = []
    for p in sorted(root.rglob("*")):
        parts = p.parts[len(root.parts):]
        if any(part.startswith(".") or part in _SKIP_DIRS for part in parts):
            continue
        if p.is_file():
            if p.suffix.lower() in _TEXT_EXTS or p.name.lower() in ("makefile", "dockerfile", "gemfile"):
                if annotate:
                    try:
                        size = p.stat().st_size
                        results.append({"path": str(p.relative_to(root)),
                                        "size": size, "ext": p.suffix})
                    except Exception:
                        results.append(str(p.relative_to(root)))
                else:
                    results.append(str(p.relative_to(root)))
                if len(results) >= max_files:
                    break
    return results


# ── stack detection (enhanced) ─────────────────────────────────────────────────

def _detect_stack(tree: list[str]) -> dict:
    names = set(tree)
    flat  = " ".join(names)
    langs: list[str] = []

    if any("setup.py" in f or "pyproject.toml" in f or "requirements" in f for f in names):
        langs.append("python")
    if any("package.json" in f for f in names) and ".node_modules" not in flat:
        langs.append("javascript/typescript")
    if "go.mod" in names:
        langs.append("go")
    if "Cargo.toml" in names:
        langs.append("rust")
    if any(f.endswith(".rb") for f in names):
        langs.append("ruby")
    if any(f.endswith(".java") for f in names):
        langs.append("java")
    if any(f.endswith(".cs") for f in names):
        langs.append("csharp")
    if any(f.endswith(".php") for f in names):
        langs.append("php")

    entry_points: list[str] = []
    for candidate in ("main.py", "app.py", "index.js", "index.ts", "main.go",
                      "main.rs", "manage.py", "server.py", "cli.py", "__main__.py",
                      "app.js", "server.js", "index.php"):
        if any(f == candidate or f.endswith("/" + candidate) for f in names):
            entry_points.append(candidate)

    # CLI detection
    has_cli = any(f in names or f.endswith("/cli.py") or f.endswith("/__main__.py")
                  for f in ("cli.py", "__main__.py", "cli.js", "cli.ts"))
    # Test framework detection
    test_cmd = None
    if any("pytest" in f or "conftest" in f for f in names):
        test_cmd = "pytest"
    elif any("jest.config" in f for f in names):
        test_cmd = "npx jest"
    elif any("test/" in f for f in names):
        test_cmd = "go test ./..."

    # pkg manager
    pkg_manager = None
    if any("package.json" in f for f in names):
        pkg_manager = "npm"
    elif any("Cargo.toml" in f for f in names):
        pkg_manager = "cargo"
    elif any("go.mod" in f for f in names):
        pkg_manager = "go"

    return {
        "languages":    langs or ["unknown"],
        "entry_points": entry_points,
        "pkg_manager":  pkg_manager,
        "has_docker":   any("dockerfile" in f.lower() for f in names),
        "has_cli":      has_cli,
        "test_cmd":     test_cmd,
        "readme":       next((f for f in names if Path(f).name.lower().startswith("readme")), None),
        "is_python_pkg": any("setup.py" in f or "pyproject.toml" in f for f in names),
    }


def _read_readme(root: Path, tree: list[str]) -> str:
    for candidate in tree:
        if Path(candidate).name.lower().startswith("readme"):
            try:
                return (root / candidate).read_text(errors="replace")[:5000]
            except Exception:
                pass
    return ""


# ── AST symbol extraction (Python) ────────────────────────────────────────────

def _extract_python_symbols(source: str, filepath: str = "") -> list[dict]:
    """Return all functions, classes, and methods with signatures + docstrings."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [{"error": str(e)}]

    results = []

    def _sig(node: ast.FunctionDef) -> str:
        args = []
        defaults = [ast.unparse(d) for d in node.args.defaults]
        all_args = node.args.args
        offset = len(all_args) - len(defaults)
        for i, arg in enumerate(all_args):
            ann = f": {ast.unparse(arg.annotation)}" if arg.annotation else ""
            default = f" = {defaults[i - offset]}" if i >= offset else ""
            args.append(f"{arg.arg}{ann}{default}")
        if node.args.vararg:
            args.append(f"*{node.args.vararg.arg}")
        if node.args.kwarg:
            args.append(f"**{node.args.kwarg.arg}")
        ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
        return f"({', '.join(args)}){ret}"

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            is_private = node.name.startswith("__") and node.name.endswith("__")
            doc = ast.get_docstring(node) or ""
            results.append({
                "type":     "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function",
                "name":     node.name,
                "signature": _sig(node),
                "docstring": doc[:300] if doc else None,
                "line":     node.lineno,
                "file":     filepath,
                "private":  node.name.startswith("_"),
                "dunder":   is_private,
            })
        elif isinstance(node, ast.ClassDef):
            doc = ast.get_docstring(node) or ""
            methods = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    methods.append(item.name)
            results.append({
                "type":     "class",
                "name":     node.name,
                "methods":  methods,
                "docstring": doc[:300] if doc else None,
                "line":     node.lineno,
                "file":     filepath,
            })

    return results


def _extract_js_symbols(source: str, filepath: str = "") -> list[dict]:
    """Simple regex-based JS/TS symbol extraction."""
    results = []
    # function declarations + arrow functions assigned to const/let
    fn_pattern = re.compile(
        r"(?:export\s+)?(?:async\s+)?function\s+(\w+)\s*\(([^)]*)\)"
        r"|(?:export\s+)?const\s+(\w+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>"
        r"|export\s+(?:default\s+)?class\s+(\w+)",
        re.MULTILINE,
    )
    for m in fn_pattern.finditer(source):
        name = m.group(1) or m.group(3) or m.group(5)
        params = m.group(2) or m.group(4) or ""
        kind = "class" if m.group(5) else "function"
        line = source[:m.start()].count("\n") + 1
        results.append({"type": kind, "name": name, "signature": f"({params})",
                        "line": line, "file": filepath})
    return results


def _extract_symbols(root: Path, file_path: Optional[str] = None) -> list[dict]:
    """Extract symbols from one file or scan the whole repo."""
    all_symbols: list[dict] = []
    if file_path:
        targets = [root / file_path]
    else:
        # Scan top-level + src/ directory Python/JS files
        targets = []
        for f in _file_tree(root, max_files=60):
            p = root / f
            if p.suffix in (".py", ".js", ".ts", ".jsx", ".tsx") and p.stat().st_size < 200_000:
                targets.append(p)

    for target in targets:
        if not target.is_file():
            continue
        rel = str(target.relative_to(root))
        try:
            source = target.read_text(errors="replace")
        except Exception:
            continue
        if target.suffix == ".py":
            all_symbols.extend(_extract_python_symbols(source, rel))
        elif target.suffix in (".js", ".ts", ".jsx", ".tsx"):
            all_symbols.extend(_extract_js_symbols(source, rel))

    return all_symbols


# ── dependency parsing ─────────────────────────────────────────────────────────

def _parse_deps(root: Path) -> dict:
    deps: dict[str, list] = {}

    # requirements.txt
    for req_file in root.glob("requirements*.txt"):
        lines = req_file.read_text(errors="replace").splitlines()
        deps[req_file.name] = [
            l.strip() for l in lines
            if l.strip() and not l.startswith("#")
        ]

    # pyproject.toml
    pp = root / "pyproject.toml"
    if pp.exists():
        content = pp.read_text(errors="replace")
        # naive extraction of [project.dependencies]
        m = re.search(r"\[project\.dependencies\](.*?)(?=\n\[|\Z)", content, re.DOTALL)
        if m:
            deps["pyproject.toml"] = re.findall(r'"([^"]+)"', m.group(1))

    # setup.py install_requires
    sp = root / "setup.py"
    if sp.exists():
        content = sp.read_text(errors="replace")
        m = re.search(r"install_requires\s*=\s*\[(.*?)\]", content, re.DOTALL)
        if m:
            deps["setup.py"] = re.findall(r"[\"']([^\"']+)[\"']", m.group(1))

    # package.json
    pj = root / "package.json"
    if pj.exists():
        try:
            data = json.loads(pj.read_text())
            pkgs = {}
            pkgs.update(data.get("dependencies", {}))
            pkgs.update(data.get("devDependencies", {}))
            deps["package.json"] = list(pkgs.keys())
        except Exception:
            pass

    # go.mod
    gm = root / "go.mod"
    if gm.exists():
        content = gm.read_text(errors="replace")
        deps["go.mod"] = re.findall(r"^\s+(\S+)\s+v\S+", content, re.MULTILINE)

    # Cargo.toml
    ct = root / "Cargo.toml"
    if ct.exists():
        content = ct.read_text(errors="replace")
        m = re.search(r"\[dependencies\](.*?)(?=\n\[|\Z)", content, re.DOTALL)
        if m:
            deps["Cargo.toml"] = re.findall(r"^(\w+)\s*=", m.group(1), re.MULTILINE)

    return deps


# ── AI query router ────────────────────────────────────────────────────────────

def _ai_query(prompt: str, config: dict, max_tokens: int = 1200) -> str:
    provider = (config.get("AI_PROVIDER") or "ollama").lower()
    try:
        if provider == "ollama":
            import ollama as _ollama
            host  = re.sub(r"/api/?$", "", config.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/"))
            model = config.get("OLLAMA_MODEL", "llama3")
            oc    = _ollama.Client(host=host)
            resp  = oc.chat(model=model,
                            messages=[{"role": "user", "content": prompt}],
                            options={"num_predict": max_tokens, "temperature": 0.25})
            return resp["message"]["content"].strip()
        elif provider in ("lmstudio", "ollama_cloud"):
            import httpx
            if provider == "lmstudio":
                base  = config.get("LMSTUDIO_HOST", "http://localhost:1234").rstrip("/")
                model = config.get("LMSTUDIO_MODEL", "local-model")
            else:
                base  = "https://openai.com/v1"
                model = config.get("OLLAMA_CLOUD_MODEL", "gpt-4o-mini")
            r = httpx.post(f"{base}/v1/chat/completions", json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens, "temperature": 0.25,
            }, timeout=90)
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
        elif provider == "gemini":
            import google.generativeai as genai
            genai.configure(api_key=config.get("GEMINI_API_KEY", ""))
            m   = genai.GenerativeModel(config.get("GEMINI_MODEL", "gemini-2.0-flash"))
            res = m.generate_content(prompt)
            return res.text.strip()
        else:
            return "(No AI provider configured for repo queries — set AI_PROVIDER env var)"
    except Exception as e:
        return f"(AI query failed [{provider}]: {e})"


# ── Git helpers ────────────────────────────────────────────────────────────────

def _git(root: Path, *args, timeout: int = 30) -> str:
    try:
        r = subprocess.run(["git", "-C", str(root)] + list(args),
                           capture_output=True, text=True, timeout=timeout)
        return (r.stdout or r.stderr or "").strip()
    except Exception as e:
        return f"git error: {e}"


# ── Registry ───────────────────────────────────────────────────────────────────

_registry: dict[str, "RepoMCPServer"] = {}

def list_repos() -> list[dict]:
    out = []
    for p in sorted(_REPOS_DIR.glob(f"*{_MANIFEST_SUFFIX}")):
        try:
            out.append(json.loads(p.read_text()))
        except Exception:
            pass
    return out

def get_repo(name: str) -> Optional["RepoMCPServer"]:
    return _registry.get(_slug(name))


# ── NativeMCPServer with full toolset ─────────────────────────────────────────

class RepoMCPServer:
    """Wraps a cloned GitHub repo as a fully intelligent MCP server."""

    def __init__(self, bridge: Any, manifest: dict) -> None:
        from open_codex.mcp_bridge import NativeMCPServer, MCPTool

        slug   = manifest["slug"]
        name   = manifest["name"]
        url    = manifest["url"]
        root   = Path(manifest["local_path"])
        config = manifest.get("ai_config", {})
        langs  = manifest.get("languages", [])
        self.manifest = manifest

        _BLOCKED_CMD = re.compile(
            r"\b(rm\s+-rf|rmdir|mkfs|dd\s|format\s|shutdown|reboot"
            r"|>\s*/dev|curl\s+-o\s|wget\s+-O\s)\b"
        )

        def _safe_resolve(rel: str) -> tuple[Path, str | None]:
            target = (root / rel).resolve()
            if not str(target).startswith(str(root.resolve())):
                return target, "Error: path traversal blocked."
            return target, None

        class _RServer(NativeMCPServer):
            def __init__(s):
                tool_list = ", ".join([
                    "info", "tree", "read", "search", "symbols", "api_surface",
                    "deps", "summarize", "run", "call_py", "cli", "test", "log", "diff", "pull",
                ])
                super().__init__(
                    removable=True,
                    id=f"repo_{slug}",
                    name=f"🛸 {name}",
                    category="repos",
                    icon="🛸",
                    description=(
                        f"Repo '{name}' ({url}) · Stack: {', '.join(langs)}. "
                        f"15 tools: {tool_list}."
                    ),
                )

                def T(tname: str, desc: str, params: dict) -> MCPTool:
                    return MCPTool(tname, desc, params, f"repo_{slug}")

                # ── info ──────────────────────────────────────────────────────
                s._register_tool(f"repo_{slug}_info",
                    lambda p, _d: json.dumps(manifest, indent=2),
                    T(f"repo_{slug}_info",
                      f"Full manifest and detected capabilities for '{name}'.", {}))

                # ── tree ──────────────────────────────────────────────────────
                s._register_tool(f"repo_{slug}_tree",
                    lambda p, _d: json.dumps({"files": _file_tree(root, int(p.get("max_files", 300)))}),
                    T(f"repo_{slug}_tree",
                      f"Annotated file tree for '{name}' repo.",
                      {"max_files": {"type": "integer", "description": "Max files to list (default 300)"}}))

                # ── read ──────────────────────────────────────────────────────
                s._register_tool(f"repo_{slug}_read", s._read,
                    T(f"repo_{slug}_read",
                      f"Read a file from '{name}' repo with optional line range.",
                      {"path":       {"type": "string",  "required": True,
                                      "description": "Relative path inside repo"},
                       "start_line": {"type": "integer", "description": "Start line (1-indexed)"},
                       "end_line":   {"type": "integer", "description": "End line (inclusive)"}}))

                # ── search ────────────────────────────────────────────────────
                s._register_tool(f"repo_{slug}_search", s._search,
                    T(f"repo_{slug}_search",
                      f"Regex search across '{name}' codebase. Returns file:line:match hits.",
                      {"pattern":        {"type": "string", "required": True,
                                          "description": "Regex or literal pattern"},
                       "glob":           {"type": "string", "description": "File glob e.g. '*.py'"},
                       "case_sensitive": {"type": "boolean"}}))

                # ── symbols ───────────────────────────────────────────────────
                s._register_tool(f"repo_{slug}_symbols", s._symbols,
                    T(f"repo_{slug}_symbols",
                      f"Extract functions, classes, and methods from '{name}' with signatures and docstrings.",
                      {"file_path": {"type": "string",
                                     "description": "Specific file path (omit for full repo scan)"},
                       "public_only": {"type": "boolean",
                                       "description": "Only return public (non-underscore) symbols"}}))

                # ── api_surface ───────────────────────────────────────────────
                s._register_tool(f"repo_{slug}_api_surface", s._api_surface,
                    T(f"repo_{slug}_api_surface",
                      f"Extract the full public API surface of '{name}' — all exported callables with descriptions.",
                      {}))

                # ── deps ──────────────────────────────────────────────────────
                s._register_tool(f"repo_{slug}_deps",
                    lambda p, _d: json.dumps(_parse_deps(root), indent=2),
                    T(f"repo_{slug}_deps",
                      f"Parse all dependency manifests in '{name}' (requirements.txt, package.json, Cargo.toml, etc).",
                      {}))

                # ── summarize ─────────────────────────────────────────────────
                s._register_tool(f"repo_{slug}_summarize", s._summarize,
                    T(f"repo_{slug}_summarize",
                      f"AI-powered narrative summary of '{name}' or a specific file inside it.",
                      {"path": {"type": "string",
                                "description": "Specific file to summarize (omit for whole-repo summary)"}}))

                # ── run ───────────────────────────────────────────────────────
                s._register_tool(f"repo_{slug}_run", s._run,
                    T(f"repo_{slug}_run",
                      f"Run a shell command inside '{name}' repo directory. "
                      "Destructive commands are blocked.",
                      {"command": {"type": "string",  "required": True},
                       "timeout": {"type": "integer", "description": "Seconds (default 30)"}}))

                # ── call_py ───────────────────────────────────────────────────
                if "python" in langs:
                    s._register_tool(f"repo_{slug}_call_py", s._call_py,
                        T(f"repo_{slug}_call_py",
                          f"Import a Python module from '{name}' and invoke a function directly. "
                          "Requires the repo to be importable (pure Python, no compiled extensions).",
                          {"module":   {"type": "string", "required": True,
                                        "description": "Dotted module path e.g. 'mylib.utils'"},
                           "function": {"type": "string", "required": True,
                                        "description": "Function name to call"},
                           "kwargs":   {"type": "object",
                                        "description": "JSON object of keyword arguments"}}))

                # ── cli ───────────────────────────────────────────────────────
                if manifest.get("has_cli") or manifest.get("entry_points"):
                    s._register_tool(f"repo_{slug}_cli", s._cli,
                        T(f"repo_{slug}_cli",
                          f"Run '{name}' CLI entrypoint with given args. Auto-detects __main__.py / CLI module.",
                          {"args":    {"type": "string", "description": "CLI arguments string"},
                           "timeout": {"type": "integer"}}))

                # ── test ──────────────────────────────────────────────────────
                s._register_tool(f"repo_{slug}_test", s._test,
                    T(f"repo_{slug}_test",
                      f"Run the '{name}' test suite. Auto-detects pytest / jest / go test.",
                      {"pattern": {"type": "string",
                                   "description": "Test filter/pattern (passed to test runner)"},
                       "timeout": {"type": "integer", "description": "Seconds (default 60)"}}))

                # ── log ───────────────────────────────────────────────────────
                s._register_tool(f"repo_{slug}_log",
                    lambda p, _d: _git(root, "log", "--oneline", f"-{int(p.get('n', 20))}"),
                    T(f"repo_{slug}_log",
                      f"Recent git commit history for '{name}'.",
                      {"n": {"type": "integer", "description": "Number of commits (default 20)"}}))

                # ── diff ──────────────────────────────────────────────────────
                s._register_tool(f"repo_{slug}_diff",
                    lambda p, _d: _git(root, "diff", p.get("ref", "HEAD"))[:6000],
                    T(f"repo_{slug}_diff",
                      f"Git diff for '{name}' vs HEAD or a given ref.",
                      {"ref": {"type": "string", "description": "Git ref/branch/SHA (default: HEAD)"}}))

                # ── pull ──────────────────────────────────────────────────────
                s._register_tool(f"repo_{slug}_pull", s._pull,
                    T(f"repo_{slug}_pull",
                      f"Pull latest changes for '{name}' and refresh the manifest + symbol cache.",
                      {}))

            # ── tool implementations ───────────────────────────────────────────

            def _read(s, p: dict, _d: str = ".") -> str:
                rel = p.get("path", "")
                target, err = _safe_resolve(rel)
                if err:
                    return err
                if not target.exists():
                    return f"Error: '{rel}' not found in repo."
                try:
                    lines = target.read_text(errors="replace").splitlines()
                    start = max(0, int(p.get("start_line", 1)) - 1)
                    end   = int(p.get("end_line", len(lines)))
                    chunk = "\n".join(lines[start:end])
                    if len(chunk) > 10_000:
                        chunk = chunk[:10_000] + f"\n\n… (truncated, {len(lines)} total lines)"
                    return chunk
                except Exception as e:
                    return f"Error reading file: {e}"

            def _search(s, p: dict, _d: str = ".") -> str:
                pattern = p.get("pattern", "")
                if not pattern:
                    return "Error: pattern required."
                glob   = p.get("glob", "")
                flags  = 0 if p.get("case_sensitive") else re.IGNORECASE
                try:
                    compiled = re.compile(pattern, flags)
                except re.error as e:
                    return f"Error: invalid regex — {e}"
                results = []
                tree = _file_tree(root, max_files=500)
                for rel in tree:
                    if glob:
                        from fnmatch import fnmatch
                        if not fnmatch(Path(rel).name, glob):
                            continue
                    target = root / rel
                    try:
                        for i, line in enumerate(target.read_text(errors="replace").splitlines(), 1):
                            if compiled.search(line):
                                results.append(f"{rel}:{i}: {line.strip()[:120]}")
                                if len(results) >= 80:
                                    results.append("… (stopped at 80 matches)")
                                    return "\n".join(results)
                    except Exception:
                        pass
                return "\n".join(results) if results else f"No matches for '{pattern}'."

            def _symbols(s, p: dict, _d: str = ".") -> str:
                file_path = p.get("file_path", "")
                public_only = bool(p.get("public_only", False))
                syms = _extract_symbols(root, file_path or None)
                if public_only:
                    syms = [sym for sym in syms if not sym.get("private")]
                return json.dumps(syms, indent=2)

            def _api_surface(s, p: dict, _d: str = ".") -> str:
                syms = _extract_symbols(root)
                # Public callables only
                public = [
                    sym for sym in syms
                    if sym.get("type") in ("function", "async_function", "class")
                    and not sym.get("private")
                    and not sym.get("dunder")
                ]
                # Format as clean API doc
                lines = [f"# Public API Surface — {name}\n"]
                for sym in public[:100]:
                    t = sym["type"]
                    sig = sym.get("signature", "")
                    doc = sym.get("docstring") or ""
                    lines.append(f"## {sym['name']}{sig}  [{t}] @ {sym['file']}:{sym['line']}")
                    if doc:
                        lines.append(f"   {doc[:200]}")
                    lines.append("")
                return "\n".join(lines) if len(lines) > 1 else "No public symbols found."

            def _summarize(s, p: dict, _d: str = ".") -> str:
                path = p.get("path", "").strip()
                if path:
                    target, err = _safe_resolve(path)
                    if err:
                        return err
                    try:
                        content = target.read_text(errors="replace")[:5000]
                    except Exception as e:
                        return f"Error: {e}"
                    syms = _extract_symbols(root, path)
                    sym_summary = json.dumps(syms[:20], indent=2) if syms else ""
                    prompt = (
                        f"Summarize the following file from the '{name}' repository.\n\n"
                        f"File: {path}\n\n"
                        f"Content:\n{content}\n\n"
                        + (f"Extracted symbols:\n{sym_summary}\n\n" if sym_summary else "")
                        + "Provide: (1) what this file does, (2) key functions/classes, "
                        "(3) how it fits into the broader codebase."
                    )
                else:
                    tree   = _file_tree(root, max_files=100)
                    readme = _read_readme(root, tree)
                    deps   = _parse_deps(root)
                    syms   = _extract_symbols(root)
                    pub    = [s for s in syms if not s.get("private")]
                    prompt = (
                        f"You are analyzing the GitHub repository '{name}' ({url}).\n\n"
                        f"README:\n{readme[:2000]}\n\n"
                        f"File tree ({len(tree)} files):\n" + "\n".join(tree[:60]) + "\n\n"
                        f"Dependencies: {json.dumps(deps, indent=1)[:800]}\n\n"
                        f"Public symbols (first 30): {json.dumps(pub[:30], indent=1)[:1000]}\n\n"
                        "Provide a comprehensive summary: (1) what does this repo do, "
                        "(2) architecture overview, (3) main entry points, "
                        "(4) how to use it as a library or tool, "
                        "(5) key strengths / interesting patterns."
                    )
                return _ai_query(prompt, config, max_tokens=1500)

            def _run(s, p: dict, _d: str = ".") -> str:
                cmd     = p.get("command", "").strip()
                timeout = int(p.get("timeout", 30))
                if not cmd:
                    return "Error: command required."
                if _BLOCKED_CMD.search(cmd):
                    return f"Error: '{cmd}' contains a blocked operation."
                try:
                    result = subprocess.run(
                        cmd, shell=True, capture_output=True, text=True,
                        cwd=str(root), timeout=timeout,
                        env={**os.environ, "PYTHONPATH": str(root)},
                    )
                    out = (result.stdout or "") + (result.stderr or "")
                    return out[:5000] or "(no output)"
                except subprocess.TimeoutExpired:
                    return f"Error: timed out after {timeout}s."
                except Exception as e:
                    return f"Error: {e}"

            def _call_py(s, p: dict, _d: str = ".") -> str:
                module   = p.get("module", "").strip()
                function = p.get("function", "").strip()
                kwargs   = p.get("kwargs", {})
                if not module or not function:
                    return "Error: module and function are required."
                if isinstance(kwargs, str):
                    try:
                        kwargs = json.loads(kwargs)
                    except Exception:
                        kwargs = {}
                # Add repo root + src/ to path temporarily
                extra_paths = [str(root), str(root / "src")]
                old_path = sys.path[:]
                try:
                    for ep in reversed(extra_paths):
                        if ep not in sys.path:
                            sys.path.insert(0, ep)
                    mod = importlib.import_module(module)
                    fn  = getattr(mod, function)
                    sig_str = str(inspect.signature(fn))
                    result  = fn(**kwargs)
                    return json.dumps({
                        "function":  f"{module}.{function}{sig_str}",
                        "kwargs":    kwargs,
                        "result":    str(result)[:3000],
                    }, indent=2)
                except ModuleNotFoundError as e:
                    return (
                        f"Error: module '{module}' not found.\n"
                        f"Tried paths: {extra_paths}\n"
                        f"Detail: {e}\n\n"
                        f"Tip: run `repo_{slug}_run` with `pip install -e .` first."
                    )
                except AttributeError:
                    return f"Error: '{function}' not found in module '{module}'."
                except Exception as e:
                    return f"Error calling {module}.{function}: {type(e).__name__}: {e}"
                finally:
                    sys.path = old_path

            def _cli(s, p: dict, _d: str = ".") -> str:
                args    = p.get("args", "").strip()
                timeout = int(p.get("timeout", 30))
                # Auto-detect CLI entry
                entry = None
                if (root / "__main__.py").exists():
                    entry = f"python -m {name.replace('-','_')}"
                elif (root / "cli.py").exists():
                    entry = "python cli.py"
                else:
                    for ep in manifest.get("entry_points", []):
                        if "main" in ep or "app" in ep or "cli" in ep:
                            entry = f"python {ep}"
                            break
                if not entry:
                    return (
                        f"No CLI entrypoint detected for '{name}'.\n"
                        f"Entry points found: {manifest.get('entry_points', [])}\n"
                        f"Use repo_{slug}_run with an explicit command instead."
                    )
                if _BLOCKED_CMD.search(args):
                    return "Error: blocked argument detected."
                cmd = f"{entry} {args}".strip()
                try:
                    r = subprocess.run(
                        cmd, shell=True, capture_output=True, text=True,
                        cwd=str(root), timeout=timeout,
                        env={**os.environ, "PYTHONPATH": str(root)},
                    )
                    return ((r.stdout or "") + (r.stderr or ""))[:5000] or "(no output)"
                except subprocess.TimeoutExpired:
                    return f"Error: CLI timed out after {timeout}s."
                except Exception as e:
                    return f"Error: {e}"

            def _test(s, p: dict, _d: str = ".") -> str:
                pattern = p.get("pattern", "")
                timeout = int(p.get("timeout", 60))
                # Auto-detect test runner
                test_cmd = manifest.get("test_cmd")
                if not test_cmd:
                    if (root / "pytest.ini").exists() or (root / "conftest.py").exists():
                        test_cmd = "pytest"
                    elif (root / "package.json").exists():
                        test_cmd = "npx --yes jest"
                    elif (root / "go.mod").exists():
                        test_cmd = "go test ./..."
                    else:
                        test_cmd = "pytest"   # fallback
                cmd = test_cmd
                if pattern:
                    if "pytest" in cmd:
                        cmd += f" -k {pattern!r}"
                    elif "jest" in cmd:
                        cmd += f" --testNamePattern={pattern!r}"
                try:
                    r = subprocess.run(
                        cmd, shell=True, capture_output=True, text=True,
                        cwd=str(root), timeout=timeout,
                        env={**os.environ, "PYTHONPATH": str(root)},
                    )
                    out = (r.stdout or "") + (r.stderr or "")
                    return out[:6000] or "(no output)"
                except subprocess.TimeoutExpired:
                    return f"Error: tests timed out after {timeout}s."
                except Exception as e:
                    return f"Error running tests: {e}"

            def _pull(s, p: dict, _d: str = ".") -> str:
                result = _git(root, "pull", "--ff-only", timeout=60)
                # Refresh manifest tree/stack
                try:
                    new_tree = _file_tree(root)
                    new_stack = _detect_stack(new_tree)
                    manifest.update({
                        "tree_sample":  new_tree[:50],
                        "languages":    new_stack["languages"],
                        "entry_points": new_stack["entry_points"],
                        "has_cli":      new_stack["has_cli"],
                        "test_cmd":     new_stack["test_cmd"],
                    })
                    _manifest_path(slug).write_text(json.dumps(manifest, indent=2))
                except Exception:
                    pass
                return result or "Already up to date."

        self._server = _RServer()
        bridge.register(self._server)
        _registry[slug] = self
        logger.info("RepoMCPServer '%s' registered — %d tools", name, 15)


# ── Public API ─────────────────────────────────────────────────────────────────

def add_repo(
    bridge: Any,
    url: str,
    name: Optional[str] = None,
    auth_token: Optional[str] = None,
    branch: Optional[str] = None,
    ai_config: Optional[dict] = None,
) -> dict:
    if not name:
        name = re.sub(r"\.git$", "", url.rstrip("/").split("/")[-1])
    slug = _slug(name)
    dest = _repo_dir(slug)

    clone_msg = _clone_repo(url, dest, branch, auth_token)

    tree    = _file_tree(dest)
    stack   = _detect_stack(tree)
    readme  = _read_readme(dest, tree)

    # Run symbol extraction on first add
    try:
        syms = _extract_symbols(dest)
        pub_syms = [s for s in syms if not s.get("private") and s.get("type") != "class"][:30]
    except Exception:
        pub_syms = []

    manifest: dict = {
        "slug":           slug,
        "name":           name,
        "url":            url,
        "branch":         branch,
        "local_path":     str(dest),
        "tree_sample":    tree[:50],
        "languages":      stack["languages"],
        "entry_points":   stack["entry_points"],
        "has_docker":     stack["has_docker"],
        "has_cli":        stack["has_cli"],
        "test_cmd":       stack["test_cmd"],
        "is_python_pkg":  stack["is_python_pkg"],
        "readme_excerpt": readme[:600],
        "public_symbols": pub_syms,
        "clone_status":   clone_msg,
        "ai_config":      ai_config or {},
    }

    _manifest_path(slug).write_text(json.dumps(manifest, indent=2))

    # Unregister old instance
    if slug in _registry:
        try:
            bridge._servers.pop(f"repo_{slug}", None)
        except Exception:
            pass

    RepoMCPServer(bridge, manifest)
    return manifest


def _clone_repo(url: str, dest: Path, branch: Optional[str], token: Optional[str]) -> str:
    if token:
        url = re.sub(r"https://", f"https://{token}@", url)
    if dest.exists():
        r = subprocess.run(["git", "-C", str(dest), "pull", "--ff-only"],
                           capture_output=True, text=True, timeout=60)
        return r.stdout.strip() or r.stderr.strip() or "already up to date"
    cmd = ["git", "clone", "--depth=1", "--single-branch"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [url, str(dest)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:800])
    return "cloned"


def remove_repo(bridge: Any, name: str) -> bool:
    slug = _slug(name)
    _registry.pop(slug, None)
    try:
        bridge._servers.pop(f"repo_{slug}", None)
    except Exception:
        pass
    mp = _manifest_path(slug)
    rd = _repo_dir(slug)
    if mp.exists():
        mp.unlink()
    if rd.exists():
        shutil.rmtree(rd, ignore_errors=True)
    return True


def reload_all(bridge: Any) -> int:
    count = 0
    for p in sorted(_REPOS_DIR.glob(f"*{_MANIFEST_SUFFIX}")):
        try:
            manifest = json.loads(p.read_text())
            root = Path(manifest["local_path"])
            if root.exists():
                RepoMCPServer(bridge, manifest)
                count += 1
            else:
                logger.warning("Repo '%s' dir missing — skipping", manifest.get("name"))
        except Exception as e:
            logger.warning("Failed to reload repo manifest %s: %s", p.name, e)
    return count

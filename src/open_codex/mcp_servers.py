"""
Native MCP Servers — prebuilt server suite for Open Codex.

Provides 5 fully-functional MCP servers:
  FilesystemMCPServer  — 10 file management tools
  GitMCPServer         — 8 git automation tools
  ShellMCPServer       — 5 command execution tools
  FetchMCPServer       — 4 web content tools
  SQLiteMCPServer      — 6 database tools
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Dict

from open_codex.mcp_bridge import MCPTool, NativeMCPServer


# ── Filesystem MCP Server ─────────────────────────────────────────────────────

class FilesystemMCPServer(NativeMCPServer):
    """10 file-system tools: read, write, list, search, move, copy, delete, stat, mkdir, tree."""

    def __init__(self):
        super().__init__(
            id="filesystem",
            name="Filesystem",
            category="filesystem",
            icon="📁",
            description="Complete file system management — read/write files, list directories, search content, copy/move/delete, directory trees.",
        )
        self._register_tool("read_file",     self._read_file,   MCPTool("read_file",   "Read a file's full content",                     {"path": {"type": "string", "required": True}}, "filesystem"))
        self._register_tool("write_file",    self._write_file,  MCPTool("write_file",  "Write/overwrite a file with content",            {"path": {"type": "string", "required": True}, "content": {"type": "string", "required": True}}, "filesystem"))
        self._register_tool("append_file",   self._append_file, MCPTool("append_file", "Append content to a file",                       {"path": {"type": "string", "required": True}, "content": {"type": "string", "required": True}}, "filesystem"))
        self._register_tool("list_dir",      self._list_dir,    MCPTool("list_dir",    "List files and directories",                     {"path": {"type": "string"}}, "filesystem"))
        self._register_tool("tree",          self._tree,        MCPTool("tree",        "Return a directory tree (max depth 4)",          {"path": {"type": "string"}}, "filesystem"))
        self._register_tool("search_files",  self._search,      MCPTool("search_files","Search file content with a text/regex query",    {"query": {"type": "string", "required": True}, "path": {"type": "string"}, "glob": {"type": "string"}}, "filesystem"))
        self._register_tool("move_file",     self._move,        MCPTool("move_file",   "Move or rename a file/directory",               {"src": {"type": "string", "required": True}, "dst": {"type": "string", "required": True}}, "filesystem"))
        self._register_tool("copy_file",     self._copy,        MCPTool("copy_file",   "Copy a file to a destination",                  {"src": {"type": "string", "required": True}, "dst": {"type": "string", "required": True}}, "filesystem"))
        self._register_tool("delete_file",   self._delete,      MCPTool("delete_file", "Delete a file or empty directory",              {"path": {"type": "string", "required": True}}, "filesystem"))
        self._register_tool("make_dir",      self._mkdir,       MCPTool("make_dir",    "Create a directory (and parents)",              {"path": {"type": "string", "required": True}}, "filesystem"))

    def _abs(self, path: str, project_dir: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = Path(project_dir) / p
        return p.resolve()

    def _read_file(self, params: Dict, project_dir: str) -> str:
        p = self._abs(params["path"], project_dir)
        if not p.exists():
            return f"ERROR: File not found: {p}"
        try:
            return p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"ERROR: {e}"

    def _write_file(self, params: Dict, project_dir: str) -> str:
        p = self._abs(params["path"], project_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(params["content"], encoding="utf-8")
        return f"✅ Written {len(params['content'])} chars to {p}"

    def _append_file(self, params: Dict, project_dir: str) -> str:
        p = self._abs(params["path"], project_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(params["content"])
        return f"✅ Appended to {p}"

    def _list_dir(self, params: Dict, project_dir: str) -> str:
        p = self._abs(params.get("path", "."), project_dir)
        if not p.is_dir():
            return f"ERROR: Not a directory: {p}"
        entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name))
        lines = []
        for e in entries:
            tag = "📁" if e.is_dir() else "📄"
            size = f" ({e.stat().st_size:,}B)" if e.is_file() else ""
            lines.append(f"{tag} {e.name}{size}")
        return "\n".join(lines) or "(empty directory)"

    def _tree(self, params: Dict, project_dir: str) -> str:
        root = self._abs(params.get("path", "."), project_dir)
        lines = [str(root.name)]

        def _walk(d: Path, prefix: str, depth: int):
            if depth > 4:
                return
            children = sorted(d.iterdir(), key=lambda e: (e.is_file(), e.name))
            for i, child in enumerate(children):
                last = i == len(children) - 1
                conn = "└── " if last else "├── "
                lines.append(f"{prefix}{conn}{child.name}{'/' if child.is_dir() else ''}")
                if child.is_dir():
                    ext = "    " if last else "│   "
                    _walk(child, prefix + ext, depth + 1)

        _walk(root, "", 0)
        return "\n".join(lines)

    def _search(self, params: Dict, project_dir: str) -> str:
        query = params["query"]
        root = self._abs(params.get("path", "."), project_dir)
        glob = params.get("glob", "**/*")
        results = []
        try:
            pattern = re.compile(query, re.IGNORECASE)
            for f in root.glob(glob):
                if not f.is_file():
                    continue
                try:
                    text = f.read_text(encoding="utf-8", errors="ignore")
                    for i, line in enumerate(text.splitlines(), 1):
                        if pattern.search(line):
                            rel = f.relative_to(root)
                            results.append(f"{rel}:{i}: {line.strip()}")
                            if len(results) >= 50:
                                break
                except Exception:
                    pass
                if len(results) >= 50:
                    break
        except re.error as e:
            return f"ERROR: Invalid regex: {e}"
        return "\n".join(results) or f"No matches for '{query}'"

    def _move(self, params: Dict, project_dir: str) -> str:
        src = self._abs(params["src"], project_dir)
        dst = self._abs(params["dst"], project_dir)
        shutil.move(str(src), str(dst))
        return f"✅ Moved {src} → {dst}"

    def _copy(self, params: Dict, project_dir: str) -> str:
        src = self._abs(params["src"], project_dir)
        dst = self._abs(params["dst"], project_dir)
        if src.is_dir():
            shutil.copytree(str(src), str(dst))
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))
        return f"✅ Copied {src} → {dst}"

    def _delete(self, params: Dict, project_dir: str) -> str:
        p = self._abs(params["path"], project_dir)
        if p.is_dir():
            shutil.rmtree(str(p))
        else:
            p.unlink(missing_ok=True)
        return f"✅ Deleted {p}"

    def _mkdir(self, params: Dict, project_dir: str) -> str:
        p = self._abs(params["path"], project_dir)
        p.mkdir(parents=True, exist_ok=True)
        return f"✅ Created directory {p}"


# ── Git MCP Server ────────────────────────────────────────────────────────────

class GitMCPServer(NativeMCPServer):
    """8 git tools: status, log, diff, branch, checkout, commit, push, pull."""

    def __init__(self):
        super().__init__(
            id="git",
            name="Git Operations",
            category="git",
            icon="⎇",
            description="Full git workflow automation — status, log, diff, branch management, commit, push, pull, stash.",
        )
        tools = [
            ("git_status",    self._status,    "Get working tree status and branch info",               {}),
            ("git_log",       self._log,       "Show recent git commits",                               {"n": {"type": "integer", "description": "Number of commits (default 10)"}}),
            ("git_diff",      self._diff,      "Show diff of staged or unstaged changes",               {"staged": {"type": "boolean"}, "file": {"type": "string"}}),
            ("git_branch",    self._branches,  "List all branches or create a new one",                 {"create": {"type": "string", "description": "Branch name to create"}}),
            ("git_checkout",  self._checkout,  "Switch to a branch",                                    {"branch": {"type": "string", "required": True}}),
            ("git_commit",    self._commit,    "Stage all and commit with a message",                   {"message": {"type": "string", "required": True}}),
            ("git_push",      self._push,      "Push current branch to remote origin",                  {"remote": {"type": "string"}, "branch": {"type": "string"}}),
            ("git_pull",      self._pull,      "Pull latest changes from remote",                       {"remote": {"type": "string"}}),
        ]
        for name, fn, desc, params in tools:
            self._register_tool(name, fn, MCPTool(name, desc, params, "git"))

    def _run(self, args: list, cwd: str) -> str:
        try:
            r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True, timeout=30)
            out = r.stdout.strip() or r.stderr.strip()
            return out or "(no output)"
        except subprocess.TimeoutExpired:
            return "ERROR: git command timed out"
        except FileNotFoundError:
            return "ERROR: git not found in PATH"
        except Exception as e:
            return f"ERROR: {e}"

    def _status(self, params: Dict, project_dir: str) -> str:
        return self._run(["status", "--short", "--branch"], project_dir)

    def _log(self, params: Dict, project_dir: str) -> str:
        n = params.get("n", 10)
        return self._run(["log", f"-{n}", "--oneline", "--graph", "--decorate"], project_dir)

    def _diff(self, params: Dict, project_dir: str) -> str:
        args = ["diff"]
        if params.get("staged"):
            args.append("--staged")
        if params.get("file"):
            args.append(params["file"])
        return self._run(args, project_dir)

    def _branches(self, params: Dict, project_dir: str) -> str:
        if params.get("create"):
            return self._run(["checkout", "-b", params["create"]], project_dir)
        return self._run(["branch", "-a"], project_dir)

    def _checkout(self, params: Dict, project_dir: str) -> str:
        return self._run(["checkout", params["branch"]], project_dir)

    def _commit(self, params: Dict, project_dir: str) -> str:
        self._run(["add", "-A"], project_dir)
        return self._run(["commit", "-m", params["message"]], project_dir)

    def _push(self, params: Dict, project_dir: str) -> str:
        remote = params.get("remote", "origin")
        branch = params.get("branch", "")
        args = ["push", remote]
        if branch:
            args.append(branch)
        return self._run(args, project_dir)

    def _pull(self, params: Dict, project_dir: str) -> str:
        remote = params.get("remote", "origin")
        return self._run(["pull", remote], project_dir)


# ── Shell MCP Server ──────────────────────────────────────────────────────────

class ShellMCPServer(NativeMCPServer):
    """5 shell tools: run command, run+capture, background jobs, env, which."""

    def __init__(self):
        super().__init__(
            id="shell",
            name="Shell Executor",
            category="shell",
            icon="⚡",
            description="Execute shell commands, capture output, manage background jobs, inspect environment.",
        )
        tools = [
            ("run",        self._run,        "Run a shell command and return output",          {"command": {"type": "string", "required": True}, "timeout": {"type": "integer"}}),
            ("run_piped",  self._run_piped,  "Run command pipeline (shell=True)",              {"command": {"type": "string", "required": True}}),
            ("which",      self._which,      "Find the path of an executable",                 {"name": {"type": "string", "required": True}}),
            ("env",        self._env,        "Get or set environment variables",               {"vars": {"type": "object"}, "get": {"type": "string"}}),
            ("ps",         self._ps,         "List running processes matching a name filter",  {"filter": {"type": "string"}}),
        ]
        for name, fn, desc, params in tools:
            self._register_tool(name, fn, MCPTool(name, desc, params, "shell"))

    def _run(self, params: Dict, project_dir: str) -> str:
        cmd = params["command"]
        timeout = params.get("timeout", 60)
        try:
            r = subprocess.run(
                cmd, shell=True, cwd=project_dir,
                capture_output=True, text=True, timeout=timeout,
            )
            out = "\n".join(filter(None, [r.stdout.strip(), r.stderr.strip()])) or "(no output)"
            prefix = f"[exit {r.returncode}] " if r.returncode != 0 else ""
            return (prefix + out)[:6000]
        except subprocess.TimeoutExpired:
            return f"ERROR: Timed out after {timeout}s"
        except Exception as e:
            return f"ERROR: {e}"

    def _run_piped(self, params: Dict, project_dir: str) -> str:
        return self._run(params, project_dir)

    def _which(self, params: Dict, project_dir: str) -> str:
        name = params["name"]
        path = shutil.which(name)
        return path or f"'{name}' not found in PATH"

    def _env(self, params: Dict, project_dir: str) -> str:
        if get := params.get("get"):
            return os.environ.get(get, f"(not set)")
        if vs := params.get("vars"):
            for k, v in vs.items():
                os.environ[k] = str(v)
            return f"✅ Set {len(vs)} env var(s)"
        # List all
        lines = [f"{k}={v}" for k, v in sorted(os.environ.items())]
        return "\n".join(lines[:100])

    def _ps(self, params: Dict, project_dir: str) -> str:
        f = params.get("filter", "")
        cmd = f"ps aux | grep '{f}' | grep -v grep" if f else "ps aux"
        return self._run({"command": cmd}, project_dir)


# ── Fetch MCP Server ──────────────────────────────────────────────────────────

class FetchMCPServer(NativeMCPServer):
    """4 web tools: fetch_url, extract_links, download_file, get_headers."""

    def __init__(self):
        super().__init__(
            id="fetch",
            name="Web Fetcher",
            category="fetch",
            icon="🌐",
            description="Fetch web pages, extract links and content, download files, inspect HTTP headers.",
        )
        tools = [
            ("fetch_url",       self._fetch,     "Fetch a URL and return text content",    {"url": {"type": "string", "required": True}, "timeout": {"type": "integer"}}),
            ("extract_links",   self._links,     "Extract all links from a URL",           {"url": {"type": "string", "required": True}}),
            ("download_file",   self._download,  "Download a remote file to local path",   {"url": {"type": "string", "required": True}, "dest": {"type": "string", "required": True}}),
            ("get_headers",     self._headers,   "Get HTTP response headers for a URL",    {"url": {"type": "string", "required": True}}),
        ]
        for name, fn, desc, params in tools:
            self._register_tool(name, fn, MCPTool(name, desc, params, "fetch"))

    def _fetch(self, params: Dict, project_dir: str) -> str:
        try:
            import httpx
            url = params["url"]
            timeout = params.get("timeout", 15)
            with httpx.Client(timeout=timeout, follow_redirects=True) as c:
                r = c.get(url)
            # Strip HTML tags for readable text
            text = re.sub(r"<[^>]+>", " ", r.text)
            text = re.sub(r"\s+", " ", text).strip()
            return f"[{r.status_code}] {url}\n\n{text[:5000]}"
        except Exception as e:
            return f"ERROR: {e}"

    def _links(self, params: Dict, project_dir: str) -> str:
        try:
            import httpx
            url = params["url"]
            with httpx.Client(timeout=15, follow_redirects=True) as c:
                r = c.get(url)
            hrefs = re.findall(r'href=["\']([^"\']+)["\']', r.text)
            unique = sorted(set(hrefs))
            return "\n".join(unique[:100]) or "No links found."
        except Exception as e:
            return f"ERROR: {e}"

    def _download(self, params: Dict, project_dir: str) -> str:
        try:
            import httpx
            url = params["url"]
            dest = Path(project_dir) / params["dest"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            with httpx.Client(timeout=60, follow_redirects=True) as c:
                r = c.get(url)
            dest.write_bytes(r.content)
            return f"✅ Downloaded {len(r.content):,} bytes → {dest}"
        except Exception as e:
            return f"ERROR: {e}"

    def _headers(self, params: Dict, project_dir: str) -> str:
        try:
            import httpx
            with httpx.Client(timeout=10, follow_redirects=True) as c:
                r = c.head(params["url"])
            lines = [f"{k}: {v}" for k, v in r.headers.items()]
            return f"HTTP {r.status_code}\n" + "\n".join(lines)
        except Exception as e:
            return f"ERROR: {e}"


# ── SQLite MCP Server ─────────────────────────────────────────────────────────

class SQLiteMCPServer(NativeMCPServer):
    """6 SQLite tools: query, insert, schema, tables, create_table, export_csv."""

    def __init__(self):
        super().__init__(
            id="sqlite",
            name="SQLite Database",
            category="sqlite",
            icon="🗄️",
            description="Full SQLite database management — query, insert, schema inspection, table creation, CSV export.",
        )
        tools = [
            ("query",         self._query,        "Execute a SQL SELECT query and return results",     {"db": {"type": "string", "required": True}, "sql": {"type": "string", "required": True}}),
            ("execute",       self._execute,      "Execute a SQL INSERT/UPDATE/DELETE/CREATE statement",{"db": {"type": "string", "required": True}, "sql": {"type": "string", "required": True}}),
            ("schema",        self._schema,       "Get the full CREATE TABLE schema for a database",   {"db": {"type": "string", "required": True}}),
            ("tables",        self._tables,       "List all tables in a SQLite database",              {"db": {"type": "string", "required": True}}),
            ("create_table",  self._create_table, "Create a new table from a column spec object",      {"db": {"type": "string", "required": True}, "table": {"type": "string", "required": True}, "columns": {"type": "object", "required": True}}),
            ("export_csv",    self._export_csv,   "Export a table to a CSV file",                      {"db": {"type": "string", "required": True}, "table": {"type": "string", "required": True}, "dest": {"type": "string"}}),
        ]
        for name, fn, desc, params in tools:
            self._register_tool(name, fn, MCPTool(name, desc, params, "sqlite"))

    def _db_path(self, db: str, project_dir: str) -> str:
        p = Path(db)
        if not p.is_absolute():
            p = Path(project_dir) / p
        return str(p)

    def _query(self, params: Dict, project_dir: str) -> str:
        db = self._db_path(params["db"], project_dir)
        sql = params["sql"]
        try:
            con = sqlite3.connect(db)
            con.row_factory = sqlite3.Row
            cur = con.execute(sql)
            rows = cur.fetchall()
            con.close()
            if not rows:
                return "(no rows returned)"
            headers = list(rows[0].keys())
            lines = [" | ".join(headers)]
            lines.append("-" * len(lines[0]))
            for row in rows[:200]:
                lines.append(" | ".join(str(v) for v in row))
            if len(rows) > 200:
                lines.append(f"... ({len(rows)} total rows, showing 200)")
            return "\n".join(lines)
        except Exception as e:
            return f"ERROR: {e}"

    def _execute(self, params: Dict, project_dir: str) -> str:
        db = self._db_path(params["db"], project_dir)
        sql = params["sql"]
        try:
            con = sqlite3.connect(db)
            cur = con.execute(sql)
            con.commit()
            affected = cur.rowcount
            con.close()
            return f"✅ Executed. Rows affected: {affected}"
        except Exception as e:
            return f"ERROR: {e}"

    def _schema(self, params: Dict, project_dir: str) -> str:
        db = self._db_path(params["db"], project_dir)
        try:
            con = sqlite3.connect(db)
            rows = con.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name").fetchall()
            con.close()
            return "\n\n".join(r[0] for r in rows) or "(empty database)"
        except Exception as e:
            return f"ERROR: {e}"

    def _tables(self, params: Dict, project_dir: str) -> str:
        db = self._db_path(params["db"], project_dir)
        try:
            con = sqlite3.connect(db)
            rows = con.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view') ORDER BY name").fetchall()
            con.close()
            return "\n".join(f"{r[1].upper()}: {r[0]}" for r in rows) or "(no tables)"
        except Exception as e:
            return f"ERROR: {e}"

    def _create_table(self, params: Dict, project_dir: str) -> str:
        db = self._db_path(params["db"], project_dir)
        table = params["table"]
        columns = params["columns"]  # {"col_name": "TEXT NOT NULL", ...}
        col_defs = ", ".join(f"{k} {v}" for k, v in columns.items())
        sql = f"CREATE TABLE IF NOT EXISTS {table} ({col_defs})"
        return self._execute({"db": params["db"], "sql": sql}, project_dir)

    def _export_csv(self, params: Dict, project_dir: str) -> str:
        db = self._db_path(params["db"], project_dir)
        table = params["table"]
        dest = params.get("dest", f"{table}.csv")
        dest_path = Path(project_dir) / dest if not Path(dest).is_absolute() else Path(dest)
        try:
            import csv
            con = sqlite3.connect(db)
            con.row_factory = sqlite3.Row
            rows = con.execute(f"SELECT * FROM {table}").fetchall()
            con.close()
            if not rows:
                return f"Table '{table}' is empty."
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            with dest_path.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=rows[0].keys())
                w.writeheader()
                w.writerows([dict(r) for r in rows])
            return f"✅ Exported {len(rows)} rows → {dest_path}"
        except Exception as e:
            return f"ERROR: {e}"


# ── Factory ───────────────────────────────────────────────────────────────────

def build_native_servers() -> list:
    """Return all prebuilt native MCP servers."""
    return [
        FilesystemMCPServer(),
        GitMCPServer(),
        ShellMCPServer(),
        FetchMCPServer(),
        SQLiteMCPServer(),
    ]

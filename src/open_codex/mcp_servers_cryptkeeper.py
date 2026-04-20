"""
CryptKeeper — in-app .env manager for Open Codex MCP servers.
==============================================================

Manages a single canonical env file:  ~/.open_codex/.env

All MCP servers (including dynamically-added ones) source this file at
startup so any key added here is immediately available to them on next
invocation.

Forge agents declare key requests via MCP tools:
  cryptkeeper_request_secret(name, reason, browser_alternative)
  cryptkeeper_has_secret(name)
  cryptkeeper_get_secret(name)          ← returns value for agent use
  cryptkeeper_list_secrets()            ← returns names only

The REST layer (/api/cryptkeeper/*) is for the frontend UI:
  GET  /api/cryptkeeper/env             ← {keys: ["NAME", ...]}  (names only)
  POST /api/cryptkeeper/env             ← {name, value} store/update
  DELETE /api/cryptkeeper/env/{name}    ← remove key
  GET  /api/cryptkeeper/requests        ← pending agent requests
  POST /api/cryptkeeper/deny            ← deny + optionally note browser path
  POST /api/cryptkeeper/dismiss/{name}  ← remove from pending list
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────────
_OCODX_DIR    = Path.home() / ".open_codex"
ENV_FILE       = _OCODX_DIR / ".env"
REQUESTS_FILE  = _OCODX_DIR / "ck_requests.json"

_OCODX_DIR.mkdir(parents=True, exist_ok=True)


# ── .env file helpers ──────────────────────────────────────────────────────────

def _parse_env() -> dict[str, str]:
    """Return {NAME: value} from the .env file (ignores comments / blanks)."""
    if not ENV_FILE.exists():
        return {}
    result: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            # strip optional surrounding quotes
            v = v.strip().strip('"').strip("'")
            result[k.strip()] = v
    return result


def _write_env(data: dict[str, str]) -> None:
    """Rewrite the .env file from the given dict, preserving existing comments."""
    lines: list[str] = []
    if ENV_FILE.exists():
        # Keep comment / blank lines unchanged; rebuild key lines
        existing_keys: set[str] = set()
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                lines.append(line)
                continue
            if "=" in stripped:
                k = stripped.split("=", 1)[0].strip()
                if k in data:
                    lines.append(f'{k}="{data[k]}"')
                    existing_keys.add(k)
                # If key was deleted, skip the line
        # Append new keys not already in file
        for k, v in data.items():
            if k not in existing_keys:
                lines.append(f'{k}="{v}"')
    else:
        lines = [f'# Open Codex CryptKeeper managed .env', '']
        for k, v in data.items():
            lines.append(f'{k}="{v}"')

    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # Also export into the current process so new MCP server subprocesses inherit
    for k, v in data.items():
        os.environ[k] = v


def env_get(name: str) -> str | None:
    return _parse_env().get(name)

def env_set(name: str, value: str) -> None:
    data = _parse_env()
    data[name] = value
    _write_env(data)
    # Remove from pending requests (user has supplied it)
    dismiss_request(name)

def env_delete(name: str) -> None:
    data = _parse_env()
    data.pop(name, None)
    _write_env(data)

def env_list_names() -> list[str]:
    return sorted(_parse_env().keys())


# ── Pending requests ───────────────────────────────────────────────────────────

def _load_requests() -> list[dict]:
    if not REQUESTS_FILE.exists():
        return []
    try:
        return json.loads(REQUESTS_FILE.read_text())
    except Exception:
        return []

def _save_requests(reqs: list[dict]) -> None:
    REQUESTS_FILE.write_text(json.dumps(reqs, indent=2))

def add_request(
    name: str,
    reason: str,
    browser_alternative: str | None = None,
    service_url: str | None = None,
) -> None:
    reqs = [r for r in _load_requests() if r.get("name") != name]
    reqs.append({
        "name": name,
        "reason": reason,
        "browser_alternative": browser_alternative,
        "has_browser_path": bool(browser_alternative),
        "service_url": service_url,
        "status": "pending",
        "requested_at": datetime.now(timezone.utc).isoformat(),
    })
    _save_requests(reqs)

def dismiss_request(name: str) -> None:
    _save_requests([r for r in _load_requests() if r.get("name") != name])

def deny_request(name: str, reason: str = "") -> None:
    reqs = _load_requests()
    for r in reqs:
        if r.get("name") == name:
            r["status"] = "denied"
            r["denied_reason"] = reason
            r["denied_at"] = datetime.now(timezone.utc).isoformat()
    _save_requests(reqs)

def list_requests() -> list[dict]:
    return _load_requests()


# ── CryptKeeperMCPServer ───────────────────────────────────────────────────────

class CryptKeeperMCPServer:
    """
    Wraps CryptKeeper tools as a NativeMCPServer registered with the MCP bridge.

    Agents call:
      cryptkeeper_request_secret(name, reason, browser_alternative?, service_url?)
      cryptkeeper_has_secret(name)
      cryptkeeper_get_secret(name)
      cryptkeeper_list_secrets()

    Browser automation is the PREFERRED path — API keys are last resort.
    """

    def __init__(self, bridge: Any) -> None:
        from open_codex.mcp_bridge import NativeMCPServer, MCPTool

        class _CKServer(NativeMCPServer):
            def __init__(inner_self):
                super().__init__(
                    id="cryptkeeper",
                    name="CryptKeeper",
                    category="secrets",
                    icon="🔐",
                    description=(
                        "Secure in-app .env manager. Agents declare key requests "
                        "(name + reason + browser alternative). Values stored in "
                        "~/.open_codex/.env and sourced by all MCP servers."
                    ),
                )
                inner_self._register_tool(
                    "cryptkeeper_request_secret",
                    inner_self._req,
                    MCPTool(
                        "cryptkeeper_request_secret",
                        (
                            "Declare that you need an env var / API key. "
                            "REQUIRED: explain WHY the key is needed and WHETHER "
                            "browser automation could achieve the same goal for free. "
                            "Prefer browser — only request an API key when unavoidable."
                        ),
                        {
                            "name":               {"type": "string", "required": True,
                                                   "description": "Env var name, e.g. GITHUB_TOKEN"},
                            "reason":             {"type": "string", "required": True,
                                                   "description": "Why this key is needed and what it enables"},
                            "browser_alternative":{"type": "string",
                                                   "description": "How browser automation could replace this key (or null if impossible)"},
                            "service_url":        {"type": "string",
                                                   "description": "URL where the user can obtain the key"},
                        },
                        "cryptkeeper",
                    ),
                )
                inner_self._register_tool(
                    "cryptkeeper_has_secret",
                    inner_self._has,
                    MCPTool(
                        "cryptkeeper_has_secret",
                        "Check if a named env var is stored. Returns true/false, never the value.",
                        {"name": {"type": "string", "required": True}},
                        "cryptkeeper",
                    ),
                )
                inner_self._register_tool(
                    "cryptkeeper_get_secret",
                    inner_self._get,
                    MCPTool(
                        "cryptkeeper_get_secret",
                        "Retrieve the value of a stored env var. Only call after has_secret returns true.",
                        {"name": {"type": "string", "required": True}},
                        "cryptkeeper",
                    ),
                )
                inner_self._register_tool(
                    "cryptkeeper_list_secrets",
                    inner_self._list,
                    MCPTool(
                        "cryptkeeper_list_secrets",
                        "List the NAMES of all stored env vars. Values are never returned.",
                        {},
                        "cryptkeeper",
                    ),
                )

            def _req(inner_self, params: dict, _proj: str = ".") -> str:
                name    = params.get("name", "").strip()
                reason  = params.get("reason", "").strip()
                browser = params.get("browser_alternative")
                url     = params.get("service_url")
                if not name or not reason:
                    return "Error: name and reason are required."
                add_request(name, reason, browser, url)
                has_browser = bool(browser)
                return (
                    f"CryptKeeper notified — awaiting user decision for '{name}'.\n"
                    + ("🌐 Browser path available — user may prefer that.\n" if has_browser else
                       "🔑 API key required — no browser alternative.\n")
                    + (f"Obtain at: {url}" if url else "")
                )

            def _has(inner_self, params: dict, _proj: str = ".") -> str:
                name   = params.get("name", "").strip()
                exists = name in _parse_env()
                return json.dumps({"name": name, "exists": exists})

            def _get(inner_self, params: dict, _proj: str = ".") -> str:
                name = params.get("name", "").strip()
                val  = env_get(name)
                if val is None:
                    return (
                        f"Error: '{name}' not in CryptKeeper .env. "
                        "Call cryptkeeper_request_secret and wait for user approval."
                    )
                return json.dumps({"name": name, "value": val})

            def _list(inner_self, params: dict, _proj: str = ".") -> str:
                return json.dumps({"secrets": env_list_names()})

        self._server = _CKServer()
        bridge.register(self._server)
        logger.info("CryptKeeperMCPServer registered — env file: %s", ENV_FILE)


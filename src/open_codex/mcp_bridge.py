"""
Open Codex MCP Bridge -- Sovereign Liquid Matrix MCP Layer

Unified registry of MCP servers. AI generation routes through:
  ollama        -- local Ollama (any model)
  ollama_cloud  -- Ollama cloud endpoint
  lmstudio      -- LM Studio OpenAI-compatible REST
  gemini        -- Google Gemini API
  huggingface   -- HuggingFace Inference API (analysis tools only)

Config keys per server (set via MCP Hub Config drawer or env vars):
  JOOMLA_BASE_URL, BEARER_TOKEN
  AI_PROVIDER           -- default provider (ollama|ollama_cloud|lmstudio|gemini|huggingface)
  OLLAMA_HOST           -- default: http://localhost:11434
  OLLAMA_MODEL          -- default: llama3
  OLLAMA_API_KEY        -- optional (for Ollama Cloud)
  LMSTUDIO_HOST         -- default: http://localhost:1234
  LMSTUDIO_MODEL        -- default: local-model
  GEMINI_API_KEY
  GEMINI_MODEL          -- default: gemini-2.0-flash
  HUGGINGFACE_API_TOKEN
"""

from __future__ import annotations

import json
import logging
import re as _re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Descriptors
# ---------------------------------------------------------------------------

@dataclass
class MCPTool:
    name: str
    description: str
    parameters: Dict[str, Any]
    server_id: str = ""


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

    def health_check(self) -> bool:
        return True

    def call(self, tool: str, params: Dict[str, Any], project_dir: str = ".") -> str:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Bridge registry
# ---------------------------------------------------------------------------

class MCPBridge:
    def __init__(self):
        self._servers: Dict[str, MCPServer] = {}

    def register(self, server: MCPServer):
        self._servers[server.id] = server

    def get(self, server_id: str) -> Optional[MCPServer]:
        return self._servers.get(server_id)

    def all_servers(self) -> List[MCPServer]:
        for srv in self._servers.values():
            try:
                srv.healthy = srv.health_check()
            except Exception:
                srv.healthy = False
        return list(self._servers.values())

    def call(self, server_id: str, tool: str, params: Dict[str, Any],
             project_dir: str = ".") -> Dict[str, Any]:
        srv = self._servers.get(server_id)
        if srv is None:
            return {"error": f"Unknown MCP server: {server_id}", "result": None}
        try:
            result = srv.call(tool, params, project_dir)
            return {"result": result, "error": None, "tool": tool, "server": server_id}
        except Exception as exc:
            logger.exception("MCP call %s.%s failed", server_id, tool)
            return {"error": str(exc), "result": None, "tool": tool, "server": server_id}

    def configure(self, server_id: str, config: Dict[str, str]):
        srv = self._servers.get(server_id)
        if srv:
            srv.config.update(config)

    def tool_manifest(self) -> List[Dict]:
        out = []
        for srv in self._servers.values():
            for t in srv.tools:
                out.append({
                    "server": srv.id,
                    "server_name": srv.name,
                    "tool": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                })
        return out


# ---------------------------------------------------------------------------
# Native Python base server
# ---------------------------------------------------------------------------

class NativeMCPServer(MCPServer):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._dispatch: Dict[str, Callable] = {}

    def _register_tool(self, name: str, fn: Callable, tool: MCPTool):
        self._dispatch[name] = fn
        self.tools.append(tool)

    def call(self, tool: str, params: Dict[str, Any], project_dir: str = ".") -> str:
        fn = self._dispatch.get(tool)
        if fn is None:
            return f"ERROR: Unknown tool '{tool}' on server '{self.id}'"
        return fn(params, project_dir)

    def health_check(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Joomla MCP Server
# ---------------------------------------------------------------------------

class JoomlaMCPServer(MCPServer):

    JOOMLA_TOOLS = [
        # CMS CRUD
        MCPTool("get_joomla_articles",   "List all Joomla articles",  {}, "joomla"),
        MCPTool("get_joomla_categories", "List all Joomla categories", {}, "joomla"),
        MCPTool("create_article", "Create and publish a Joomla article",
                {"article_text":  {"type": "string",  "required": True},
                 "title":         {"type": "string"},
                 "category_id":   {"type": "integer"},
                 "published":     {"type": "boolean"}}, "joomla"),
        MCPTool("update_article", "Update an existing Joomla article",
                {"article_id":    {"type": "integer", "required": True},
                 "title":         {"type": "string"},
                 "introtext":     {"type": "string"},
                 "fulltext":      {"type": "string"},
                 "metadesc":      {"type": "string"}}, "joomla"),
        MCPTool("manage_article_state", "Change article state",
                {"article_id":   {"type": "integer", "required": True},
                 "target_state": {"type": "integer", "required": True,
                                  "description": "1=published 0=unpublished 2=archived -2=trashed"}}, "joomla"),
        MCPTool("move_article_to_trash", "Move article to trash",
                {"article_id":     {"type": "integer", "required": True},
                 "expected_title": {"type": "string"}}, "joomla"),

        # Provider-agnostic AI tools
        MCPTool("generate_article", "Generate article using configured AI provider",
                {"topic":           {"type": "string", "required": True},
                 "style":           {"type": "string", "description": "informative|persuasive|casual|technical"},
                 "length":          {"type": "string", "description": "short|medium|long"},
                 "target_audience": {"type": "string"},
                 "ai_service":      {"type": "string",
                                     "description": "ollama|ollama_cloud|lmstudio|gemini|huggingface (overrides AI_PROVIDER)"}},
                "joomla"),
        MCPTool("enhance_article", "Enhance article content using configured AI provider",
                {"content":          {"type": "string", "required": True},
                 "enhancement_type": {"type": "string",
                                      "description": "improve_readability|add_details|make_engaging|fix_grammar|optimize_seo"},
                 "target_audience":  {"type": "string"},
                 "ai_service":       {"type": "string"}}, "joomla"),
        MCPTool("generate_title_meta", "Generate SEO title + meta description",
                {"content":       {"type": "string", "required": True},
                 "focus_keyword": {"type": "string"},
                 "title_style":   {"type": "string",
                                   "description": "engaging|professional|clickbait|descriptive"},
                 "ai_service":    {"type": "string"}}, "joomla"),
        MCPTool("summarize_article", "Summarize article using configured AI provider",
                {"content":    {"type": "string",  "required": True},
                 "max_length": {"type": "integer"},
                 "ai_service": {"type": "string"}}, "joomla"),
        MCPTool("analyze_sentiment", "Analyze article sentiment",
                {"content":    {"type": "string", "required": True},
                 "ai_service": {"type": "string"}}, "joomla"),
        MCPTool("classify_content", "Classify article into categories",
                {"content":          {"type": "string", "required": True},
                 "candidate_labels": {"type": "array"},
                 "ai_service":       {"type": "string"}}, "joomla"),
        MCPTool("translate_content", "Translate article to another language",
                {"content":         {"type": "string", "required": True},
                 "target_language": {"type": "string"},
                 "source_language": {"type": "string"},
                 "ai_service":      {"type": "string"}}, "joomla"),

        # Pipeline tools
        MCPTool("create_ai_article_and_publish", "AI generate + publish to Joomla in one step",
                {"topic":       {"type": "string",  "required": True},
                 "ai_service":  {"type": "string",
                                 "description": "ollama|ollama_cloud|lmstudio|gemini (overrides AI_PROVIDER)"},
                 "style":       {"type": "string"},
                 "category_id": {"type": "integer"},
                 "published":   {"type": "boolean"}}, "joomla"),
        MCPTool("enhance_existing_joomla_article", "Fetch + AI enhance + update article",
                {"article_id":       {"type": "integer", "required": True},
                 "enhancement_type": {"type": "string"},
                 "ai_service":       {"type": "string"}}, "joomla"),
        MCPTool("analyze_joomla_articles_with_ai", "Bulk AI analysis of Joomla articles",
                {"limit":        {"type": "integer"},
                 "analysis_type":{"type": "string"},
                 "ai_service":   {"type": "string"}}, "joomla"),

        # Legacy explicit-provider tools (backward compat)
        MCPTool("generate_article_with_gemini", "Generate article via Gemini",
                {"topic": {"type": "string", "required": True},
                 "style": {"type": "string"}, "length": {"type": "string"},
                 "target_audience": {"type": "string"}}, "joomla"),
        MCPTool("enhance_article_with_gemini", "Enhance article via Gemini",
                {"content": {"type": "string", "required": True},
                 "enhancement_type": {"type": "string"}}, "joomla"),
        MCPTool("generate_title_meta_with_gemini", "SEO title + meta via Gemini",
                {"content": {"type": "string", "required": True},
                 "focus_keyword": {"type": "string"}}, "joomla"),
        MCPTool("generate_article_with_ollama", "Generate article via Ollama",
                {"topic": {"type": "string", "required": True},
                 "style": {"type": "string"}, "length": {"type": "string"},
                 "model": {"type": "string"}}, "joomla"),
        MCPTool("generate_article_with_lmstudio", "Generate article via LM Studio",
                {"topic": {"type": "string", "required": True},
                 "style": {"type": "string"}, "length": {"type": "string"},
                 "model": {"type": "string"}}, "joomla"),
    ]

    def __init__(self, script_path: str, config: Optional[Dict[str, str]] = None):
        super().__init__(
            id="joomla",
            name="Joomla CMS",
            category="joomla",
            icon="🌐",
            description=(
                "Full Joomla 4/5 CMS management with multi-provider AI content generation. "
                "Supports Ollama (local+cloud), LM Studio, and Google Gemini for article generation, "
                "enhancement, SEO optimisation, translation, and bulk analysis."
            ),
            tools=self.JOOMLA_TOOLS,
            config=config or {},
        )
        self.script_path = script_path

    # -- Health check ----------------------------------------------------------

    def health_check(self) -> bool:
        base = self.config.get("JOOMLA_BASE_URL", "")
        if not base:
            return False
        try:
            import httpx
            r = httpx.get(
                f"{base}/api/index.php/v1/content/articles",
                headers={"Authorization": f"Bearer {self.config.get('BEARER_TOKEN', '')}"},
                timeout=5,
            )
            return r.status_code < 500
        except Exception:
            return False

    # -- Tool dispatcher -------------------------------------------------------

    def call(self, tool: str, params: Dict[str, Any], project_dir: str = ".") -> str:
        base  = self.config.get("JOOMLA_BASE_URL", "").rstrip("/")
        token = self.config.get("BEARER_TOKEN", "")

        AI_ONLY = {
            "generate_article", "enhance_article", "generate_title_meta",
            "summarize_article", "analyze_sentiment", "classify_content", "translate_content",
            "generate_article_with_gemini", "enhance_article_with_gemini",
            "generate_title_meta_with_gemini",
            "generate_article_with_ollama", "generate_article_with_lmstudio",
        }

        if tool not in AI_ONLY and (not base or not token):
            return (
                "WARNING: Joomla not configured. Set JOOMLA_BASE_URL and BEARER_TOKEN "
                "in the MCP Hub Config drawer.\n"
                f"Tool: {tool}\nParams: {json.dumps(params, indent=2)}"
            )

        try:
            import httpx

            def alias(title: str) -> str:
                s = _re.sub(r"[^a-z0-9\s-]", "", title.lower())
                return _re.sub(r"\s+", "-", s).strip("-")

            hdrs = {
                "Accept": "application/vnd.api+json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            }
            art_url = f"{base}/api/index.php/v1/content/articles"
            cat_url = f"{base}/api/index.php/v1/content/categories"

            with httpx.Client(timeout=30) as c:

                # ---- CMS CRUD ------------------------------------------------
                if tool == "get_joomla_articles":
                    return c.get(art_url, headers=hdrs).text

                elif tool == "get_joomla_categories":
                    cats = c.get(cat_url, headers=hdrs).json().get("data", [])
                    lines = ["Categories:"]
                    for cat in cats:
                        a = cat.get("attributes", {})
                        lines.append(f"  {a.get('id')}: {a.get('title')}")
                    return "\n".join(lines)

                elif tool == "create_article":
                    text   = params.get("article_text", "")
                    title  = params.get("title") or (text[:60].rstrip() + "…")
                    pub    = params.get("published", True)
                    body   = {
                        "alias": alias(title), "articletext": text,
                        "catid": params.get("category_id", 8),
                        "title": title, "state": 1 if pub else 0, "language": "*",
                    }
                    r = c.post(art_url, json=body, headers=hdrs)
                    return (f"Article '{title}' created and {'published' if pub else 'drafted'}."
                            if r.status_code in (200, 201)
                            else f"Create failed HTTP {r.status_code}: {r.text[:400]}")

                elif tool == "update_article":
                    aid  = params["article_id"]
                    body = {k: params[k] for k in ("title", "introtext", "fulltext", "metadesc") if k in params}
                    if "title" in body:
                        body["alias"] = alias(body["title"])
                    r = c.patch(f"{art_url}/{aid}", json=body, headers=hdrs)
                    return (f"Article {aid} updated."
                            if r.status_code in (200, 204)
                            else f"Update failed {r.status_code}: {r.text[:400]}")

                elif tool == "manage_article_state":
                    aid   = params["article_id"]
                    state = params["target_state"]
                    label = {1: "published", 0: "unpublished", 2: "archived", -2: "trashed"}.get(state, str(state))
                    r = c.patch(f"{art_url}/{aid}", json={"state": state}, headers=hdrs)
                    return (f"Article {aid} is now {label}."
                            if r.status_code in (200, 204)
                            else f"State change failed {r.status_code}")

                elif tool == "move_article_to_trash":
                    aid = params["article_id"]
                    r = c.patch(f"{art_url}/{aid}", json={"state": -2}, headers=hdrs)
                    return (f"Article {aid} moved to trash."
                            if r.status_code in (200, 204)
                            else f"Trash failed {r.status_code}")

                # ---- Provider-agnostic AI ------------------------------------
                elif tool in ("generate_article", "enhance_article", "generate_title_meta",
                              "summarize_article", "analyze_sentiment",
                              "classify_content", "translate_content"):
                    return self._ai_tool(tool, params)

                # ---- Explicit-provider aliases --------------------------------
                elif tool in ("generate_article_with_gemini", "enhance_article_with_gemini",
                              "generate_title_meta_with_gemini"):
                    return self._ai_tool(tool, {**params, "_force_provider": "gemini"})

                elif tool == "generate_article_with_ollama":
                    p = dict(params)
                    if "model" in p:
                        self.config["OLLAMA_MODEL"] = p.pop("model")
                    return self._ai_tool("generate_article", {**p, "_force_provider": "ollama"})

                elif tool == "generate_article_with_lmstudio":
                    p = dict(params)
                    if "model" in p:
                        self.config["LMSTUDIO_MODEL"] = p.pop("model")
                    return self._ai_tool("generate_article", {**p, "_force_provider": "lmstudio"})

                # ---- Pipelines -----------------------------------------------
                elif tool == "create_ai_article_and_publish":
                    content = self._ai_tool("generate_article", params)
                    if content.lower().startswith(("error", "warning")):
                        return content
                    body = {
                        "alias":       alias(params.get("topic", "ai-article")),
                        "articletext": content,
                        "catid":       params.get("category_id", 8),
                        "title":       params.get("topic", "AI Generated Article"),
                        "state":       1 if params.get("published", True) else 0,
                        "language":    "*",
                    }
                    r = c.post(art_url, json=body, headers=hdrs)
                    return (f"AI article '{params.get('topic')}' published."
                            if r.status_code in (200, 201)
                            else f"Publish failed {r.status_code}: {r.text[:300]}")

                elif tool == "enhance_existing_joomla_article":
                    aid = params["article_id"]
                    r = c.get(f"{art_url}/{aid}", headers=hdrs)
                    if r.status_code != 200:
                        return f"Could not fetch article {aid}: HTTP {r.status_code}"
                    art  = r.json().get("data", {}).get("attributes", {})
                    text = (art.get("introtext", "") + "\n" + art.get("fulltext", "")).strip()
                    enhanced = self._ai_tool("enhance_article", {
                        "content":          text,
                        "enhancement_type": params.get("enhancement_type", "improve_readability"),
                        "ai_service":       params.get("ai_service", ""),
                    })
                    upd = c.patch(f"{art_url}/{aid}", json={"articletext": enhanced}, headers=hdrs)
                    return (f"Article {aid} enhanced."
                            if upd.status_code in (200, 204)
                            else f"Update failed {upd.status_code}")

                elif tool == "analyze_joomla_articles_with_ai":
                    arts   = c.get(art_url, headers=hdrs).json().get("data", [])
                    limit  = params.get("limit", 5)
                    ai_svc = params.get("ai_service", "")
                    rows   = []
                    for art in arts[:limit]:
                        a    = art.get("attributes", {})
                        text = ((a.get("introtext") or "") + " " + (a.get("fulltext") or ""))[:500]
                        analysis = self._ai_tool("analyze_sentiment",
                                                  {"content": text, "ai_service": ai_svc})
                        rows.append(f"[{a.get('id')}] {a.get('title')}: {analysis}")
                    return "\n".join(rows) or "No articles."

                else:
                    return f"Error: Tool '{tool}' not implemented in Joomla server."

        except Exception as exc:
            return f"Error ({type(exc).__name__}): {exc}"

    # -- AI routing ------------------------------------------------------------

    def _resolve_provider(self, params: Dict) -> str:
        return (
            (params.get("ai_service") or "").strip()
            or (params.get("_force_provider") or "").strip()
            or (self.config.get("AI_PROVIDER") or "").strip()
            or "gemini"
        ).lower()

    def _build_prompt(self, tool: str, params: Dict) -> str:
        t = (tool
             .replace("_with_gemini", "")
             .replace("_with_ollama", "")
             .replace("_with_lmstudio", ""))

        if "generate_article" in t:
            return (
                f"Write a {params.get('style', 'informative')} article about "
                f"'{params.get('topic', 'the requested topic')}' for a "
                f"{params.get('target_audience', 'general')} audience. "
                f"Length: {params.get('length', 'medium')}. "
                "Include a compelling title on the first line. "
                "Use clear headings and well-structured paragraphs. "
                "The content must be original and ready to publish on a Joomla website."
            )
        if "enhance_article" in t or "enhance" in t:
            enh  = params.get("enhancement_type", "improve_readability")
            aud  = params.get("target_audience", "general")
            body = params.get("content", "")[:3000]
            return (
                f"Improve the following article ('enhancement goal: {enh}') "
                f"for a {aud} audience. "
                "Return only the improved content with the same structure.\n\n"
                + body
            )
        if "title_meta" in t or "generate_title" in t:
            kw    = params.get("focus_keyword", "")
            style = params.get("title_style", "engaging")
            body  = params.get("content", "")[:1500]
            kw_note = f" Include the keyword '{kw}'." if kw else ""
            return (
                f"Write a {style} SEO title (under 60 chars) and meta description "
                f"(under 160 chars) for this article.{kw_note}\n"
                "Respond EXACTLY in this format:\n"
                "Title: <title here>\n"
                "Meta: <meta description here>\n\n"
                + body
            )
        if "summarize" in t:
            ml = params.get("max_length", 150)
            return f"Summarize the following text in under {ml} words:\n\n" + params.get("content", "")[:3000]
        if "sentiment" in t:
            return (
                "Analyze the sentiment of the text below. "
                "Reply with: SENTIMENT: [POSITIVE/NEGATIVE/NEUTRAL] | SCORE: [0.0-1.0] | REASON: <brief>\n\n"
                + params.get("content", "")[:1000]
            )
        if "classify" in t:
            labels = params.get("candidate_labels",
                                ["technology", "business", "health", "entertainment", "science"])
            return (
                f"Classify the text below into one of: {', '.join(labels)}.\n"
                "Reply with: CATEGORY: <label> | CONFIDENCE: <0.0-1.0>\n\n"
                + params.get("content", "")[:1000]
            )
        if "translate" in t:
            src = params.get("source_language", "English")
            tgt = params.get("target_language", "French")
            return (
                f"Translate the following {src} text into {tgt}. "
                "Return only the translation, no explanations.\n\n"
                + params.get("content", "")[:3000]
            )
        return str(params)

    def _generate_with_ai(self, prompt: str, provider: str, max_tokens: int = 1400) -> str:
        """Route text generation through the selected provider."""
        try:
            # ------------------------------------------------------------------
            # Ollama LOCAL
            # Docs: http://localhost:11434 (or custom OLLAMA_HOST)
            # Auth: none by default (optional OLLAMA_API_KEY for protected servers)
            # Models: whatever you have pulled locally (ollama pull llama3, etc.)
            # Config keys: OLLAMA_HOST, OLLAMA_MODEL, OLLAMA_API_KEY (optional)
            # ------------------------------------------------------------------
            if provider == "ollama":
                import ollama as _ollama
                raw_host = self.config.get("OLLAMA_HOST", "http://localhost:11434")
                # Strip trailing /api if user included it (SDK appends /api/chat itself)
                host  = _re.sub(r"/api/?$", "", raw_host.rstrip("/"))
                model = self.config.get("OLLAMA_MODEL", "llama3")
                # Build client — no auth unless explicitly configured
                oc_kwargs: Dict[str, Any] = {"host": host}
                local_key = self.config.get("OLLAMA_API_KEY", "")
                if local_key:
                    oc_kwargs["headers"] = {"Authorization": f"Bearer {local_key}"}
                oc   = _ollama.Client(**oc_kwargs)
                resp = oc.chat(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    options={"num_predict": max_tokens, "temperature": 0.7},
                )
                return resp["message"]["content"].strip()

            # ------------------------------------------------------------------
            # Ollama CLOUD
            # Docs: https://docs.ollama.com/cloud
            # Host:  https://ollama.com  (always -- do NOT override)
            # Auth:  Bearer token from https://ollama.com/settings/keys  (REQUIRED)
            # Models: cloud-hosted tags, e.g. gpt-oss:120b, llama4:scout
            # Config keys: OLLAMA_CLOUD_API_KEY (required), OLLAMA_CLOUD_MODEL
            # ------------------------------------------------------------------
            elif provider == "ollama_cloud":
                import ollama as _ollama
                cloud_key = self.config.get("OLLAMA_CLOUD_API_KEY", "")
                if not cloud_key:
                    return (
                        "Error: OLLAMA_CLOUD_API_KEY not configured. "
                        "Get your API key from https://ollama.com/settings/keys "
                        "and add it in the MCP Hub Config drawer."
                    )
                cloud_model = self.config.get("OLLAMA_CLOUD_MODEL", "gpt-oss:120b")
                # Ollama Cloud always uses https://ollama.com as the host
                oc = _ollama.Client(
                    host="https://ollama.com",
                    headers={"Authorization": f"Bearer {cloud_key}"},
                )
                resp = oc.chat(
                    model=cloud_model,
                    messages=[{"role": "user", "content": prompt}],
                    options={"num_predict": max_tokens, "temperature": 0.7},
                )
                return resp["message"]["content"].strip()

            # -- LM Studio (OpenAI-compatible) ---------------------------------
            elif provider == "lmstudio":
                import httpx as _hx
                host  = self.config.get("LMSTUDIO_HOST", "http://localhost:1234").rstrip("/")
                model = self.config.get("LMSTUDIO_MODEL", "local-model")
                body  = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": 0.7,
                    "stream": False,
                }
                with _hx.Client(timeout=120) as hc:
                    r = hc.post(f"{host}/v1/chat/completions", json=body)
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"].strip()

            # -- Google Gemini -------------------------------------------------
            elif provider == "gemini":
                from google import genai as _genai
                key = self.config.get("GEMINI_API_KEY", "")
                if not key:
                    return "Error: GEMINI_API_KEY not configured. Use the MCP Hub Config drawer."
                _gc = _genai.Client(api_key=key)
                resp = _gc.models.generate_content(
                    model=self.config.get("GEMINI_MODEL", "gemini-2.0-flash"),
                    contents=prompt,
                )
                return resp.text

            # -- HuggingFace (generation fallback) -----------------------------
            elif provider == "huggingface":
                token = self.config.get("HUGGINGFACE_API_TOKEN", "")
                if not token:
                    return (
                        "Error: HUGGINGFACE_API_TOKEN not configured. "
                        "Use the MCP Hub Config drawer or switch to ollama/lmstudio/gemini."
                    )
                from huggingface_hub import InferenceClient
                cl  = InferenceClient(token=token)
                out = cl.text_generation(prompt, max_new_tokens=max_tokens)
                return out.strip()

            else:
                return (
                    f"Error: Unknown AI provider '{provider}'. "
                    "Valid options: ollama, ollama_cloud, lmstudio, gemini, huggingface."
                )

        except Exception as exc:
            return f"AI generation error ({provider} / {type(exc).__name__}): {exc}"

    def _ai_tool(self, tool: str, params: Dict) -> str:
        """Resolve provider + build prompt + call AI."""
        provider = self._resolve_provider(params)
        prompt   = self._build_prompt(tool, params)
        return self._generate_with_ai(prompt, provider)

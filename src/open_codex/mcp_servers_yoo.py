"""
Open Codex — YOOtheme Pro MCP Server

Provides autonomous natural-language → YOOtheme layout JSON generation and
direct Joomla database layout injection.

Architecture:
  - YooLayoutEngine  : Python port of openflow-builder-main/yoothemeLayoutEngine.ts
                       Full CRUD on YOO layout JSON trees with 50-deep undo/redo
  - YooThemeMCPServer: 26 MCP tools spanning AI generation, layout engine ops,
                       and MySQL direct read/write of #__content.introtext

YOOtheme Layout JSON format (stored in article introtext as <!--{...}-->):
  {
    "type": "layout",
    "version": "4.5.33",
    "name": "My Page",
    "children": [
      {
        "type": "section",
        "props": {"style": "default", "name": "Hero", "padding_top": "xlarge"},
        "children": [
          {
            "type": "row",
            "props": {"gutter": "medium"},
            "children": [
              {
                "type": "column",
                "props": {"width_bp": "1-1"},
                "children": [
                  {"type": "headline", "props": {"content": "Hello", "title_element": "h1"}},
                  {"type": "text",     "props": {"content": "<p>Body</p>"}},
                  {"type": "button",   "props": {"content": "CTA", "link": "#", "button_style": "primary"}}
                ]
              }
            ]
          }
        ]
      }
    ]
  }
"""

from __future__ import annotations

import copy
import json
import logging
import re as _re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from open_codex.mcp_bridge import NativeMCPServer, MCPTool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# YOO layout JSON factories (mirrors yoothemeSchemas.ts makeXxx helpers)
# ---------------------------------------------------------------------------

def _uid() -> str:
    """Short stable-ish unique ID for node identity."""
    import random, string
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=8))


def make_layout(children: List[Dict], name: str = "Layout") -> Dict:
    return {"type": "layout", "version": "4.5.33", "name": name, "children": children}

def make_section(props: Dict = None, children: List[Dict] = None) -> Dict:
    return {"type": "section", "props": props or {}, "children": children or []}

def make_row(props: Dict = None, children: List[Dict] = None) -> Dict:
    return {"type": "row", "props": props or {"gutter": "medium"}, "children": children or []}

def make_column(width: str = "1-1", props: Dict = None, children: List[Dict] = None) -> Dict:
    p = props or {}
    p.setdefault("width_bp", width)
    return {"type": "column", "props": p, "children": children or []}

def make_headline(content: str, element: str = "h2", style: str = "heading-large") -> Dict:
    return {"type": "headline", "props": {"content": content, "title_element": element, "title_style": style}}

def make_text(content: str, cls: str = "") -> Dict:
    p: Dict[str, Any] = {"content": content}
    if cls:
        p["class"] = cls
    return {"type": "text", "props": p}

def make_button(label: str, link: str = "#", style: str = "primary") -> Dict:
    return {"type": "button", "props": {"content": label, "link": link, "button_style": style}}

def make_image(src: str, alt: str = "") -> Dict:
    return {"type": "image", "props": {"image": src, "image_alt": alt}}

def make_panel(title: str, content: str, style: str = "card-default") -> Dict:
    return {"type": "panel", "props": {"title": title, "content": content, "panel_style": style, "hover": True}}

def make_grid(columns: List[List[Dict]], gutter: str = "medium", widths: List[str] = None) -> Dict:
    """Build a row/column grid from a list-of-column-children."""
    n = len(columns)
    default_widths = {1: ["1-1"], 2: ["1-2", "1-2"], 3: ["1-3", "1-3", "1-3"],
                      4: ["1-4", "1-4", "1-4", "1-4"]}.get(n, ["1-1"] * n)
    ws = widths or default_widths
    cols = [make_column(ws[i] if i < len(ws) else "1-1", children=col_children)
            for i, col_children in enumerate(columns)]
    return make_row({"gutter": gutter}, cols)

def wrap_for_joomla(layout: Dict) -> str:
    """Embed layout JSON inside an HTML comment (YOOtheme's storage format)."""
    return f"<!--{json.dumps(layout, separators=(',', ':'))}-->"

def unwrap_from_joomla(html: str) -> Optional[Dict]:
    """Extract YOOtheme layout JSON from HTML comment wrapper."""
    m = _re.search(r"<!--(\{.*?\})-->", html, _re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None

def validate_layout(layout: Any) -> Tuple[bool, List[str]]:
    """Basic structural validation of a YOOtheme layout dict."""
    errors: List[str] = []
    if not isinstance(layout, dict):
        return False, ["Layout must be a dict"]
    if layout.get("type") != "layout":
        errors.append(f"Root type must be 'layout', got '{layout.get('type')}'")
    if not isinstance(layout.get("children"), list):
        errors.append("Root 'children' must be a list")
    for i, child in enumerate(layout.get("children", [])):
        if not isinstance(child, dict):
            errors.append(f"Child {i} must be a dict")
        elif child.get("type") != "section":
            errors.append(f"Child {i} type should be 'section', got '{child.get('type')}'")
    return len(errors) == 0, errors


# ---------------------------------------------------------------------------
# YooLayoutEngine — full CRUD with undo/redo
# ---------------------------------------------------------------------------

@dataclass
class LayoutSnapshot:
    layout: Dict
    label: str
    at: float = field(default_factory=time.time)


class YooLayoutEngine:
    """
    Python port of openflow-builder-main/server/yoothemeLayoutEngine.ts.

    Provides:
    - load() / load_from_joomla()     : parse layout from JSON or HTML
    - wrap_for_joomla()               : serialize to HTML comment
    - add_section() / remove_section() / move_section()
    - node_at_path() / update_at_path() / find_by_type()
    - undo() / redo()                 : 50-deep snapshot history
    - stats                           : section/row/col/element counts
    """

    MAX_HISTORY = 50

    def __init__(self, layout: Dict = None):
        self._current: Dict = copy.deepcopy(layout) if layout else make_layout([])
        self._history: List[LayoutSnapshot] = []
        self._future: List[LayoutSnapshot] = []

    # ── Getters ──────────────────────────────────────────────────────────────

    @property
    def layout(self) -> Dict:
        return copy.deepcopy(self._current)

    @property
    def json(self) -> str:
        return json.dumps(self._current, indent=2)

    @property
    def joomla_html(self) -> str:
        return wrap_for_joomla(self._current)

    @property
    def stats(self) -> Dict:
        counts = {"section": 0, "row": 0, "column": 0, "element": 0, "total": 0}
        max_depth = [0]

        def traverse(nodes, depth):
            if depth > max_depth[0]:
                max_depth[0] = depth
            for node in nodes:
                counts["total"] += 1
                t = node.get("type", "element")
                if t in counts:
                    counts[t] += 1
                else:
                    counts["element"] += 1
                traverse(node.get("children", []), depth + 1)

        traverse(self._current.get("children", []), 0)
        counts["depth"] = max_depth[0]
        counts["snapshots"] = len(self._history)
        return counts

    # ── Snapshots ─────────────────────────────────────────────────────────────

    def _snapshot(self, label: str):
        self._history.append(LayoutSnapshot(copy.deepcopy(self._current), label))
        if len(self._history) > self.MAX_HISTORY:
            self._history.pop(0)
        self._future.clear()

    def undo(self) -> Dict:
        if not self._history:
            return {"success": False, "message": "Nothing to undo"}
        snap = self._history.pop()
        self._future.append(LayoutSnapshot(copy.deepcopy(self._current), f"Before: {snap.label}"))
        self._current = snap.layout
        return {"success": True, "label": snap.label}

    def redo(self) -> Dict:
        if not self._future:
            return {"success": False, "message": "Nothing to redo"}
        snap = self._future.pop()
        self._history.append(LayoutSnapshot(copy.deepcopy(self._current), snap.label))
        self._current = snap.layout
        return {"success": True, "label": snap.label}

    def history(self) -> List[Dict]:
        return [{"label": s.label, "at": s.at} for s in self._history]

    # ── Load / Replace ────────────────────────────────────────────────────────

    def load(self, layout: Any, label: str = "Load") -> Tuple[bool, List[str]]:
        if isinstance(layout, str):
            try:
                layout = json.loads(layout)
            except Exception as e:
                return False, [f"JSON parse error: {e}"]
        ok, errors = validate_layout(layout)
        if not ok:
            return False, errors
        self._snapshot(label)
        self._current = layout
        return True, []

    def load_from_joomla(self, html: str) -> Tuple[bool, List[str]]:
        layout = unwrap_from_joomla(html)
        if layout is None:
            return False, ["No YOOtheme layout found in HTML (expected <!--{...}-->)"]
        return self.load(layout, "Load from Joomla")

    def replace(self, layout: Dict):
        self._snapshot("Replace")
        self._current = copy.deepcopy(layout)

    # ── Section CRUD ──────────────────────────────────────────────────────────

    def add_section(self, props: Dict = None, at_index: int = None, children: List[Dict] = None) -> Dict:
        self._snapshot("Add section")
        row = make_row(children=[make_column("1-1", children=children or [])])
        section = make_section(props or {}, [row])
        c = self._current.setdefault("children", [])
        if at_index is not None:
            c.insert(at_index, section)
        else:
            c.append(section)
        return section

    def remove_section(self, index: int) -> Dict:
        c = self._current.get("children", [])
        if index < 0 or index >= len(c):
            return {"success": False, "error": f"Section index {index} out of range (0-{len(c)-1})"}
        self._snapshot(f"Remove section {index}")
        removed = c.pop(index)
        return {"success": True, "removed_type": removed.get("type")}

    def move_section(self, from_index: int, to_index: int) -> Dict:
        c = self._current.get("children", [])
        n = len(c)
        if not (0 <= from_index < n and 0 <= to_index < n):
            return {"success": False, "error": "Index out of range"}
        self._snapshot(f"Move section {from_index} → {to_index}")
        section = c.pop(from_index)
        c.insert(to_index, section)
        return {"success": True}

    def replace_section(self, index: int, section: Dict) -> Dict:
        c = self._current.get("children", [])
        if index < 0 or index >= len(c):
            return {"success": False, "error": "Index out of range"}
        self._snapshot(f"Replace section {index}")
        c[index] = copy.deepcopy(section)
        return {"success": True}

    # ── Generic node ops (by path) ────────────────────────────────────────────

    def _navigate_path(self, path: List[int]) -> Optional[Dict]:
        node = self._current
        for step in path:
            children = node.get("children", [])
            if step < 0 or step >= len(children):
                return None
            node = children[step]
        return node

    def node_at_path(self, path: List[int]) -> Optional[Dict]:
        n = self._navigate_path(path)
        return copy.deepcopy(n) if n else None

    def update_at_path(self, path: List[int], props: Dict) -> Dict:
        node = self._navigate_path(path)
        if node is None:
            return {"success": False, "error": f"No node at path {path}"}
        self._snapshot(f"Update node at {path}")
        node.setdefault("props", {}).update(props)
        return {"success": True}

    def find_by_type(self, node_type: str) -> List[Dict]:
        results: List[Dict] = []

        def traverse(nodes, path):
            for i, node in enumerate(nodes):
                p = path + [i]
                if node.get("type") == node_type:
                    results.append({"node": copy.deepcopy(node), "path": p})
                traverse(node.get("children", []), p)

        traverse(self._current.get("children", []), [])
        return results

    def append_to_first_column(self, section_index: int, element: Dict) -> Dict:
        """Add an element to the first column of the first row of a section."""
        try:
            section = self._current["children"][section_index]
            row = section["children"][0]
            col = row["children"][0]
            self._snapshot(f"Append element to section {section_index}/col 0")
            col.setdefault("children", []).append(copy.deepcopy(element))
            return {"success": True}
        except (IndexError, KeyError) as e:
            return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# YOO AI prompt builder
# ---------------------------------------------------------------------------

# Full schema injected into every AI layout generation call
_YOO_SCHEMA_PRIMER = """
YOOtheme Pro Layout JSON Schema:
- Root: {"type":"layout","version":"4.5.33","name":"string","children":[...sections]}
- Section: {"type":"section","props":{"style":"default|muted|primary|secondary","width":"default|large|xlarge","padding_top":"none|small|default|large|xlarge","padding_bottom":"none|small|default|large|xlarge","text_align":"left|center|right","name":"string","image":"url or empty","image_size":"cover","media_overlay":"rgba(0,0,0,0.5) or empty"},"children":[...rows]}
- Row: {"type":"row","props":{"gutter":"small|medium|large|collapse"},"children":[...columns]}
- Column: {"type":"column","props":{"width_bp":"1-1|1-2|1-3|2-3|1-4|3-4|auto","vertical_align":"top|middle|bottom"},"children":[...elements]}
- Headline: {"type":"headline","props":{"content":"string","title_element":"h1|h2|h3|h4","title_style":"heading-2xlarge|heading-xlarge|heading-large|heading-medium|heading-small","title_color":"","text_align":"left|center|right","margin":"small|default|large"}}
- Text: {"type":"text","props":{"content":"<p>HTML string</p>","class":"uk-text-lead|uk-text-small|uk-text-muted"}}
- Button: {"type":"button","props":{"content":"string","link":"#","button_style":"primary|secondary|default|text","button_size":"small|default|large","button_width":""}}
- Image: {"type":"image","props":{"image":"url","image_alt":"string","image_width":"","image_height":"","image_cover":false}}
- Panel: {"type":"panel","props":{"title":"string","content":"string","panel_style":"card-default|card-primary|card-secondary","hover":true,"title_element":"h3"}}
- Grid (repeated panels): use row + multiple 1-3 or 1-4 columns each containing a panel element
""".strip()


def _build_generation_prompt(request: str, section_type: str = None, extra_context: str = "") -> str:
    type_hint = f" Focus on creating a '{section_type}' section." if section_type else ""
    return f"""You are a YOOtheme Pro expert. Generate a complete YOOtheme layout JSON object.
{_YOO_SCHEMA_PRIMER}

RULES:
- Output ONLY valid JSON — no markdown fences, no explanation, no extra text
- Every section must have at least one row → column → element path
- Use realistic, professional content for the requested topic
- section props.name should be human-readable (e.g. "Hero", "Features", "Contact")
- Buttons must have valid link values (use "#" for placeholders)
- Text content in text elements must be valid HTML (wrap in <p> tags)
{extra_context}

REQUEST: {request}{type_hint}

Return the full layout JSON object starting with {{"type":"layout",...}}"""


# ---------------------------------------------------------------------------
# YooTheme MCP Server
# ---------------------------------------------------------------------------

class YooThemeMCPServer(NativeMCPServer):
    """
    26-tool MCP server for natural-language YOOtheme Pro builder operations.

    Config keys (set via MCP Hub Config drawer or env vars):
      AI_PROVIDER          — ollama | ollama_cloud | lmstudio | gemini (default: gemini)
      OLLAMA_HOST          — local Ollama host (default: http://localhost:11434)
      OLLAMA_MODEL         — local Ollama model (default: llama3)
      OLLAMA_API_KEY       — optional, for protected Ollama servers
      OLLAMA_CLOUD_API_KEY — required for ollama_cloud (from ollama.com/settings/keys)
      OLLAMA_CLOUD_MODEL   — cloud model tag (default: gpt-oss:120b)
      LMSTUDIO_HOST        — LM Studio host (default: http://localhost:1234)
      LMSTUDIO_MODEL       — LM Studio model name
      GEMINI_API_KEY       — Google Gemini key
      GEMINI_MODEL         — Gemini model (default: gemini-2.0-flash)
      JOOMLA_BASE_URL      — Joomla site URL for REST API layout r/w
      BEARER_TOKEN         — Joomla REST API bearer token
      YOOMYSQL_HOST        — MySQL host for direct DB access
      YOOMYSQL_PORT        — MySQL port (default: 3306)
      YOOMYSQL_USER        — MySQL username
      YOOMYSQL_PASSWORD    — MySQL password
      YOOMYSQL_DATABASE    — Joomla database name
      YOOMYSQL_PREFIX      — Joomla table prefix (default: jos_)
    """

    def __init__(self, config: Dict[str, str] = None):
        super().__init__(
            id="yootheme",
            name="YOOtheme Builder",
            category="yootheme",
            icon="🏗",
            description=(
                "Natural-language YOOtheme Pro page building agent. "
                "Generate full layouts, add/remove/reorder sections, manage YOO JSON layout trees, "
                "and write layouts directly to Joomla articles via REST or MySQL."
            ),
            tools=[],
            config=config or {},
        )
        # Per-session layout engines (keyed by session_id param)
        self._engines: Dict[str, YooLayoutEngine] = {}
        self._register_all_tools()

    def _get_engine(self, session_id: str = "default") -> YooLayoutEngine:
        if session_id not in self._engines:
            self._engines[session_id] = YooLayoutEngine()
        return self._engines[session_id]

    # ── AI generation ─────────────────────────────────────────────────────────

    def _resolve_provider(self, params: Dict) -> str:
        return (
            (params.get("ai_service") or "").strip()
            or (self.config.get("AI_PROVIDER") or "").strip()
            or "gemini"
        ).lower()

    def _generate_with_ai(self, prompt: str, provider: str, max_tokens: int = 3000) -> str:
        try:
            if provider == "ollama":
                import ollama as _ollama
                raw_host = self.config.get("OLLAMA_HOST", "http://localhost:11434")
                host = _re.sub(r"/api/?$", "", raw_host.rstrip("/"))
                model = self.config.get("OLLAMA_MODEL", "llama3")
                local_key = self.config.get("OLLAMA_API_KEY", "")
                kw: Dict[str, Any] = {"host": host}
                if local_key:
                    kw["headers"] = {"Authorization": f"Bearer {local_key}"}
                oc = _ollama.Client(**kw)
                resp = oc.chat(model=model, messages=[{"role": "user", "content": prompt}],
                               options={"num_predict": max_tokens, "temperature": 0.3})
                return resp["message"]["content"].strip()

            elif provider == "ollama_cloud":
                import ollama as _ollama
                cloud_key = self.config.get("OLLAMA_CLOUD_API_KEY", "")
                if not cloud_key:
                    return "Error: OLLAMA_CLOUD_API_KEY not configured."
                model = self.config.get("OLLAMA_CLOUD_MODEL", "gpt-oss:120b")
                oc = _ollama.Client(host="https://ollama.com",
                                    headers={"Authorization": f"Bearer {cloud_key}"})
                resp = oc.chat(model=model, messages=[{"role": "user", "content": prompt}],
                               options={"num_predict": max_tokens, "temperature": 0.3})
                return resp["message"]["content"].strip()

            elif provider == "lmstudio":
                import httpx as _hx
                host = self.config.get("LMSTUDIO_HOST", "http://localhost:1234").rstrip("/")
                model = self.config.get("LMSTUDIO_MODEL", "local-model")
                body = {"model": model, "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": max_tokens, "temperature": 0.3, "stream": False}
                with _hx.Client(timeout=120) as hc:
                    r = hc.post(f"{host}/v1/chat/completions", json=body)
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"].strip()

            elif provider == "gemini":
                from google import genai as _genai
                key = self.config.get("GEMINI_API_KEY", "")
                if not key:
                    return "Error: GEMINI_API_KEY not configured. Set it in the YOO Builder Config drawer."
                _gc = _genai.Client(api_key=key)
                resp = _gc.models.generate_content(
                    model=self.config.get("GEMINI_MODEL", "gemini-2.0-flash"),
                    contents=prompt,
                )
                return resp.text

            else:
                return f"Error: Unknown AI provider '{provider}'."

        except Exception as e:
            return f"AI error ({provider} / {type(e).__name__}): {e}"

    def _ai_json(self, prompt: str, provider: str) -> Tuple[Optional[Dict], str]:
        """Call AI, parse JSON, return (parsed_dict_or_None, raw_text)."""
        raw = self._generate_with_ai(prompt, provider)
        if raw.startswith("Error"):
            return None, raw
        # Strip markdown fences if present
        clean = _re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=_re.IGNORECASE)
        clean = _re.sub(r"\s*```$", "", clean.strip())
        # Try to extract first JSON object
        m = _re.search(r"\{.*\}", clean, _re.DOTALL)
        if m:
            clean = m.group(0)
        try:
            return json.loads(clean), raw
        except Exception as e:
            return None, f"AI returned invalid JSON ({e}):\n{raw[:800]}"

    # ── Joomla REST helpers ───────────────────────────────────────────────────

    def _joomla_headers(self) -> Dict:
        return {
            "Accept": "application/vnd.api+json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.get('BEARER_TOKEN', '')}",
        }

    def _art_url(self, aid: Any = None) -> str:
        base = self.config.get("JOOMLA_BASE_URL", "").rstrip("/")
        url = f"{base}/api/index.php/v1/content/articles"
        return f"{url}/{aid}" if aid else url

    def _rest_get_article(self, aid: int) -> Tuple[Optional[Dict], str]:
        try:
            import httpx
            r = httpx.get(self._art_url(aid), headers=self._joomla_headers(), timeout=15)
            if r.status_code != 200:
                return None, f"HTTP {r.status_code}"
            return r.json().get("data", {}).get("attributes", {}), ""
        except Exception as e:
            return None, str(e)

    def _rest_write_introtext(self, aid: int, introtext: str) -> Tuple[bool, str]:
        try:
            import httpx
            r = httpx.patch(self._art_url(aid),
                            json={"introtext": introtext},
                            headers=self._joomla_headers(), timeout=15)
            ok = r.status_code in (200, 204)
            return ok, "" if ok else f"HTTP {r.status_code}"
        except Exception as e:
            return False, str(e)

    # ── MySQL helpers ─────────────────────────────────────────────────────────

    def _mysql_pool(self):
        cfg = self.config
        host     = cfg.get("YOOMYSQL_HOST", "")
        user     = cfg.get("YOOMYSQL_USER", "")
        password = cfg.get("YOOMYSQL_PASSWORD", "")
        database = cfg.get("YOOMYSQL_DATABASE", "")
        if not all([host, user, database]):
            raise ValueError(
                "MySQL not configured. Set YOOMYSQL_HOST / YOOMYSQL_USER / "
                "YOOMYSQL_PASSWORD / YOOMYSQL_DATABASE in the YOO Builder Config."
            )
        import mysql.connector  # type: ignore
        return mysql.connector.connect(
            host=host,
            port=int(cfg.get("YOOMYSQL_PORT", "3306")),
            user=user,
            password=password,
            database=database,
        )

    def _mysql_prefix(self) -> str:
        return self.config.get("YOOMYSQL_PREFIX", "jos_")

    # =========================================================================
    # Tool implementations
    # =========================================================================

    # ── AI Generation Tools ───────────────────────────────────────────────────

    def _tool_yoo_generate_page(self, params: Dict, _dir: str) -> str:
        request  = params.get("request", "")
        sections = params.get("sections", [])
        provider = self._resolve_provider(params)
        session  = params.get("session_id", "default")
        if not request:
            return "Error: 'request' param required. Describe the page you want to build."
        extra = f"Build these section types in order: {', '.join(sections)}." if sections else ""
        prompt = _build_generation_prompt(request, extra_context=extra)
        layout, raw = self._ai_json(prompt, provider)
        if layout is None:
            return raw
        ok, errors = validate_layout(layout)
        if not ok:
            return f"AI returned invalid layout: {'; '.join(errors)}\n\nRaw:\n{raw[:500]}"
        engine = self._get_engine(session)
        engine.replace(layout)
        s = engine.stats
        return (
            f"Layout generated and loaded into session '{session}'.\n"
            f"Sections: {s['section']} | Rows: {s['row']} | Columns: {s['column']} | Elements: {s['element']}\n\n"
            f"Use yoo_set_layout to save to a Joomla article, or yoo_get_layout_json to view the JSON."
        )

    def _tool_yoo_add_section(self, params: Dict, _dir: str) -> str:
        section_type = params.get("section_type", "custom")
        request      = params.get("description", "")
        provider     = self._resolve_provider(params)
        at_index     = params.get("at_index")
        session      = params.get("session_id", "default")

        PRESETS = {
            "hero":        "Add a hero/banner section with headline, subtext, and a CTA button",
            "features":    "Add a features/services grid with 3 cards showing icons and descriptions",
            "cta":         "Add a call-to-action section with bold heading, supporting text, and 2 buttons",
            "testimonials":"Add a testimonials section with 3 customer reviews in card style",
            "pricing":     "Add a pricing section with 3 plans (Basic, Pro, Enterprise) in card columns",
            "gallery":     "Add an image gallery grid section with 6 placeholder images in 3 columns",
            "contact":     "Add a contact section with address, phone, email, and a prompt to contact us",
            "about":       "Add an about us section with headline, story paragraph, and a team photo placeholder",
            "faq":         "Add a FAQ section with 5 common questions and answers in accordion style panels",
            "video":       "Add a video section with a centered headline and embedded video placeholder",
        }
        desc = request or PRESETS.get(section_type, f"Add a {section_type} section")
        prompt = _build_generation_prompt(
            desc, section_type=section_type,
            extra_context="Generate ONLY a single section object (type:section with children), NOT a full layout. "
                          "Return just the section JSON starting with {\"type\":\"section\",...}"
        )
        raw = self._generate_with_ai(prompt, provider)
        if raw.startswith("Error"):
            return raw
        clean = _re.sub(r"^```(?:json)?\s*", "", raw.strip(), _re.IGNORECASE)
        clean = _re.sub(r"\s*```$", "", clean.strip())
        m = _re.search(r"\{.*\}", clean, _re.DOTALL)
        if m:
            clean = m.group(0)
        try:
            section_node = json.loads(clean)
        except Exception as e:
            return f"AI returned invalid JSON for section ({e}):\n{raw[:600]}"

        engine = self._get_engine(session)
        if section_node.get("type") != "section":
            section_node = make_section(props={"name": section_type.title()}, children=[
                make_row(children=[make_column("1-1", children=[section_node])])
            ])

        engine._snapshot(f"Add {section_type} section")
        c = engine._current.setdefault("children", [])
        if at_index is not None:
            c.insert(int(at_index), section_node)
        else:
            c.append(section_node)

        return (
            f"'{section_type.title()}' section added to session '{session}' "
            f"(now {len(c)} sections total).\n"
            "Use yoo_set_layout to save to Joomla."
        )

    def _tool_yoo_compose_layout(self, params: Dict, _dir: str) -> str:
        section_types = params.get("sections", ["hero", "features", "cta", "contact"])
        topic         = params.get("topic", "a professional website")
        provider      = self._resolve_provider(params)
        session       = params.get("session_id", "default")
        request       = f"Build a complete {topic} page with sections: {', '.join(section_types)}"
        prompt = _build_generation_prompt(request)
        layout, raw = self._ai_json(prompt, provider)
        if layout is None:
            return raw
        ok, errors = validate_layout(layout)
        if not ok:
            return f"Invalid layout: {'; '.join(errors)}"
        engine = self._get_engine(session)
        engine.replace(layout)
        s = engine.stats
        return (
            f"Layout composed: {s['section']} sections, {s['element']} elements.\n"
            f"Topic: {topic}\nSections: {', '.join(section_types)}\n"
            "Use yoo_set_layout to write to Joomla."
        )

    def _tool_yoo_image_to_layout(self, params: Dict, _dir: str) -> str:
        description = params.get("description", "")
        url         = params.get("url", "")
        provider    = self._resolve_provider(params)
        session     = params.get("session_id", "default")
        context = description or url or "a professional landing page"
        prompt = _build_generation_prompt(
            f"Analyze this design and generate matching YOOtheme layout: {context}",
            extra_context=(
                "If a URL is provided, imagine the page structure from the URL context. "
                "Match the visual hierarchy: hero → content sections → CTA → footer sections."
            )
        )
        layout, raw = self._ai_json(prompt, provider)
        if layout is None:
            return raw
        ok, errors = validate_layout(layout)
        if not ok:
            return f"Invalid layout: {'; '.join(errors)}"
        engine = self._get_engine(session)
        engine.replace(layout)
        s = engine.stats
        return f"Image/URL mapped to layout: {s['section']} sections, {s['element']} elements."

    # ── Layout Engine Tools ───────────────────────────────────────────────────

    def _tool_yoo_get_layout_json(self, params: Dict, _dir: str) -> str:
        session = params.get("session_id", "default")
        engine  = self._get_engine(session)
        s = engine.stats
        return (
            f"Session: '{session}' | "
            f"{s['section']} sections | {s['row']} rows | {s['column']} columns | {s['element']} elements\n\n"
            + engine.json
        )

    def _tool_yoo_load_layout(self, params: Dict, _dir: str) -> str:
        layout_json = params.get("layout_json", "")
        session     = params.get("session_id", "default")
        if not layout_json:
            return "Error: 'layout_json' param required."
        engine = self._get_engine(session)
        ok, errors = engine.load(layout_json, "User load")
        if not ok:
            return f"Load failed: {'; '.join(errors)}"
        s = engine.stats
        return f"Layout loaded: {s['section']} sections, {s['element']} elements."

    def _tool_yoo_remove_section(self, params: Dict, _dir: str) -> str:
        index   = int(params.get("index", 0))
        session = params.get("session_id", "default")
        engine  = self._get_engine(session)
        result  = engine.remove_section(index)
        if not result.get("success"):
            return f"Error: {result.get('error')}"
        s = engine.stats
        return f"Section {index} removed. {s['section']} sections remain."

    def _tool_yoo_move_section(self, params: Dict, _dir: str) -> str:
        from_i  = int(params.get("from_index", 0))
        to_i    = int(params.get("to_index", 1))
        session = params.get("session_id", "default")
        engine  = self._get_engine(session)
        result  = engine.move_section(from_i, to_i)
        return f"Section {from_i} moved to position {to_i}." if result.get("success") else f"Error: {result.get('error')}"

    def _tool_yoo_update_element(self, params: Dict, _dir: str) -> str:
        path    = params.get("path", [])
        props   = params.get("props", {})
        session = params.get("session_id", "default")
        engine  = self._get_engine(session)
        result  = engine.update_at_path(path, props)
        return "Element updated." if result.get("success") else f"Error: {result.get('error')}"

    def _tool_yoo_get_stats(self, params: Dict, _dir: str) -> str:
        session = params.get("session_id", "default")
        s       = self._get_engine(session).stats
        return (
            f"YOO Layout Stats — session: '{session}'\n"
            f"  Sections : {s['section']}\n"
            f"  Rows     : {s['row']}\n"
            f"  Columns  : {s['column']}\n"
            f"  Elements : {s['element']}\n"
            f"  Total    : {s['total']}\n"
            f"  Depth    : {s['depth']}\n"
            f"  Snapshots: {s['snapshots']}"
        )

    def _tool_yoo_validate_layout(self, params: Dict, _dir: str) -> str:
        session = params.get("session_id", "default")
        engine  = self._get_engine(session)
        ok, errors = validate_layout(engine.layout)
        if ok:
            return f"Layout valid. {engine.stats['section']} sections, {engine.stats['total']} nodes."
        return "Layout INVALID:\n" + "\n".join(f"  - {e}" for e in errors)

    def _tool_yoo_undo(self, params: Dict, _dir: str) -> str:
        session = params.get("session_id", "default")
        result  = self._get_engine(session).undo()
        return (f"Undone: '{result['label']}'" if result["success"]
                else "Nothing to undo.")

    def _tool_yoo_redo(self, params: Dict, _dir: str) -> str:
        session = params.get("session_id", "default")
        result  = self._get_engine(session).redo()
        return (f"Redone: '{result['label']}'" if result["success"]
                else "Nothing to redo.")

    def _tool_yoo_list_presets(self, params: Dict, _dir: str) -> str:
        presets = [
            ("hero",        "Full-width hero with headline, subtext, CTA button"),
            ("features",    "3-column feature grid with icons and descriptions"),
            ("cta",         "Bold call-to-action with heading and 2 buttons"),
            ("testimonials","3 customer review cards"),
            ("pricing",     "3-tier pricing table (Basic / Pro / Enterprise)"),
            ("gallery",     "6-image responsive gallery grid"),
            ("contact",     "Contact section with address, phone, email"),
            ("about",       "About section with story text and team image"),
            ("faq",         "5-question FAQ in accordion-style panels"),
            ("video",       "Centered headline with video embed placeholder"),
        ]
        lines = ["Available YOOtheme section presets:", ""]
        for name, desc in presets:
            lines.append(f"  {name:15} — {desc}")
        lines += ["", "Use: yoo_add_section(section_type='hero', session_id='my-page')"]
        return "\n".join(lines)

    # ── Joomla REST Layout R/W ────────────────────────────────────────────────

    def _tool_yoo_read_layout_from_article(self, params: Dict, _dir: str) -> str:
        aid     = int(params.get("article_id", 0))
        session = params.get("session_id", str(aid))
        if not aid:
            return "Error: 'article_id' required."
        art, err = self._rest_get_article(aid)
        if art is None:
            return f"Failed to fetch article {aid}: {err}"
        introtext = art.get("introtext", "")
        engine = self._get_engine(session)
        ok, errors = engine.load_from_joomla(introtext)
        if not ok:
            return (
                f"Article {aid} loaded but has no YOOtheme layout (or layout is invalid).\n"
                f"Errors: {'; '.join(errors)}\n"
                f"Introtext snippet: {introtext[:200]}"
            )
        s = engine.stats
        return (
            f"Layout loaded from article {aid} into session '{session}'.\n"
            f"Sections: {s['section']} | Elements: {s['element']}"
        )

    def _tool_yoo_set_layout(self, params: Dict, _dir: str) -> str:
        aid     = int(params.get("article_id", 0))
        session = params.get("session_id", "default")
        if not aid:
            return "Error: 'article_id' required."
        engine = self._get_engine(session)
        s = engine.stats
        if s["total"] == 0:
            return "Error: Session engine is empty. Generate a layout first."
        ok, errors = validate_layout(engine.layout)
        if not ok:
            return f"Cannot save — layout is invalid: {'; '.join(errors)}"
        html_comment = engine.joomla_html
        base = self.config.get("JOOMLA_BASE_URL", "")
        token = self.config.get("BEARER_TOKEN", "")
        if not base or not token:
            return (
                "Joomla REST not configured. Set JOOMLA_BASE_URL and BEARER_TOKEN "
                "in the YOO Builder Config drawer.\n\n"
                f"Layout JSON preview ({s['section']} sections):\n{engine.json[:800]}"
            )
        written, err = self._rest_write_introtext(aid, html_comment)
        if not written:
            return f"Failed to write layout to article {aid}: {err}"
        return (
            f"Layout saved to article {aid}.\n"
            f"Sections: {s['section']} | Elements: {s['element']}\n"
            f"Stored as <!--{{...}}--> in article introtext."
        )

    def _tool_yoo_list_articles_with_layouts(self, params: Dict, _dir: str) -> str:
        limit  = int(params.get("limit", 20))
        base   = self.config.get("JOOMLA_BASE_URL", "").rstrip("/")
        token  = self.config.get("BEARER_TOKEN", "")
        if not base or not token:
            return "Joomla not configured. Set JOOMLA_BASE_URL and BEARER_TOKEN."
        try:
            import httpx
            r = httpx.get(f"{base}/api/index.php/v1/content/articles",
                          headers=self._joomla_headers(), timeout=15)
            r.raise_for_status()
            arts = r.json().get("data", [])[:limit]
            rows = []
            for art in arts:
                a = art.get("attributes", {})
                intro = a.get("introtext", "")
                has_yoo = bool(_re.search(r'<!--\{"type":"layout"', intro))
                rows.append(
                    f"  [{a.get('id'):>4}] {'✅' if has_yoo else '  '} {a.get('title', '')}"
                )
            return (
                "Joomla articles (✅ = has YOOtheme layout):\n"
                + "\n".join(rows)
                + f"\n\nShowing {len(rows)} of {len(arts)} total."
            )
        except Exception as e:
            return f"Error: {e}"

    # ── MySQL Direct R/W ──────────────────────────────────────────────────────

    def _tool_yoo_mysql_read_layout(self, params: Dict, _dir: str) -> str:
        aid     = int(params.get("article_id", 0))
        session = params.get("session_id", str(aid))
        if not aid:
            return "Error: 'article_id' required."
        try:
            conn = self._mysql_pool()
            prefix = self._mysql_prefix()
            cur = conn.cursor(dictionary=True)
            cur.execute(f"SELECT id, title, introtext FROM `{prefix}content` WHERE id = %s", (aid,))
            row = cur.fetchone()
            conn.close()
            if not row:
                return f"Article {aid} not found."
            intro = row.get("introtext", "")
            engine = self._get_engine(session)
            ok, errors = engine.load_from_joomla(intro)
            if not ok:
                return (
                    f"Article {aid} ('{row['title']}') has no YOOtheme layout.\n"
                    f"Errors: {'; '.join(errors)}"
                )
            s = engine.stats
            return (
                f"Layout read from MySQL: article {aid} '{row['title']}'\n"
                f"Sections: {s['section']} | Elements: {s['element']}\n"
                f"Session: '{session}'"
            )
        except ValueError as e:
            return f"MySQL not configured: {e}"
        except Exception as e:
            return f"MySQL error: {type(e).__name__}: {e}"

    def _tool_yoo_mysql_write_layout(self, params: Dict, _dir: str) -> str:
        aid     = int(params.get("article_id", 0))
        session = params.get("session_id", "default")
        if not aid:
            return "Error: 'article_id' required."
        engine = self._get_engine(session)
        ok, errors = validate_layout(engine.layout)
        if not ok:
            return f"Invalid layout: {'; '.join(errors)}"
        html_comment = engine.joomla_html
        try:
            conn = self._mysql_pool()
            prefix = self._mysql_prefix()
            cur = conn.cursor()
            cur.execute(
                f"UPDATE `{prefix}content` SET introtext = %s WHERE id = %s",
                (html_comment, aid)
            )
            conn.commit()
            affected = cur.rowcount
            conn.close()
            if affected == 0:
                return f"No rows updated. Article {aid} may not exist."
            s = engine.stats
            return (
                f"Layout written directly to MySQL: article {aid}\n"
                f"Sections: {s['section']} | Elements: {s['element']}\n"
                f"Rows affected: {affected}"
            )
        except ValueError as e:
            return f"MySQL not configured: {e}"
        except Exception as e:
            return f"MySQL error: {type(e).__name__}: {e}"

    def _tool_yoo_mysql_list_articles(self, params: Dict, _dir: str) -> str:
        limit = int(params.get("limit", 50))
        only_with_layouts = params.get("only_with_layouts", False)
        try:
            conn = self._mysql_pool()
            prefix = self._mysql_prefix()
            cur = conn.cursor(dictionary=True)
            if only_with_layouts:
                cur.execute(
                    f"SELECT id, title, catid, state, introtext "
                    f"FROM `{prefix}content` "
                    f"WHERE introtext LIKE %s "
                    f"ORDER BY modified DESC LIMIT %s",
                    ('%<!--{"type":"layout"%', limit)
                )
            else:
                cur.execute(
                    f"SELECT id, title, catid, state, introtext "
                    f"FROM `{prefix}content` "
                    f"ORDER BY modified DESC LIMIT %s",
                    (limit,)
                )
            rows = cur.fetchall()
            conn.close()
            lines = [f"{'ID':>4}  {'State':5}  {'YOO':3}  Title"]
            for r in rows:
                has_yoo = "<!--{\"type\":\"layout\"" in (r.get("introtext") or "")
                state = {1: "pub", 0: "unp", 2: "arch", -2: "trash"}.get(r.get("state", 0), "?")
                lines.append(f"{r['id']:>4}  {state:5}  {'✅' if has_yoo else '  ':3}  {r['title']}")
            return "\n".join(lines)
        except ValueError as e:
            return f"MySQL not configured: {e}"
        except Exception as e:
            return f"MySQL error: {type(e).__name__}: {e}"

    # ── Template Config ───────────────────────────────────────────────────────

    def _tool_yoo_get_template_config(self, params: Dict, _dir: str) -> str:
        style_id = int(params.get("style_id", 0))
        try:
            conn = self._mysql_pool()
            prefix = self._mysql_prefix()
            cur = conn.cursor(dictionary=True)
            query = f"SELECT id, title, params FROM `{prefix}template_styles` WHERE client_id = 0"
            if style_id:
                query += f" AND id = {style_id}"
            cur.execute(query)
            rows = cur.fetchall()
            conn.close()
            if not rows:
                return "No template styles found."
            results = []
            for row in rows:
                try:
                    p = json.loads(row.get("params", "{}"))
                    yoo_config = p.get("config", {})
                    results.append(f"[{row['id']}] {row['title']}: {json.dumps(yoo_config, indent=2)[:400]}")
                except Exception:
                    results.append(f"[{row['id']}] {row['title']}: (could not parse params)")
            return "\n\n".join(results)
        except ValueError as e:
            return f"MySQL not configured: {e}"
        except Exception as e:
            return f"MySQL error: {type(e).__name__}: {e}"

    def _tool_yoo_set_template_config(self, params: Dict, _dir: str) -> str:
        style_id = int(params.get("style_id", 0))
        config   = params.get("config", {})
        if not style_id or not config:
            return "Error: 'style_id' and 'config' dict required."
        try:
            conn = self._mysql_pool()
            prefix = self._mysql_prefix()
            cur = conn.cursor(dictionary=True)
            cur.execute(f"SELECT params FROM `{prefix}template_styles` WHERE id = %s", (style_id,))
            row = cur.fetchone()
            if not row:
                conn.close()
                return f"Template style {style_id} not found."
            try:
                existing = json.loads(row["params"])
            except Exception:
                existing = {}
            existing.setdefault("config", {}).update(config)
            cur.execute(
                f"UPDATE `{prefix}template_styles` SET params = %s WHERE id = %s",
                (json.dumps(existing), style_id)
            )
            conn.commit()
            affected = cur.rowcount
            conn.close()
            return (f"Template config updated for style {style_id}.\n"
                    f"Keys set: {', '.join(config.keys())}\nRows affected: {affected}")
        except ValueError as e:
            return f"MySQL not configured: {e}"
        except Exception as e:
            return f"MySQL error: {type(e).__name__}: {e}"

    # =========================================================================
    # Tool registration
    # =========================================================================

    def _register_all_tools(self):
        P = "yootheme"

        ai_svc = {"ai_service": {"type": "string",
                                  "description": "ollama|ollama_cloud|lmstudio|gemini (overrides AI_PROVIDER)"}}
        session = {"session_id": {"type": "string",
                                   "description": "In-memory layout session key (default: 'default')"}}

        tools = [
            # ── AI Generation ──────────────────────────────────────────────
            ("yoo_generate_page", self._tool_yoo_generate_page,
             "Natural-language → full YOOtheme layout (generate complete page from description)",
             {**{"request":  {"type": "string", "required": True,
                              "description": "Describe the page you want (e.g. 'Marketing landing page for a plumbing company')"},
                 "sections": {"type": "array",
                              "description": "Ordered list of section types to include: hero, features, cta, testimonials, pricing, gallery, contact"}},
              **ai_svc, **session}),

            ("yoo_add_section", self._tool_yoo_add_section,
             "Add a single section to the current layout (preset or custom AI-generated)",
             {**{"section_type": {"type": "string", "required": True,
                                  "description": "hero|features|cta|testimonials|pricing|gallery|contact|about|faq|video|custom"},
                 "description":  {"type": "string",
                                  "description": "Optional: describe what you want in the section"},
                 "at_index":     {"type": "integer",
                                  "description": "Insert at this position (default: append)"}},
              **ai_svc, **session}),

            ("yoo_compose_layout", self._tool_yoo_compose_layout,
             "Compose a full page layout from a topic and list of section types",
             {**{"topic":    {"type": "string", "required": True,
                              "description": "Subject of the page (e.g. 'Photography studio')"},
                 "sections": {"type": "array",
                              "description": "Section types in order: [hero, features, cta, contact]"}},
              **ai_svc, **session}),

            ("yoo_image_to_layout", self._tool_yoo_image_to_layout,
             "Convert a design description or URL to a matching YOOtheme layout",
             {**{"description": {"type": "string", "description": "Describe the design/page structure"},
                 "url":         {"type": "string", "description": "URL of the page to clone"}},
              **ai_svc, **session}),

            ("yoo_list_presets", self._tool_yoo_list_presets,
             "List all available YOOtheme section preset templates",
             {**session}),

            # ── Layout Engine ──────────────────────────────────────────────
            ("yoo_get_layout_json", self._tool_yoo_get_layout_json,
             "Get the current layout JSON from the in-memory session engine",
             {**session}),

            ("yoo_load_layout", self._tool_yoo_load_layout,
             "Load a YOOtheme layout JSON string into the session engine",
             {**{"layout_json": {"type": "string", "required": True,
                                 "description": "Full YOOtheme JSON string or object"}},
              **session}),

            ("yoo_remove_section", self._tool_yoo_remove_section,
             "Remove a section from the current layout by index",
             {**{"index": {"type": "integer", "required": True,
                           "description": "0-based section index"}},
              **session}),

            ("yoo_move_section", self._tool_yoo_move_section,
             "Reorder a section in the layout",
             {**{"from_index": {"type": "integer", "required": True},
                 "to_index":   {"type": "integer", "required": True}},
              **session}),

            ("yoo_update_element", self._tool_yoo_update_element,
             "Update props on a specific node by path (e.g. [0,0,0] = section 0, row 0, col 0)",
             {**{"path":  {"type": "array",  "required": True,
                           "description": "Node path as int array e.g. [0,0,0,1]"},
                 "props": {"type": "object", "required": True,
                           "description": "Props to merge into the node"}},
              **session}),

            ("yoo_get_stats", self._tool_yoo_get_stats,
             "Get layout statistics: section/row/column/element counts and depth",
             {**session}),

            ("yoo_validate_layout", self._tool_yoo_validate_layout,
             "Validate the current session layout against the YOOtheme schema",
             {**session}),

            ("yoo_undo", self._tool_yoo_undo,
             "Undo the last layout operation (50-deep history)",
             {**session}),

            ("yoo_redo", self._tool_yoo_redo,
             "Redo the last undone layout operation",
             {**session}),

            # ── Joomla REST Layout R/W ─────────────────────────────────────
            ("yoo_read_layout_from_article", self._tool_yoo_read_layout_from_article,
             "Read YOOtheme layout from a Joomla article via REST API and load into session",
             {**{"article_id": {"type": "integer", "required": True}},
              **session}),

            ("yoo_set_layout", self._tool_yoo_set_layout,
             "Write the current session layout to a Joomla article via REST API",
             {**{"article_id": {"type": "integer", "required": True}},
              **session}),

            ("yoo_list_articles_with_layouts", self._tool_yoo_list_articles_with_layouts,
             "List Joomla articles, marking which ones have YOOtheme layouts",
             {"limit": {"type": "integer", "description": "Max articles to list (default 20)"}}),

            # ── MySQL Direct ───────────────────────────────────────────────
            ("yoo_mysql_read_layout", self._tool_yoo_mysql_read_layout,
             "Read YOOtheme layout directly from MySQL #__content table",
             {**{"article_id": {"type": "integer", "required": True}},
              **session}),

            ("yoo_mysql_write_layout", self._tool_yoo_mysql_write_layout,
             "Write current session layout directly to MySQL #__content table (fastest method)",
             {**{"article_id": {"type": "integer", "required": True}},
              **session}),

            ("yoo_mysql_list_articles", self._tool_yoo_mysql_list_articles,
             "List articles from MySQL with YOOtheme layout status",
             {"limit":             {"type": "integer", "description": "Max rows (default 50)"},
              "only_with_layouts": {"type": "boolean",
                                    "description": "Only return articles that have YOO layouts"}}),

            ("yoo_get_template_config", self._tool_yoo_get_template_config,
             "Read YOOtheme template style config from MySQL #__template_styles",
             {"style_id": {"type": "integer", "description": "Specific style ID (0 = all)"}}),

            ("yoo_set_template_config", self._tool_yoo_set_template_config,
             "Write YOOtheme template config keys directly to MySQL #__template_styles",
             {"style_id": {"type": "integer", "required": True},
              "config":   {"type": "object",  "required": True,
                           "description": "Config key-value pairs to merge into template params"}}),
        ]

        for name, fn, desc, parameters in tools:
            self._register_tool(
                name, fn,
                MCPTool(name, desc, parameters, P)
            )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_yootheme_server(config: Dict[str, str] = None) -> YooThemeMCPServer:
    return YooThemeMCPServer(config=config or {})

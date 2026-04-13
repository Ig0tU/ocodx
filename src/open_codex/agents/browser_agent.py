"""
AIO-NUI Browser Agent — Autonomous headed browser agent using Playwright.

The LLM observes a live browser (URL, title, text, screenshot) and decides
what action to take next. Each action is executed via Playwright (Chromium,
headed mode) and a screenshot is captured and yielded as a base64 PNG frame
for live streaming to the Open Codex frontend.

This gives users a real-time Mission Control view of the AI autonomously
controlling a browser to complete any task.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
import threading
import time
from typing import Callable, Generator, Optional

logger = logging.getLogger(__name__)

# ── Action schema ─────────────────────────────────────────────────────────────

BROWSER_TOOLS_DOC = """
BROWSER ACTIONS (pick exactly one per response):

goto        Navigate to a URL
  BROWSER_ACTION: {"action": "goto", "url": "https://example.com"}

click       Click an element by CSS selector
  BROWSER_ACTION: {"action": "click", "selector": "button.submit"}

type        Type text into an input field (clears first)
  BROWSER_ACTION: {"action": "type", "selector": "input#q", "text": "search query"}

scroll      Scroll the page
  BROWSER_ACTION: {"action": "scroll", "direction": "down", "pixels": 600}

wait        Wait for an element or a number of seconds
  BROWSER_ACTION: {"action": "wait", "selector": "#result", "timeout": 5000}
  BROWSER_ACTION: {"action": "wait", "seconds": 2}

screenshot  Take a screenshot (you always get one after every action automatically)
  BROWSER_ACTION: {"action": "screenshot"}

extract     Extract text or attribute from an element
  BROWSER_ACTION: {"action": "extract", "selector": "main", "attr": "innerText"}

key         Press a keyboard key
  BROWSER_ACTION: {"action": "key", "key": "Enter"}

hover       Hover over an element
  BROWSER_ACTION: {"action": "hover", "selector": ".menu-item"}

select      Select option in a <select> dropdown
  BROWSER_ACTION: {"action": "select", "selector": "select#lang", "value": "en"}

js          Execute arbitrary JavaScript and return the result
  BROWSER_ACTION: {"action": "js", "script": "document.title"}

DONE        Signal task completion
  DONE: <concise summary of what was accomplished>
"""

ACTION_RE = re.compile(r'BROWSER_ACTION:\s*(\{.+?\})', re.DOTALL)
DONE_RE = re.compile(r'^DONE:\s*(.+)', re.MULTILINE | re.DOTALL)

MAX_PAGE_TEXT = 3000  # chars of page text fed to LLM each step
MAX_STEPS = 40


def _build_browser_system_prompt(task: str) -> str:
    return f"""You are AIO-NUI — the Autonomous Interaction & Observation Navigation Unit.
You control a real Chromium browser autonomously to complete tasks for the user.

CURRENT TASK:
{task}

You operate as a SLM-v3 AID-09 (Agentic Workflow Architect) subagent.
Every action you take is streamed live to the user who is watching you work.
Be methodical, efficient, and decisive. Do not ask for clarification.

{BROWSER_TOOLS_DOC}

OBSERVATION FORMAT (provided to you after each action):
---
URL: <current url>
TITLE: <page title>
PAGE_TEXT: <visible text excerpt>
LAST_ACTION_RESULT: <success/error from last action>
---

RULES:
- Output EXACTLY ONE BROWSER_ACTION per response, then wait for OBSERVATION.
- Always start with a goto action to navigate to the right page.  
- After extracting the information you need, output DONE with a summary.
- If something fails, try an alternative approach (different selector, JS, etc.).
- Be specific with selectors — prefer id/name/placeholder over generic tags.
- Keep going until the task is fully complete.
- Format DONE as: DONE: <what was accomplished, including any extracted data>
"""


# ── BrowserAgent ──────────────────────────────────────────────────────────────

class BrowserAgent:
    """
    Autonomous headed browser agent.

    Yields SSE-compatible event dicts:
      {"type": "frame", "step": N, "action": str, "png": base64, "url": str, "title": str}
      {"type": "log",   "step": N, "message": str}
      {"type": "done",  "summary": str}
      {"type": "error", "content": str}
    """

    def __init__(
        self,
        llm_caller: Callable[[list], str],
        headless: bool = False,
        viewport_width: int = 1280,
        viewport_height: int = 800,
        frame_quality: int = 75,
    ):
        self.llm_caller = llm_caller
        self.headless = headless
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        self.frame_quality = frame_quality

    def run(
        self,
        task: str,
        start_url: Optional[str] = None,
        abort_event: Optional[threading.Event] = None,
    ) -> Generator[dict, None, None]:
        """Run the browser agent and yield SSE event dicts."""
        _abort = abort_event or threading.Event()

        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
        except ImportError:
            yield {"type": "error", "content": "Playwright not installed. Run: pip install playwright && playwright install chromium"}
            return

        messages = [
            {"role": "system", "content": _build_browser_system_prompt(task)},
            {"role": "user", "content": f"Begin the task. Start by navigating to the appropriate page.\nTask: {task}"},
        ]

        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(
                    headless=self.headless,
                    args=["--no-sandbox", "--disable-setuid-sandbox"],
                )
                context = browser.new_context(
                    viewport={"width": self.viewport_width, "height": self.viewport_height},
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0",
                )
                page = context.new_page()
            except Exception as e:
                yield {"type": "error", "content": f"Failed to launch browser: {e}"}
                return

            # Navigate to start URL if provided
            if start_url:
                try:
                    page.goto(start_url, wait_until="domcontentloaded", timeout=15000)
                    yield {"type": "log", "step": 0, "message": f"Navigated to {start_url}"}
                    yield self._capture_frame(page, 0, f"goto {start_url}")
                except Exception as e:
                    yield {"type": "log", "step": 0, "message": f"Start URL failed: {e}"}

            last_result = "Ready. Browser is open."

            for step in range(1, MAX_STEPS + 1):
                if _abort.is_set():
                    yield {"type": "log", "step": step, "message": "⏹ Aborted by user"}
                    break

                # Build observation context
                try:
                    url = page.url
                    title = page.title()
                    body_text = page.evaluate("document.body?.innerText || ''")[:MAX_PAGE_TEXT]
                except Exception:
                    url = "(unknown)"
                    title = "(unknown)"
                    body_text = ""

                observation = (
                    f"---\n"
                    f"URL: {url}\n"
                    f"TITLE: {title}\n"
                    f"PAGE_TEXT:\n{body_text}\n"
                    f"LAST_ACTION_RESULT: {last_result}\n"
                    f"---"
                )

                messages.append({"role": "user", "content": observation})

                # LLM decides next action
                try:
                    response = self.llm_caller(messages)
                except Exception as e:
                    yield {"type": "error", "content": f"LLM error at step {step}: {e}"}
                    break

                messages.append({"role": "assistant", "content": response})

                # Check for DONE
                done_m = DONE_RE.search(response)
                if done_m:
                    summary = done_m.group(1).strip()
                    # Final screenshot
                    yield self._capture_frame(page, step, "DONE")
                    yield {"type": "log", "step": step, "message": f"✅ {summary}"}
                    yield {"type": "done", "summary": summary, "step": step}
                    browser.close()
                    return

                # Parse browser action
                action_m = ACTION_RE.search(response)
                if not action_m:
                    # Treat as clarifying text, continue
                    thinking = response.strip()[:200]
                    yield {"type": "log", "step": step, "message": f"💭 {thinking}"}
                    last_result = "(no action parsed — LLM is thinking)"
                    continue

                try:
                    action_data = json.loads(action_m.group(1))
                except json.JSONDecodeError as e:
                    yield {"type": "error", "content": f"Malformed action JSON at step {step}: {e}"}
                    last_result = f"ERROR: malformed JSON — {e}"
                    continue

                action_type = action_data.get("action", "")
                action_desc = _describe_action(action_data)
                yield {"type": "log", "step": step, "message": f"▶ {action_desc}"}

                # Execute the action
                last_result = self._execute_action(page, action_data, step)

                # Capture frame after action
                frame_ev = self._capture_frame(page, step, action_desc)
                yield frame_ev

                if last_result.startswith("ERROR"):
                    yield {"type": "log", "step": step, "message": f"⚠️ {last_result}"}

            else:
                yield {"type": "error", "content": f"Reached max steps ({MAX_STEPS})"}
                yield self._capture_frame(page, MAX_STEPS, "max steps reached")

            browser.close()

    # ── Action executor ───────────────────────────────────────────────────────

    def _execute_action(self, page, action_data: dict, step: int) -> str:
        from playwright.sync_api import TimeoutError as PWTimeout

        action = action_data.get("action", "")
        try:
            if action == "goto":
                url = action_data["url"]
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                return f"Navigated to {page.url}"

            elif action == "click":
                sel = action_data["selector"]
                page.click(sel, timeout=8000)
                page.wait_for_load_state("domcontentloaded", timeout=5000)
                return f"Clicked {sel}"

            elif action == "type":
                sel = action_data["selector"]
                text = action_data.get("text", "")
                page.fill(sel, text, timeout=8000)
                return f"Typed into {sel}"

            elif action == "scroll":
                direction = action_data.get("direction", "down")
                pixels = int(action_data.get("pixels", 500))
                dy = pixels if direction == "down" else -pixels
                page.evaluate(f"window.scrollBy(0, {dy})")
                return f"Scrolled {direction} {pixels}px"

            elif action == "wait":
                if "selector" in action_data:
                    sel = action_data["selector"]
                    timeout = int(action_data.get("timeout", 5000))
                    page.wait_for_selector(sel, timeout=timeout)
                    return f"Waited for {sel}"
                else:
                    secs = float(action_data.get("seconds", 1))
                    time.sleep(min(secs, 10))
                    return f"Waited {secs}s"

            elif action == "screenshot":
                return "Screenshot captured"

            elif action == "extract":
                sel = action_data.get("selector", "body")
                attr = action_data.get("attr", "innerText")
                if attr == "innerText":
                    text = page.locator(sel).first.inner_text(timeout=6000)
                else:
                    text = page.locator(sel).first.get_attribute(attr, timeout=6000) or ""
                return f"Extracted: {text[:500]}"

            elif action == "key":
                key = action_data.get("key", "Enter")
                page.keyboard.press(key)
                return f"Pressed {key}"

            elif action == "hover":
                sel = action_data["selector"]
                page.hover(sel, timeout=6000)
                return f"Hovered {sel}"

            elif action == "select":
                sel = action_data["selector"]
                val = action_data.get("value", "")
                page.select_option(sel, value=val, timeout=6000)
                return f"Selected {val} in {sel}"

            elif action == "js":
                script = action_data.get("script", "")
                result = page.evaluate(script)
                return f"JS result: {str(result)[:300]}"

            else:
                return f"ERROR: Unknown action '{action}'"

        except Exception as e:
            return f"ERROR: {type(e).__name__}: {e}"

    # ── Screenshot frame capture ──────────────────────────────────────────────

    def _capture_frame(self, page, step: int, action: str) -> dict:
        try:
            raw_bytes = page.screenshot(type="png", full_page=False)
            # Compress with Pillow if available, else send raw
            try:
                from PIL import Image
                img = Image.open(io.BytesIO(raw_bytes))
                # Resize to a reasonable streaming size
                img.thumbnail((1024, 680), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=self.frame_quality, optimize=True)
                compressed = buf.getvalue()
                png_b64 = base64.b64encode(compressed).decode()
                mime = "image/jpeg"
            except ImportError:
                png_b64 = base64.b64encode(raw_bytes).decode()
                mime = "image/png"

            try:
                url = page.url
                title = page.title()
            except Exception:
                url = ""
                title = ""

            return {
                "type": "frame",
                "step": step,
                "action": action,
                "png": png_b64,
                "mime": mime,
                "url": url,
                "title": title,
            }
        except Exception as e:
            return {
                "type": "log",
                "step": step,
                "message": f"Screenshot failed: {e}",
            }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _describe_action(action_data: dict) -> str:
    a = action_data.get("action", "?")
    if a == "goto":   return f"goto {action_data.get('url', '')}"
    if a == "click":  return f"click {action_data.get('selector', '')}"
    if a == "type":   return f"type '{action_data.get('text', '')}' into {action_data.get('selector', '')}"
    if a == "scroll": return f"scroll {action_data.get('direction', 'down')} {action_data.get('pixels', 500)}px"
    if a == "wait":   return f"wait {action_data.get('selector', action_data.get('seconds', '1s'))}"
    if a == "key":    return f"press {action_data.get('key', 'Enter')}"
    if a == "extract": return f"extract {action_data.get('attr', 'text')} from {action_data.get('selector', '')}"
    if a == "hover":  return f"hover {action_data.get('selector', '')}"
    if a == "select": return f"select '{action_data.get('value', '')}' in {action_data.get('selector', '')}"
    if a == "js":     return f"js: {action_data.get('script', '')[:60]}"
    return a

## v0.1.21 — Full Action Visibility, Dynamic Ollama Cloud, Browser Intelligence

### Agent Action Visibility (Claude Code & all agents)
- **Live step streaming** — agent work is now fully visible while running; the steps panel auto-collapses to a tidy summary ("12 steps · 3 files changed") when done
- **Tool call detail** — each tool call now shows the full args JSON in an expandable body instead of truncated summary-only text
- **Result panel** — tool results auto-open for short outputs, show char count for large ones
- **Expanded tool icons** — all Claude Code tools now have correct icons (Read, Write, Edit, Bash, Glob, Grep, WebFetch, WebSearch, Agent, Task, TodoWrite + git, search, web, data ops)
- **Smart arg previews** — renderArgs recognises all common tool signatures for meaningful one-line previews

### Ollama Cloud — All Models Available
- Model selector now dynamically queries the live Ollama Cloud API instead of hardcoding 4 models
- Graceful fallback to a comprehensive 15+ model list if the API is unreachable
- Consistent with how all other providers fetch their model lists

### AI Browser — Session Continuation & Intelligence
- **Session continuity** — prior session summary is carried forward across browser runs; agent knows what was already accomplished and builds on it instead of starting over
- **Continuation UI** — dismissable "↺ Continuing session" banner; launch button becomes "↺ Continue Session" when context is active
- **Upgraded system prompt** — 10 strategic rules: plan-first, resilient selectors, obstacle/cookie/modal handling (dismiss_dialog), extract-before-DONE, no hallucination
- **Larger page awareness** — MAX_PAGE_TEXT raised 3000 → 8000 characters
- **New browser actions** — `back`, `extract_all`, `focus`, `dismiss_dialog`

### team_plan_extend Event
- Late-joining matrix agents now render with agent badges instead of being silently dropped

### Previous (v0.1.20)
- Phase Launcher with run-all, live progress bar, per-phase status tracking
- Automations inline browser configurator + search + /auto slash command
- Auto-MCPilot Anthropic/Claude and OpenAI provider support

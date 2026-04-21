## v0.1.20 — Phase Launcher, Automation Configurator & Multi-Provider AutoPilot

### Phase Launcher
- **Per-phase status tracking** — each phase card shows a live amber spinner while running and a green checkmark when complete
- **Run All Phases Sequentially** — one-click button executes all 6 SLM-v3 phases in order with a live progress bar; cancel mid-run at any time
- **Panel drag-resize** — Phase Launcher now supports drag-to-resize like all other panels
- **`/phase all` slash command** — trigger the full phase sequence from the chat input

### Automations Panel
- **Inline browser task configurator** — browser automations expand in-place so you fill in your topic, URL, or target before launching instead of getting a raw template
- **Search** — filter all 20+ automations by name or description in real time
- **`/auto <name>` slash command** — launch any automation by name prefix directly from the chat input

### Auto-MCPilot
- **Anthropic/Claude provider** — set `AI_PROVIDER=anthropic` (uses `claude-haiku-4-5-20251001` by default, override with `ANTHROPIC_MODEL`)
- **OpenAI provider** — set `AI_PROVIDER=openai` (uses `gpt-4o-mini` by default, override with `OPENAI_MODEL`)

### Previous (v0.1.19)
- Swarm Team Mode — `team_mode` flag enables multi-agent coordination
- `edit_file` tool — patch files in-place with exact string replacement
- Rich automation task templates across all 20+ automations
- Auto code-file extraction from fenced code blocks
- OpenClaw / Gemini CLI binary support

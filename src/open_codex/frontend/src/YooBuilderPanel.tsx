import { useState, useRef, useEffect, useCallback } from 'react'
import type { KeyboardEvent } from 'react'

// ─── Config save helper ───────────────────────────────────────────────────────

async function saveYooConfig(cfg: Record<string, string>): Promise<void> {
  await fetch('/api/mcp/servers/yootheme/config', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config: cfg }),
  })
}

// ─── Types ────────────────────────────────────────────────────────────────────

interface YooStats {
  section: number
  row: number
  column: number
  element: number
  total: number
  depth: number
  snapshots: number
}

interface ArticleInfo {
  id: number
  title: string
  hasLayout: boolean
}

interface YooBuilderPanelProps {
  onClose: () => void
}

// ─── Preset Palette config ────────────────────────────────────────────────────

const SECTION_PRESETS = [
  { type: 'hero',         icon: '🦸', label: 'Hero' },
  { type: 'features',     icon: '✦',  label: 'Features' },
  { type: 'cta',          icon: '🎯', label: 'CTA' },
  { type: 'testimonials', icon: '💬', label: 'Testimonials' },
  { type: 'pricing',      icon: '💎', label: 'Pricing' },
  { type: 'gallery',      icon: '🖼',  label: 'Gallery' },
  { type: 'contact',      icon: '📬', label: 'Contact' },
  { type: 'about',        icon: '📖', label: 'About' },
  { type: 'faq',          icon: '❓', label: 'FAQ' },
  { type: 'video',        icon: '▶',  label: 'Video' },
] as const

const AI_PROVIDERS = ['gemini', 'ollama', 'ollama_cloud', 'lmstudio'] as const

// ─── API helpers ──────────────────────────────────────────────────────────────

async function yooCall(tool: string, params: Record<string, unknown>): Promise<string> {
  const res = await fetch('/api/mcp/call', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ server: 'yootheme', tool, params }),
  })
  const data = await res.json()
  if (data.error) return `Error: ${data.error}`
  return String(data.result ?? '')
}

async function fetchArticles(): Promise<ArticleInfo[]> {
  try {
    const res = await fetch('/api/mcp/call', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        server: 'yootheme',
        tool: 'yoo_list_articles_with_layouts',
        params: { limit: 50 },
      }),
    })
    const data = await res.json()
    const text: string = data.result ?? ''
    // Parse the text table format
    const lines = text.split('\n').slice(1) // skip header
    return lines
      .filter(l => l.trim() && l.includes(']'))
      .map(l => {
        const m = l.match(/\[\s*(\d+)\]\s+(✅|  )\s+(.+)/)
        if (!m) return null
        return { id: Number(m[1]), title: m[3].trim(), hasLayout: m[2].trim() === '✅' }
      })
      .filter(Boolean) as ArticleInfo[]
  } catch {
    return []
  }
}

// ─── Main Panel ───────────────────────────────────────────────────────────────

export function YooBuilderPanel({ onClose }: YooBuilderPanelProps) {
  const [tab, setTab] = useState<'build' | 'layout' | 'json' | 'config'>('build')

  // NL command bar
  const [nlInput, setNlInput] = useState('')
  const [aiProvider, setAiProvider] = useState<string>('gemini')
  const [sessionId, setSessionId] = useState('default')
  const [running, setRunning] = useState(false)
  const [log, setLog] = useState<string[]>([])

  // Layout state
  const [stats, setStats] = useState<YooStats | null>(null)
  const [layoutJson, setLayoutJson] = useState('')

  // Article selector
  const [articles, setArticles] = useState<ArticleInfo[]>([])
  const [selectedArticleId, setSelectedArticleId] = useState<number | null>(null)
  const [artLoading, setArtLoading] = useState(false)

  // Section editor
  const [sectionDesc, setSectionDesc] = useState('')

  // Config state
  const [cfg, setCfg] = useState({
    AI_PROVIDER: 'gemini',
    JOOMLA_BASE_URL: '', BEARER_TOKEN: '',
    OLLAMA_HOST: 'http://localhost:11434', OLLAMA_MODEL: 'llama3',
    OLLAMA_CLOUD_API_KEY: '', OLLAMA_CLOUD_MODEL: 'gpt-oss:120b',
    LMSTUDIO_HOST: 'http://localhost:1234', LMSTUDIO_MODEL: 'local-model',
    GEMINI_API_KEY: '', GEMINI_MODEL: 'gemini-2.0-flash',
    YOOMYSQL_HOST: '', YOOMYSQL_PORT: '3306', YOOMYSQL_USER: '',
    YOOMYSQL_PASSWORD: '', YOOMYSQL_DATABASE: '', YOOMYSQL_PREFIX: 'jos_',
  })
  const [cfgSaving, setCfgSaving] = useState(false)
  const [cfgSaved, setCfgSaved] = useState(false)

  const logRef = useRef<HTMLDivElement>(null)

  const addLog = useCallback((msg: string) => {
    setLog(prev => [...prev.slice(-200), msg])
  }, [])

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [log])

  // Load articles list on mount
  useEffect(() => {
    fetchArticles().then(setArticles)
  }, [])

  // Refresh stats from session
  const refreshStats = useCallback(async () => {
    const result = await yooCall('yoo_get_stats', { session_id: sessionId })
    const m = {
      section: /Sections\s*:\s*(\d+)/i.exec(result)?.[1] ?? '0',
      row: /Rows\s*:\s*(\d+)/i.exec(result)?.[1] ?? '0',
      column: /Columns\s*:\s*(\d+)/i.exec(result)?.[1] ?? '0',
      element: /Elements\s*:\s*(\d+)/i.exec(result)?.[1] ?? '0',
      total: /Total\s*:\s*(\d+)/i.exec(result)?.[1] ?? '0',
      depth: /Depth\s*:\s*(\d+)/i.exec(result)?.[1] ?? '0',
      snapshots: /Snapshots\s*:\s*(\d+)/i.exec(result)?.[1] ?? '0',
    }
    setStats({
      section: +m.section, row: +m.row, column: +m.column,
      element: +m.element, total: +m.total, depth: +m.depth, snapshots: +m.snapshots,
    })
  }, [sessionId])

  const refreshJson = useCallback(async () => {
    const result = await yooCall('yoo_get_layout_json', { session_id: sessionId })
    // Extract the JSON portion after the stats line
    const jsonStart = result.indexOf('{')
    if (jsonStart !== -1) setLayoutJson(result.slice(jsonStart))
  }, [sessionId])

  // ── NL command dispatch ──────────────────────────────────────────────────────

  const runNlCommand = useCallback(async () => {
    if (!nlInput.trim() || running) return
    setRunning(true)
    addLog(`▶ ${nlInput}`)
    try {
      const result = await yooCall('yoo_generate_page', {
        request: nlInput,
        ai_service: aiProvider,
        session_id: sessionId,
      })
      addLog(result)
      await refreshStats()
    } catch (e) {
      addLog(`Error: ${e}`)
    } finally {
      setRunning(false)
      setNlInput('')
    }
  }, [nlInput, running, aiProvider, sessionId, addLog, refreshStats])

  const onNlKeyDown = useCallback((e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void runNlCommand() }
  }, [runNlCommand])

  // ── Section palette ──────────────────────────────────────────────────────────

  const addPresetSection = useCallback(async (sectionType: string) => {
    if (running) return
    setRunning(true)
    addLog(`▶ Adding ${sectionType} section…`)
    try {
      const result = await yooCall('yoo_add_section', {
        section_type: sectionType,
        description: sectionDesc || undefined,
        ai_service: aiProvider,
        session_id: sessionId,
      })
      addLog(result)
      await refreshStats()
    } finally {
      setRunning(false)
    }
  }, [running, sectionDesc, aiProvider, sessionId, addLog, refreshStats])

  // ── Undo/Redo ─────────────────────────────────────────────────────────────────

  const doUndo = useCallback(async () => {
    const r = await yooCall('yoo_undo', { session_id: sessionId })
    addLog(r); await refreshStats()
  }, [sessionId, addLog, refreshStats])

  const doRedo = useCallback(async () => {
    const r = await yooCall('yoo_redo', { session_id: sessionId })
    addLog(r); await refreshStats()
  }, [sessionId, addLog, refreshStats])

  // ── Article load / save ───────────────────────────────────────────────────────

  const loadFromArticle = useCallback(async () => {
    if (!selectedArticleId) return
    setArtLoading(true)
    addLog(`▶ Loading layout from article ${selectedArticleId}…`)
    const r = await yooCall('yoo_read_layout_from_article', {
      article_id: selectedArticleId,
      session_id: sessionId,
    })
    addLog(r); await refreshStats()
    setArtLoading(false)
  }, [selectedArticleId, sessionId, addLog, refreshStats])

  const saveToArticle = useCallback(async () => {
    if (!selectedArticleId) return
    setArtLoading(true)
    addLog(`▶ Saving layout to article ${selectedArticleId}…`)
    const r = await yooCall('yoo_set_layout', {
      article_id: selectedArticleId,
      session_id: sessionId,
    })
    addLog(r)
    setArtLoading(false)
  }, [selectedArticleId, sessionId, addLog])

  const removeSection = useCallback(async (idx: number) => {
    const r = await yooCall('yoo_remove_section', { index: idx, session_id: sessionId })
    addLog(r); await refreshStats()
  }, [sessionId, addLog, refreshStats])

  const saveCfg = useCallback(async () => {
    setCfgSaving(true)
    try {
      await saveYooConfig(cfg)
      setCfgSaved(true)
      setTimeout(() => setCfgSaved(false), 2500)
    } finally {
      setCfgSaving(false)
    }
  }, [cfg])

  // ─────────────────────────────────────────────────────────────────────────────

  return (
    <aside className="slm-panel yoo-panel">
      <div className="slm-panel-header">
        <div className="slm-panel-title">
          <span className="slm-panel-icon">🏗</span>
          YOO Builder
          {stats && <span className="yoo-stat-pill">{stats.section}sec / {stats.element}el</span>}
        </div>
        <button id="btn-close-yoo" className="panel-close" onClick={onClose}>✕</button>
      </div>

      {/* ── Tab bar ── */}
      <div className="yoo-tabs">
        {(['build', 'layout', 'json', 'config'] as const).map(t => (
          <button key={t} className={`yoo-tab ${tab === t ? 'active' : ''}`}
            onClick={() => {
              setTab(t)
              if (t === 'json') void refreshJson()
              if (t === 'layout') void refreshStats()
            }}>
            {t === 'build' ? '⚡ Build' : t === 'layout' ? '📐 Layout' : t === 'json' ? '{ } JSON' : '⚙ Config'}
          </button>
        ))}
      </div>

      <div className="yoo-body">

        {/* ══════ BUILD TAB ══════ */}
        {tab === 'build' && (
          <div className="yoo-build">

            {/* Session + Provider row */}
            <div className="yoo-row">
              <div className="yoo-field">
                <label className="yoo-label">Session</label>
                <input className="yoo-input" value={sessionId}
                  onChange={e => setSessionId(e.target.value)}
                  placeholder="default" />
              </div>
              <div className="yoo-field">
                <label className="yoo-label">AI Provider</label>
                <select className="yoo-select" value={aiProvider}
                  onChange={e => setAiProvider(e.target.value)}>
                  {AI_PROVIDERS.map(p => (
                    <option key={p} value={p}>{p}</option>
                  ))}
                </select>
              </div>
            </div>

            {/* NL command bar */}
            <div className="yoo-nl-bar">
              <textarea
                id="yoo-nl-input"
                className="yoo-nl-input"
                value={nlInput}
                onChange={e => setNlInput(e.target.value)}
                onKeyDown={onNlKeyDown}
                placeholder="Describe the page you want to build…&#10;e.g. 'Landing page for a plumbing company with hero, 3 features, and contact'"
                rows={3}
                disabled={running}
              />
              <button id="btn-yoo-generate" className="yoo-generate-btn"
                disabled={running || !nlInput.trim()} onClick={runNlCommand}>
                {running ? '⟳' : '⚡'} Generate
              </button>
            </div>

            {/* Section Palette */}
            <div className="yoo-palette-header">
              <span>Section Palette</span>
              <input className="yoo-input yoo-palette-desc" value={sectionDesc}
                onChange={e => setSectionDesc(e.target.value)}
                placeholder="Optional custom description for section…" />
            </div>
            <div className="yoo-palette">
              {SECTION_PRESETS.map(({ type, icon, label }) => (
                <button key={type} id={`btn-yoo-preset-${type}`}
                  className="yoo-preset-btn" disabled={running}
                  onClick={() => void addPresetSection(type)}>
                  <span className="yoo-preset-icon">{icon}</span>
                  <span className="yoo-preset-label">{label}</span>
                </button>
              ))}
            </div>

            {/* Article picker */}
            <div className="yoo-article-row">
              <div className="yoo-field yoo-field-grow">
                <label className="yoo-label">Article</label>
                <select className="yoo-select" value={selectedArticleId ?? ''}
                  onChange={e => setSelectedArticleId(e.target.value ? +e.target.value : null)}>
                  <option value="">— select article —</option>
                  {articles.map(a => (
                    <option key={a.id} value={a.id}>
                      [{a.id}] {a.hasLayout ? '✅ ' : ''}{a.title}
                    </option>
                  ))}
                </select>
              </div>
              <button id="btn-yoo-load" className="yoo-action-btn"
                disabled={!selectedArticleId || artLoading} onClick={loadFromArticle}>
                📥 Load
              </button>
              <button id="btn-yoo-save" className="yoo-action-btn yoo-save-btn"
                disabled={!selectedArticleId || artLoading || (stats?.total ?? 0) === 0}
                onClick={saveToArticle}>
                💾 Save
              </button>
              <button id="btn-yoo-refresh-arts" className="yoo-action-btn"
                onClick={() => void fetchArticles().then(setArticles)}>
                ↺
              </button>
            </div>

            {/* Quick action row */}
            <div className="yoo-quick-row">
              <button id="btn-yoo-undo" className="yoo-quick-btn" onClick={doUndo}
                disabled={(stats?.snapshots ?? 0) === 0}>↩ Undo</button>
              <button id="btn-yoo-redo" className="yoo-quick-btn" onClick={doRedo}>↪ Redo</button>
              <button id="btn-yoo-validate" className="yoo-quick-btn"
                disabled={(stats?.total ?? 0) === 0}
                onClick={async () => {
                  const r = await yooCall('yoo_validate_layout', { session_id: sessionId })
                  addLog(r)
                }}>✓ Validate</button>
              <button id="btn-yoo-clear" className="yoo-quick-btn yoo-clear-btn"
                onClick={async () => {
                  const r = await yooCall('yoo_load_layout', {
                    layout_json: '{"type":"layout","version":"4.5.33","name":"Empty","children":[]}',
                    session_id: sessionId,
                  })
                  addLog(r); await refreshStats()
                }}>⊘ Clear</button>
            </div>

            {/* Agent log */}
            <div ref={logRef} className="yoo-log">
              {log.length === 0
                ? <span className="yoo-log-empty">Agent output will appear here…</span>
                : log.map((l, i) => (
                  <div key={i} className={`yoo-log-line ${l.startsWith('▶') ? 'yoo-log-cmd' : l.startsWith('Error') ? 'yoo-log-err' : ''}`}>
                    {l}
                  </div>
                ))
              }
            </div>
          </div>
        )}

        {/* ══════ LAYOUT TAB ══════ */}
        {tab === 'layout' && (
          <div className="yoo-layout-view">
            {stats && (
              <div className="yoo-stats-grid">
                {([['Sections', stats.section], ['Rows', stats.row], ['Columns', stats.column],
                  ['Elements', stats.element], ['Depth', stats.depth], ['Snapshots', stats.snapshots]] as [string, number][])
                  .map(([label, val]) => (
                    <div key={label} className="yoo-stat-card">
                      <div className="yoo-stat-val">{val}</div>
                      <div className="yoo-stat-lbl">{label}</div>
                    </div>
                  ))}
              </div>
            )}
            <button id="btn-yoo-refresh-stats" className="yoo-action-btn" style={{ marginBottom: '12px' }}
              onClick={refreshStats}>↺ Refresh</button>

            {/* Section list with remove buttons */}
            {layoutJson && (() => {
              try {
                const layout = JSON.parse(layoutJson)
                const sections = layout?.children ?? []
                if (sections.length === 0) return (
                  <div className="yoo-empty-state">No sections yet. Use the Build tab to generate.</div>
                )
                return (
                  <div className="yoo-section-list">
                    {sections.map((sec: Record<string, unknown>, i: number) => {
                      const props = (sec.props ?? {}) as Record<string, unknown>
                      const name = String(props.name ?? `Section ${i + 1}`)
                      const style = String(props.style ?? 'default')
                      const rows = (sec.children as unknown[]) ?? []
                      const elementCount = rows.reduce((a: number, row) => {
                        const r = row as Record<string, unknown>
                        const cols = (r.children as unknown[]) ?? []
                        return a + cols.reduce((b: number, col) => {
                          const c = col as Record<string, unknown>
                          return b + ((c.children as unknown[]) ?? []).length
                        }, 0)
                      }, 0)
                      return (
                        <div key={i} className="yoo-section-row">
                          <div className="yoo-section-info">
                            <span className="yoo-section-badge">{i}</span>
                            <span className="yoo-section-name">{name}</span>
                            <span className={`yoo-section-style yoo-style-${style}`}>{style}</span>
                            <span className="yoo-section-meta">{rows.length} row{rows.length !== 1 ? 's' : ''} · {elementCount} el</span>
                          </div>
                          <div className="yoo-section-actions">
                            <button className="yoo-section-btn" title="Move up"
                              disabled={i === 0}
                              onClick={() => void yooCall('yoo_move_section', { from_index: i, to_index: i - 1, session_id: sessionId }).then(() => refreshStats()).then(refreshJson)}>
                              ↑
                            </button>
                            <button className="yoo-section-btn" title="Move down"
                              disabled={i === sections.length - 1}
                              onClick={() => void yooCall('yoo_move_section', { from_index: i, to_index: i + 1, session_id: sessionId }).then(() => refreshStats()).then(refreshJson)}>
                              ↓
                            </button>
                            <button className="yoo-section-btn yoo-section-del" title="Remove"
                              onClick={() => { void removeSection(i); void refreshJson() }}>
                              ✕
                            </button>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )
              } catch { return <div className="yoo-empty-state">Load a layout to see section tree.</div> }
            })()}
          </div>
        )}

        {/* ══════ JSON TAB ══════ */}
        {tab === 'json' && (
          <div className="yoo-json-view">
            <div className="yoo-json-toolbar">
              <button id="btn-yoo-refresh-json" className="yoo-action-btn" onClick={refreshJson}>↺ Refresh</button>
              <button id="btn-yoo-copy-json" className="yoo-action-btn"
                disabled={!layoutJson}
                onClick={() => navigator.clipboard.writeText(layoutJson)}>⎘ Copy</button>
              <span className="yoo-json-size">{layoutJson ? `${(layoutJson.length / 1024).toFixed(1)} KB` : '—'}</span>
            </div>
            <pre className="yoo-json-pre">
              {layoutJson || '// Generate a layout or load from an article to see the JSON'}
            </pre>
          </div>
        )}

        {/* ══════ CONFIG TAB ══════ */}
        {tab === 'config' && (
          <div className="yoo-cfg-view">

            {/* Joomla */}
            <div className="yoo-cfg-section">
              <div className="yoo-cfg-section-title">🌐 Joomla Connection</div>
              <div className="yoo-cfg-field">
                <label className="yoo-label">Site URL</label>
                <input className="yoo-input" placeholder="https://yoursite.com"
                  value={cfg.JOOMLA_BASE_URL}
                  onChange={e => setCfg(c => ({ ...c, JOOMLA_BASE_URL: e.target.value }))} />
              </div>
              <div className="yoo-cfg-field">
                <label className="yoo-label">Bearer Token</label>
                <input className="yoo-input" type="password" placeholder="From Joomla Admin → Users → API Token"
                  value={cfg.BEARER_TOKEN}
                  onChange={e => setCfg(c => ({ ...c, BEARER_TOKEN: e.target.value }))} />
              </div>
            </div>

            {/* AI Provider */}
            <div className="yoo-cfg-section">
              <div className="yoo-cfg-section-title">🤖 AI Provider</div>
              <div className="yoo-row">
                <div className="yoo-field">
                  <label className="yoo-label">Default Provider</label>
                  <select className="yoo-select" value={cfg.AI_PROVIDER}
                    onChange={e => setCfg(c => ({ ...c, AI_PROVIDER: e.target.value }))}>
                    {['ollama', 'ollama_cloud', 'lmstudio', 'gemini', 'huggingface'].map(p => (
                      <option key={p} value={p}>{p}</option>
                    ))}
                  </select>
                </div>
              </div>

              {(cfg.AI_PROVIDER === 'ollama') && <>
                <div className="yoo-row">
                  <div className="yoo-field yoo-field-grow">
                    <label className="yoo-label">Ollama Host</label>
                    <input className="yoo-input" value={cfg.OLLAMA_HOST}
                      onChange={e => setCfg(c => ({ ...c, OLLAMA_HOST: e.target.value }))} />
                  </div>
                  <div className="yoo-field">
                    <label className="yoo-label">Model</label>
                    <input className="yoo-input" value={cfg.OLLAMA_MODEL}
                      onChange={e => setCfg(c => ({ ...c, OLLAMA_MODEL: e.target.value }))} />
                  </div>
                </div>
              </>}

              {(cfg.AI_PROVIDER === 'ollama_cloud') && <>
                <div className="yoo-row">
                  <div className="yoo-field yoo-field-grow">
                    <label className="yoo-label">Cloud API Key <span className="yoo-cfg-hint">ollama.com/settings/keys</span></label>
                    <input className="yoo-input" type="password" value={cfg.OLLAMA_CLOUD_API_KEY}
                      onChange={e => setCfg(c => ({ ...c, OLLAMA_CLOUD_API_KEY: e.target.value }))} />
                  </div>
                  <div className="yoo-field">
                    <label className="yoo-label">Model</label>
                    <input className="yoo-input" value={cfg.OLLAMA_CLOUD_MODEL}
                      onChange={e => setCfg(c => ({ ...c, OLLAMA_CLOUD_MODEL: e.target.value }))} />
                  </div>
                </div>
              </>}

              {(cfg.AI_PROVIDER === 'lmstudio') && <>
                <div className="yoo-row">
                  <div className="yoo-field yoo-field-grow">
                    <label className="yoo-label">LM Studio Host</label>
                    <input className="yoo-input" value={cfg.LMSTUDIO_HOST}
                      onChange={e => setCfg(c => ({ ...c, LMSTUDIO_HOST: e.target.value }))} />
                  </div>
                  <div className="yoo-field">
                    <label className="yoo-label">Model</label>
                    <input className="yoo-input" value={cfg.LMSTUDIO_MODEL}
                      onChange={e => setCfg(c => ({ ...c, LMSTUDIO_MODEL: e.target.value }))} />
                  </div>
                </div>
              </>}

              {(cfg.AI_PROVIDER === 'gemini') && <>
                <div className="yoo-row">
                  <div className="yoo-field yoo-field-grow">
                    <label className="yoo-label">Gemini API Key</label>
                    <input className="yoo-input" type="password" value={cfg.GEMINI_API_KEY}
                      onChange={e => setCfg(c => ({ ...c, GEMINI_API_KEY: e.target.value }))} />
                  </div>
                  <div className="yoo-field">
                    <label className="yoo-label">Model</label>
                    <input className="yoo-input" value={cfg.GEMINI_MODEL}
                      onChange={e => setCfg(c => ({ ...c, GEMINI_MODEL: e.target.value }))} />
                  </div>
                </div>
              </>}
            </div>

            {/* MySQL Direct */}
            <div className="yoo-cfg-section">
              <div className="yoo-cfg-section-title">🗄 MySQL Direct <span className="yoo-cfg-badge">optional</span></div>
              <div className="yoo-cfg-hint-block">Enables direct layout injection into <code>#__content</code> — fastest method, bypasses REST.</div>
              <div className="yoo-row">
                <div className="yoo-field yoo-field-grow">
                  <label className="yoo-label">Host</label>
                  <input className="yoo-input" placeholder="localhost" value={cfg.YOOMYSQL_HOST}
                    onChange={e => setCfg(c => ({ ...c, YOOMYSQL_HOST: e.target.value }))} />
                </div>
                <div className="yoo-field" style={{ flex: '0 0 70px' }}>
                  <label className="yoo-label">Port</label>
                  <input className="yoo-input" value={cfg.YOOMYSQL_PORT}
                    onChange={e => setCfg(c => ({ ...c, YOOMYSQL_PORT: e.target.value }))} />
                </div>
              </div>
              <div className="yoo-row">
                <div className="yoo-field">
                  <label className="yoo-label">User</label>
                  <input className="yoo-input" value={cfg.YOOMYSQL_USER}
                    onChange={e => setCfg(c => ({ ...c, YOOMYSQL_USER: e.target.value }))} />
                </div>
                <div className="yoo-field">
                  <label className="yoo-label">Password</label>
                  <input className="yoo-input" type="password" value={cfg.YOOMYSQL_PASSWORD}
                    onChange={e => setCfg(c => ({ ...c, YOOMYSQL_PASSWORD: e.target.value }))} />
                </div>
              </div>
              <div className="yoo-row">
                <div className="yoo-field yoo-field-grow">
                  <label className="yoo-label">Database</label>
                  <input className="yoo-input" value={cfg.YOOMYSQL_DATABASE}
                    onChange={e => setCfg(c => ({ ...c, YOOMYSQL_DATABASE: e.target.value }))} />
                </div>
                <div className="yoo-field" style={{ flex: '0 0 90px' }}>
                  <label className="yoo-label">Table Prefix</label>
                  <input className="yoo-input" value={cfg.YOOMYSQL_PREFIX}
                    onChange={e => setCfg(c => ({ ...c, YOOMYSQL_PREFIX: e.target.value }))} />
                </div>
              </div>
            </div>

            <button id="btn-yoo-save-cfg" className="yoo-cfg-save-btn"
              disabled={cfgSaving} onClick={saveCfg}>
              {cfgSaving ? '…' : cfgSaved ? '✓ Saved' : '💾 Save Configuration'}
            </button>
          </div>
        )}
      </div>
    </aside>
  )
}

import { useState, useEffect, useRef, useCallback } from 'react'
import type { KeyboardEvent, ChangeEvent } from 'react'
import './App.css'
import { YooBuilderPanel } from './YooBuilderPanel'

// ── Types ─────────────────────────────────────────────────────────────────────

interface FileNode {
  name: string
  path: string
  type: 'file' | 'directory'
  children?: FileNode[]
}

type AgentType = 'lmstudio' | 'ollama' | 'ollama_cloud' | 'gemini'
  | 'claude_code' | 'gemini_cli' | 'codex' | 'openclaw'
type Mode = 'local' | 'worktree' | 'cloud'
type Panel = 'matrix' | 'phases' | 'health' | 'automations' | 'browser' | 'mcp' | 'yoo' | null

interface MCPToolParam {
  type: string
  description?: string
  required?: boolean
}

interface MCPToolDef {
  name: string
  description: string
  parameters: Record<string, MCPToolParam>
}

interface MCPServerInfo {
  id: string
  name: string
  category: string
  icon: string
  description: string
  healthy: boolean
  tool_count: number
  tools: MCPToolDef[]
  config_keys: string[]
  config_set: Record<string, boolean>
}

interface MCPCallResult {
  result: string | null
  error: string | null
  tool: string
  server: string
}

interface Automation {
  id: string
  name: string
  category: string
  icon: string
  description: string
  browser: boolean
  default_url?: string
  task_template?: string
}

interface BrowserEvent {
  type: 'session_id' | 'frame' | 'log' | 'done' | 'error'
  session_id?: string
  step?: number
  action?: string
  png?: string
  mime?: string
  url?: string
  title?: string
  message?: string
  summary?: string
  content?: string
}

interface Project {
  id: string
  path: string
  name: string
  git: boolean
}

interface AgentEvent {
  type: 'start' | 'thinking' | 'thinking_text' | 'tool_call' | 'tool_result'
       | 'file_changed' | 'message' | 'done' | 'error' | 'stream_id' | 'aborted'
  content?: string
  tool?: string
  args?: Record<string, unknown>
  result?: string
  path?: string
  stats?: { files_changed: string[]; added?: number; removed?: number }
  prompt?: string
  stream_id?: string
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  events: AgentEvent[]
  done: boolean
  stats?: AgentEvent['stats']
  ts: number
  slmRole?: string
}

interface Thread {
  id: string
  title: string
  messages: Message[]
  ts: number
  stats?: { added: number; removed: number }
}

interface GitStatus {
  is_repo: boolean
  branch: string | null
  files: { status: string; path: string }[]
}

interface SLMAgent {
  coord: string
  cluster: string
  name: string
  keyword: string
  brilliance: string
}

interface SLMPhase {
  id: string
  name: string
  description: string
  chain: string[]
  prompt: string
  phase_num: number
}

interface ProviderHealth {
  ok: boolean
  hint?: string
  models?: string[]
}

interface TerminalAgentInfo {
  id: string
  label: string
  icon: string
  description: string
  auth_hint: string
  available: boolean
  authenticated: boolean
  version: string | null
  path: string | null
}

// ── Constants ─────────────────────────────────────────────────────────────────

const TERMINAL_AGENT_IDS: AgentType[] = ['claude_code', 'gemini_cli', 'codex', 'openclaw']

const AGENT_LABELS: Record<AgentType, string> = {
  lmstudio: 'LM Studio',
  ollama: 'Ollama',
  ollama_cloud: 'Ollama Cloud',
  gemini: 'Gemini',
  claude_code: 'Claude Code',
  gemini_cli: 'Gemini CLI',
  codex: 'Codex',
  openclaw: 'OpenClaw',
}

const SUGGESTIONS = [
  { icon: '🔧', label: 'Fix bugs in my code' },
  { icon: '✨', label: 'Add a new feature' },
  { icon: '📝', label: 'Write tests for this project' },
  { icon: '📖', label: 'Explain how this codebase works' },
  { icon: '🔄', label: 'Refactor for better readability' },
  { icon: '🚀', label: 'Optimize performance' },
  { icon: '🛡️', label: 'Security audit this project' },
  { icon: '🏗️', label: 'Review architecture patterns' },
]

/** Per-cluster accent hue */
const CLUSTER_HUE: Record<string, number> = {
  'Architecture Core': 262,
  'Language Excellence': 195,
  'Cloud & Platform': 210,
  'Operations & Reliability': 160,
  'AI & Data Systems': 285,
  'Quality, Security & Performance': 0,
  'Business & Finance': 38,
  'Revenue & Sales': 22,
  'Modernization & Legacy': 170,
  'Engineering Systems': 245,
  'Data Intelligence': 200,
  'Reliability Engineering': 142,
  'Growth & Lifecycle': 330,
  'Governance & Risk': 52,
  'Product Strategy': 300,
  'Experience Design': 320,
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6)

function store<T>(key: string, fallback: T): T {
  try { const v = localStorage.getItem(key); return v !== null ? JSON.parse(v) : fallback }
  catch { return fallback }
}

function storeSet(key: string, v: unknown) {
  try { localStorage.setItem(key, JSON.stringify(v)) } catch { /* */ }
}

function timeAgo(ts: number) {
  const d = Date.now() - ts
  if (d < 60_000) return 'just now'
  if (d < 3_600_000) return `${Math.floor(d / 60_000)}m ago`
  if (d < 86_400_000) return `${Math.floor(d / 3_600_000)}h ago`
  return `${Math.floor(d / 86_400_000)}d ago`
}

function clusterColor(cluster: string, alpha = 1) {
  const h = CLUSTER_HUE[cluster] ?? 262
  return `hsla(${h}, 70%, 65%, ${alpha})`
}

function clusterBg(cluster: string) {
  const h = CLUSTER_HUE[cluster] ?? 262
  return `hsla(${h}, 60%, 50%, 0.08)`
}

function clusterBorder(cluster: string) {
  const h = CLUSTER_HUE[cluster] ?? 262
  return `hsla(${h}, 60%, 55%, 0.2)`
}

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  // Projects
  const [projects, setProjects] = useState<Project[]>([])
  const [activeProject, setActiveProject] = useState<Project | null>(null)

  // Threads
  const [threads, setThreads] = useState<Thread[]>([])
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null)

  // Settings
  const [agentType, setAgentType] = useState<AgentType>(() => {
    const saved = store<string>('oc_agent', 'ollama')
    // Migrate legacy 'phi' selection to 'ollama'
    return (saved === 'phi' ? 'ollama' : saved) as AgentType
  })
  const [version, setVersion] = useState('0.1.18')
  const [model, setModel] = useState<string>(() => store('oc_model', ''))
  const [models, setModels] = useState<string[]>([])
  const [modelsLoading, setModelsLoading] = useState(false)
  const [apiKey, setApiKey] = useState(() => store('oc_apikey', ''))
  const [geminiApiKey, setGeminiApiKey] = useState(() => store('oc_geminikey', ''))
  const [lmHost, setLmHost] = useState(() => store('oc_lmhost', 'http://localhost:1234'))
  const [ollamaHost, setOllamaHost] = useState(() => store('oc_ollamahost', 'http://localhost:11434'))
  const [mode, setMode] = useState<Mode>('local')

  // Chat UI
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [activeStreamId, setActiveStreamId] = useState<string | null>(null)
  const [showSettings, setShowSettings] = useState(false)
  const [addProjectInput, setAddProjectInput] = useState('')
  const [showAddProject, setShowAddProject] = useState(false)

  // Active panel
  const [activePanel, setActivePanel] = useState<Panel>(null)

  // Automations
  const [automations, setAutomations] = useState<Automation[]>([])
  const [automationTaskInput, setAutomationTaskInput] = useState('')
  const [automationUrlInput, setAutomationUrlInput] = useState('')
  const [selectedAutomation, setSelectedAutomation] = useState<Automation | null>(null)
  const [automationCategory, setAutomationCategory] = useState<string>('All')

  // Browser viewer (AIO-NUI)
  const [browserSessionId, setBrowserSessionId] = useState<string | null>(null)
  const [browserRunning, setBrowserRunning] = useState(false)
  const [browserFrame, setBrowserFrame] = useState<string | null>(null)
  const [browserFrameMime, setBrowserFrameMime] = useState('image/jpeg')
  const [browserLogs, setBrowserLogs] = useState<BrowserEvent[]>([])
  const [browserUrl, setBrowserUrl] = useState('')
  const [browserTitle, setBrowserTitle] = useState('')
  const [browserStep, setBrowserStep] = useState(0)
  const [browserDone, setBrowserDone] = useState<string | null>(null)
  const browserLogRef = useRef<HTMLDivElement>(null)

  // MCP Hub
  const [mcpServers, setMcpServers] = useState<MCPServerInfo[]>([])
  const [mcpTotalTools, setMcpTotalTools] = useState(0)
  const [mcpActiveServer, setMcpActiveServer] = useState<MCPServerInfo | null>(null)
  const [mcpExpandedTool, setMcpExpandedTool] = useState<string | null>(null)
  const [mcpCallParams, setMcpCallParams] = useState<Record<string, string>>({})
  const [mcpCallResult, setMcpCallResult] = useState<MCPCallResult | null>(null)
  const [mcpCallLoading, setMcpCallLoading] = useState(false)
  const [mcpConfigServer, setMcpConfigServer] = useState<MCPServerInfo | null>(null)
  const [mcpConfigValues, setMcpConfigValues] = useState<Record<string, string>>({})
  const [mcpConfigSaving, setMcpConfigSaving] = useState(false)
  const [mcpHealthLoading, setMcpHealthLoading] = useState<string | null>(null)

  // SLM Matrix
  const [slmAgents, setSlmAgents] = useState<SLMAgent[]>([])
  const [slmClusters, setSlmClusters] = useState<Record<string, SLMAgent[]>>({})
  const [slmSearch, setSlmSearch] = useState('')
  const [selectedAgent, setSelectedAgent] = useState<SLMAgent | null>(null)
  const [expandedCluster, setExpandedCluster] = useState<string | null>(null)

  // SLM Phases
  const [slmPhases, setSlmPhases] = useState<SLMPhase[]>([])

  // Provider Health
  const [health, setHealth] = useState<Record<string, ProviderHealth>>({})
  const [healthLoading, setHealthLoading] = useState<Record<string, boolean>>({})

  // Terminal agent detection (Claude Code, Gemini CLI, Codex, OpenClaw)
  const [terminalAgents, setTerminalAgents] = useState<TerminalAgentInfo[]>([])

  // Git
  const [gitStatus, setGitStatus] = useState<GitStatus | null>(null)
  const [gitStats, setGitStats] = useState<{ added: number; removed: number } | null>(null)
  const [showCommit, setShowCommit] = useState(false)
  const [commitMsg, setCommitMsg] = useState('')
  const [commitLoading, setCommitLoading] = useState(false)

  // File explorer
  const [showFiles, setShowFiles] = useState(false)
  const [fileTree, setFileTree] = useState<FileNode[]>([])
  const [fileTreeLoading, setFileTreeLoading] = useState(false)
  const [openedFile, setOpenedFile] = useState<{ path: string; content: string } | null>(null)
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set())

  const inputRef = useRef<HTMLTextAreaElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  const activeThread = threads.find(t => t.id === activeThreadId) ?? null

  // ── Persist settings ───────────────────────────────────────────────────────
  useEffect(() => { storeSet('oc_agent', agentType) }, [agentType])
  useEffect(() => { storeSet('oc_model', model) }, [model])
  useEffect(() => { storeSet('oc_apikey', apiKey) }, [apiKey])
  useEffect(() => { storeSet('oc_geminikey', geminiApiKey) }, [geminiApiKey])
  useEffect(() => { storeSet('oc_lmhost', lmHost) }, [lmHost])
  useEffect(() => { storeSet('oc_ollamahost', ollamaHost) }, [ollamaHost])

  const urlPromptRef = useRef<string | null>(new URLSearchParams(window.location.search).get('prompt'))

  // ── Load on mount ──────────────────────────────────────────────────────────
  useEffect(() => {
    fetch('/api/projects')
      .then(r => r.json())
      .then((ps: Project[]) => {
        setProjects(ps)
        const last = store<string | null>('oc_last_project', null)
        const found = ps.find(p => p.id === last) ?? ps[0] ?? null
        setActiveProject(found)
      })
      .catch(() => {})

    fetch('/api/config').then(r => r.json()).then(d => setVersion(d.version)).catch(() => {})

    // Load SLM matrix
    fetch('/api/slm/agents')
      .then(r => r.json())
      .then(d => {
        setSlmAgents(d.agents ?? [])
        setSlmClusters(d.clusters ?? {})
      })
      .catch(() => {})

    // Load SLM phases
    fetch('/api/slm/phases')
      .then(r => r.json())
      .then(d => setSlmPhases(d.phases ?? []))
      .catch(() => {})

    // Load automations
    fetch('/api/automations')
      .then(r => r.json())
      .then((d: Automation[]) => setAutomations(d))
      .catch(() => {})

    // Load MCP servers
    fetch('/api/mcp/servers')
      .then(r => r.json())
      .then((d: { servers: MCPServerInfo[]; total_tools: number }) => {
        setMcpServers(d.servers ?? [])
        setMcpTotalTools(d.total_tools ?? 0)
        if (d.servers?.length > 0) setMcpActiveServer(d.servers[0])
      })
      .catch(() => {})

    // Detect installed terminal AI agent CLIs
    fetch('/api/agents/terminal')
      .then(r => r.json())
      .then((d: { agents: TerminalAgentInfo[] }) => setTerminalAgents(d.agents ?? []))
      .catch(() => {})

    if (urlPromptRef.current) setInput(urlPromptRef.current)
  }, [])

  // Auto-send URL prompt
  useEffect(() => {
    if (urlPromptRef.current && activeProject && !streaming) {
      const p = urlPromptRef.current
      urlPromptRef.current = null
      window.history.replaceState({}, '', window.location.pathname)
      sendMessage(p)
    }
  }, [activeProject, streaming])

  // ── Load threads when project changes ─────────────────────────────────────
  useEffect(() => {
    if (!activeProject) { setThreads([]); setActiveThreadId(null); return }
    storeSet('oc_last_project', activeProject.id)
    fetch(`/api/threads?project=${encodeURIComponent(activeProject.path)}`)
      .then(r => r.json())
      .then((ts: Thread[]) => {
        setThreads(ts)
        setActiveThreadId(ts[0]?.id ?? null)
      })
      .catch(() => setThreads([]))
    refreshGit()
  }, [activeProject])

  // ── Scroll to bottom ──────────────────────────────────────────────────────
  useEffect(() => {
    setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: 'smooth' }), 80)
  }, [activeThread?.messages.length, activeThreadId])

  // ── Git status ────────────────────────────────────────────────────────────
  const refreshGit = useCallback(() => {
    if (!activeProject?.git) return
    const enc = encodeURIComponent(activeProject.path)
    Promise.all([
      fetch(`/api/git/status?project=${enc}`).then(r => r.json()),
      fetch(`/api/git/stats?project=${enc}`).then(r => r.json()),
    ]).then(([status, stats]) => {
      setGitStatus(status)
      setGitStats(stats)
    }).catch(() => {})
  }, [activeProject])

  // ── Fetch models ──────────────────────────────────────────────────────────
  const fetchModels = useCallback(async () => {
    if (agentType === 'ollama_cloud') {
      setModels(['qwen3-coder:480b-cloud', 'deepseek-v3.1:671b-cloud', 'qwen3.5:latest-cloud', 'ministral-3:latest-cloud'])
      return
    }
    if (agentType === 'gemini') {
      setModels(['gemini-2.5-pro', 'gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-2.0-flash-lite'])
      return
    }
    if (TERMINAL_AGENT_IDS.includes(agentType)) {
      setModels([])  // terminal agents manage their own models
      return
    }
    setModelsLoading(true)
    try {
      const host = agentType === 'lmstudio' ? lmHost : ollamaHost
      const r = await fetch(`/api/models?source=${agentType}&host=${encodeURIComponent(host)}`)
      const d = await r.json()
      setModels(d.models ?? [])
    } catch { setModels([]) }
    finally { setModelsLoading(false) }
  }, [agentType, lmHost, ollamaHost])

  useEffect(() => { fetchModels() }, [fetchModels])

  // ── Provider health check ─────────────────────────────────────────────────
  const checkHealth = useCallback(async (provider: string) => {
    setHealthLoading(prev => ({ ...prev, [provider]: true }))
    try {
      const host = provider === 'lmstudio' ? lmHost : provider === 'ollama' ? ollamaHost : undefined
      const params = new URLSearchParams()
      if (host) params.set('host', host)
      if (provider === 'ollama_cloud' && apiKey) params.set('api_key', apiKey)
      if (provider === 'gemini' && geminiApiKey) params.set('api_key', geminiApiKey)
      const r = await fetch(`/api/health/${provider}?${params}`)
      const d = await r.json()
      setHealth(prev => ({ ...prev, [provider]: d }))
    } catch (e) {
      setHealth(prev => ({ ...prev, [provider]: { ok: false, hint: String(e) } }))
    } finally {
      setHealthLoading(prev => ({ ...prev, [provider]: false }))
    }
  }, [lmHost, ollamaHost, apiKey, geminiApiKey])

  useEffect(() => {
    if (activePanel === 'health') {
      ['lmstudio', 'ollama', 'ollama_cloud', 'gemini'].forEach(p => checkHealth(p))
    }
  }, [activePanel])

  // ── Project management ────────────────────────────────────────────────────
  async function pickProjectDialog() {
    try {
      const r = await fetch('/api/projects/pick', { method: 'POST' })
      const d = await r.json()
      if (d.path) setAddProjectInput(d.path)
    } catch {}
  }

  async function addProject() {
    const path = addProjectInput.trim()
    if (!path) return
    try {
      const r = await fetch('/api/projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path }),
      })
      if (!r.ok) { const e = await r.json(); alert(e.detail || 'Failed to add project'); return }
      const project: Project = await r.json()
      setProjects(prev => [...prev, project])
      setActiveProject(project)
      setShowAddProject(false)
      setAddProjectInput('')
    } catch (e) { alert(String(e)) }
  }

  async function removeProject(id: string) {
    await fetch(`/api/projects/${id}`, { method: 'DELETE' })
    setProjects(prev => {
      const next = prev.filter(p => p.id !== id)
      if (activeProject?.id === id) setActiveProject(next[0] ?? null)
      return next
    })
  }

  // ── Thread management ─────────────────────────────────────────────────────
  function newThread() {
    if (!activeProject) return
    const t: Thread = { id: uid(), title: 'New thread', messages: [], ts: Date.now() }
    setThreads(prev => [t, ...prev])
    setActiveThreadId(t.id)
    setInput('')
    setTimeout(() => inputRef.current?.focus(), 80)
  }

  async function deleteThread(tid: string) {
    if (!activeProject) return
    setThreads(prev => {
      const next = prev.filter(t => t.id !== tid)
      if (activeThreadId === tid) setActiveThreadId(next[0]?.id ?? null)
      return next
    })
    await fetch(`/api/threads/${tid}?project=${encodeURIComponent(activeProject.path)}`, { method: 'DELETE' })
  }

  async function persistThread(thread: Thread) {
    if (!activeProject) return
    await fetch('/api/threads', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project_dir: activeProject.path, thread }),
    }).catch(() => {})
  }

  // ── SLM Matrix actions ────────────────────────────────────────────────────
  function activateAgent(agent: SLMAgent) {
    setSelectedAgent(agent)
    // Insert keyword into input as preamble command
    setInput(prev => {
      const base = prev.trim()
      return base ? base : `[${agent.keyword}] `
    })
    setActivePanel(null)
    setTimeout(() => inputRef.current?.focus(), 80)
  }

  function clearSelectedAgent() {
    setSelectedAgent(null)
  }

  // Filter agents for matrix view
  const filteredAgents = slmSearch
    ? slmAgents.filter(a =>
        a.name.toLowerCase().includes(slmSearch.toLowerCase()) ||
        a.coord.toLowerCase().includes(slmSearch.toLowerCase()) ||
        a.cluster.toLowerCase().includes(slmSearch.toLowerCase()) ||
        a.brilliance.toLowerCase().includes(slmSearch.toLowerCase())
      )
    : slmAgents

  const filteredClusters = slmSearch
    ? (() => {
        const out: Record<string, SLMAgent[]> = {}
        filteredAgents.forEach(a => {
          if (!out[a.cluster]) out[a.cluster] = []
          out[a.cluster].push(a)
        })
        return out
      })()
    : slmClusters

  // ── Phase launcher ────────────────────────────────────────────────────────
  function launchPhase(phase: SLMPhase) {
    if (!activeProject) { alert('Select a project first'); return }
    setActivePanel(null)
    setInput(phase.prompt)
    setTimeout(() => sendMessage(phase.prompt), 100)
  }

  // ── Send message ──────────────────────────────────────────────────────────
  async function sendMessage(overrideText?: string) {
    const text = (overrideText ?? input).trim()
    if (!text || streaming || !activeProject) return

    let tid = activeThreadId
    let isNew = false

    if (!tid) {
      const t: Thread = { id: uid(), title: text.slice(0, 50), messages: [], ts: Date.now() }
      setThreads(prev => [t, ...prev])
      setActiveThreadId(t.id)
      tid = t.id
      isNew = true
    }

    const userMsg: Message = {
      id: uid(), role: 'user', content: text, events: [], done: true, ts: Date.now(),
      slmRole: selectedAgent ? selectedAgent.name : undefined,
    }
    const assistantMsg: Message = { id: uid(), role: 'assistant', content: '', events: [], done: false, ts: Date.now() }
    const aId = assistantMsg.id

    setThreads(prev => prev.map(t => t.id === tid ? {
      ...t,
      title: isNew ? text.slice(0, 50) : t.title,
      messages: [...t.messages, userMsg, assistantMsg],
    } : t))
    setInput('')
    if (inputRef.current) inputRef.current.style.height = 'auto'
    setStreaming(true)

    try {
      const host = agentType === 'lmstudio' ? lmHost
        : agentType === 'ollama' ? ollamaHost
        : agentType === 'ollama_cloud' ? 'https://ollama.com'
        : undefined  // gemini & terminal agents don't use a host

      // Build SLM context preamble if an agent is selected
      const slmContext = selectedAgent
        ? `You are operating as the ${selectedAgent.name} (${selectedAgent.coord}).\nRole brilliance: ${selectedAgent.brilliance}.\nKeyword: ${selectedAgent.keyword}.\nApply this specialized expertise lens to everything in this conversation.`
        : undefined

      const res = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          project_dir: activeProject.path,
          agent_type: agentType,
          model: model || null,
          host,
          api_key: agentType === 'ollama_cloud' ? apiKey || undefined
                 : agentType === 'gemini' ? geminiApiKey || undefined
                 : undefined,
          thread_id: tid,
          slm_context: slmContext,
        }),
      })

      if (!res.ok) throw new Error(`HTTP ${res.status}`)

      const reader = res.body!.getReader()
      const decoder = new TextDecoder()
      let buf = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const parts = buf.split('\n\n')
        buf = parts.pop() ?? ''

        for (const part of parts) {
          if (!part.startsWith('data: ')) continue
          let ev: AgentEvent
          try { ev = JSON.parse(part.slice(6)) } catch { continue }

          // Capture stream_id for abort
          if (ev.type === 'stream_id' && ev.stream_id) {
            setActiveStreamId(ev.stream_id)
            continue
          }

          if (ev.type === 'aborted') { break }

          setThreads(prev => prev.map(t => t.id === tid ? {
            ...t,
            messages: t.messages.map(m => m.id === aId ? {
              ...m,
              events: [...m.events, ev],
              content: ev.type === 'message' ? ev.content ?? m.content : m.content,
              done: ev.type === 'done',
              stats: ev.type === 'done' ? ev.stats : m.stats,
            } : m),
            stats: ev.type === 'done' && ev.stats
              ? { added: ev.stats.added ?? 0, removed: ev.stats.removed ?? 0 }
              : t.stats,
          } : t))

          if (ev.type === 'file_changed') refreshGit()
          if (ev.type === 'done') { refreshGit(); setActiveStreamId(null) }
        }
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setThreads(prev => prev.map(t => t.id === tid ? {
        ...t,
        messages: t.messages.map(m => m.id === aId
          ? { ...m, content: `Error: ${msg}`, done: true } : m),
      } : t))
    } finally {
      setStreaming(false)
      setActiveStreamId(null)
      setThreads(prev => {
        const thread = prev.find(t => t.id === tid)
        if (thread) persistThread(thread)
        return prev
      })
    }
  }

  // ── Abort stream ──────────────────────────────────────────────────────────
  async function abortStream() {
    if (!activeStreamId) return
    try {
      await fetch(`/api/chat/abort/${activeStreamId}`, { method: 'POST' })
    } catch {}
  }

  // ── Delete individual message (kill stream if pending) ────────────────────
  async function deleteMessage(threadId: string, msgId: string) {
    const thread = threads.find(t => t.id === threadId)
    if (!thread) return
    const msg = thread.messages.find(m => m.id === msgId)
    if (!msg) return

    // If this is the active in-flight assistant message, kill the stream first
    if (msg.role === 'assistant' && !msg.done && streaming) {
      await abortStream()
      setStreaming(false)
      setActiveStreamId(null)
    }

    const updatedMessages = thread.messages.filter(m => m.id !== msgId)
    const updatedThread = { ...thread, messages: updatedMessages }
    setThreads(prev => prev.map(t => t.id === threadId ? updatedThread : t))
    persistThread(updatedThread)
  }

  // ── Commit ────────────────────────────────────────────────────────────────
  async function doCommit() {
    if (!activeProject || !commitMsg.trim()) return
    setCommitLoading(true)
    try {
      const r = await fetch('/api/git/commit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_dir: activeProject.path, message: commitMsg }),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail)
      setCommitMsg('')
      setShowCommit(false)
      refreshGit()
    } catch (e) { alert(String(e)) }
    finally { setCommitLoading(false) }
  }

  // ── Key handler ───────────────────────────────────────────────────────────
  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); sendMessage() }
    if (e.key === 'Escape') { clearSelectedAgent() }
  }

  function onInputChange(e: ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value)
    e.target.style.height = 'auto'
    e.target.style.height = Math.min(e.target.scrollHeight, 200) + 'px'
  }

  // ── File panel ────────────────────────────────────────────────────────────
  const loadFileTree = useCallback(async () => {
    if (!activeProject) return
    setFileTreeLoading(true)
    try {
      // Uses correct endpoint /api/projects/{id}/tree (bug fixed)
      const r = await fetch(`/api/projects/${encodeURIComponent(activeProject.id)}/tree`)
      const d = await r.json()
      setFileTree(d.tree ?? [])
    } catch { setFileTree([]) }
    finally { setFileTreeLoading(false) }
  }, [activeProject])

  useEffect(() => {
    if (showFiles && activeProject) loadFileTree()
  }, [showFiles, activeProject, loadFileTree])

  async function openFile(path: string) {
    try {
      const r = await fetch(`/api/file?path=${encodeURIComponent(path)}&project=${encodeURIComponent(activeProject!.path)}`)
      const d = await r.json()
      setOpenedFile({ path, content: d.content ?? '' })
    } catch { setOpenedFile({ path, content: '(could not read file)' }) }
  }

  function toggleDir(path: string) {
    setExpandedDirs(prev => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path); else next.add(path)
      return next
    })
  }

  function renderFileNode(node: FileNode, depth = 0): React.ReactNode {
    const indent = depth * 14
    if (node.type === 'directory') {
      const open = expandedDirs.has(node.path)
      return (
        <div key={node.path}>
          <div className="ft-dir" style={{ paddingLeft: indent + 8 }} onClick={() => toggleDir(node.path)}>
            <span className="ft-caret">{open ? '▾' : '▸'}</span>
            <span className="ft-dir-icon">📁</span>
            <span className="ft-name">{node.name}</span>
          </div>
          {open && node.children?.map(c => renderFileNode(c, depth + 1))}
        </div>
      )
    }
    return (
      <div key={node.path} className={`ft-file ${openedFile?.path === node.path ? 'active' : ''}`}
        style={{ paddingLeft: indent + 8 }} onClick={() => openFile(node.path)}>
        <span className="ft-file-icon">{fileIcon(node.name)}</span>
        <span className="ft-name">{node.name}</span>
      </div>
    )
  }

  function fileIcon(name: string) {
    const ext = name.split('.').pop()?.toLowerCase() ?? ''
    const map: Record<string, string> = {
      ts: '🟦', tsx: '🟦', js: '🟨', jsx: '🟨',
      py: '🐍', rs: '🦀', go: '🐹', md: '📝',
      json: '{}', css: '🎨', html: '🌐', sh: '⚡',
      toml: '⚙', yaml: '📋', yml: '📋', txt: '📄',
    }
    return map[ext] ?? '📄'
  }

  // ── Event rendering ───────────────────────────────────────────────────────
  function renderEvent(ev: AgentEvent, i: number) {
    switch (ev.type) {
      case 'thinking': return null
      case 'thinking_text':
        return ev.content
          ? <div key={i} className="ev-thinking-text">💭 {ev.content}</div>
          : null
      case 'tool_call':
        return (
          <details key={i} className="ev-tool">
            <summary>
              <span className="ev-tool-icon">{toolIcon(ev.tool)}</span>
              <span className="ev-tool-name">{ev.tool}</span>
              {ev.args && <span className="ev-tool-args">{renderArgs(ev.tool, ev.args)}</span>}
            </summary>
          </details>
        )
      case 'tool_result':
        return (
          <details key={i} className="ev-result">
            <summary>Result from {ev.tool}</summary>
            <pre className="ev-result-pre">{ev.result}</pre>
          </details>
        )
      case 'file_changed':
        return (
          <div key={i} className="ev-file-changed">
            <span className="ev-file-icon">✏</span>
            <span className="ev-file-path">{ev.path}</span>
          </div>
        )
      case 'error':
        return <div key={i} className="ev-error">⚠️ {ev.content}</div>
      default: return null
    }
  }

  function toolIcon(tool?: string) {
    const map: Record<string, string> = {
      list_directory: '📂', read_file: '📄', write_file: '✏️',
      run_command: '⚡', search_files: '🔍', create_file: '🆕',
    }
    return tool ? (map[tool] ?? '🔧') : '🔧'
  }

  function renderArgs(tool?: string, args?: Record<string, unknown>) {
    if (!args) return ''
    if (tool === 'write_file' || tool === 'create_file') return args.path as string
    if (tool === 'run_command') return args.command as string
    return Object.values(args).join(' ')
  }

  const hasChanges = (gitStats?.added ?? 0) + (gitStats?.removed ?? 0) > 0

  // ── Panel toggles ─────────────────────────────────────────────────────────
  function togglePanel(p: Panel) {
    setActivePanel(prev => prev === p ? null : p)
    setShowSettings(false)
  }

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="app">

      {/* ── Sidebar ───────────────────────────────────────────────── */}
      <aside className="sidebar">
        <div className="sb-logo">
          <div className="sb-logo-icon">⬡</div>
          <div className="sb-logo-text">
            <span className="sb-logo-name">Open Codex</span>
            <span className="sb-logo-tag">SLM-v3</span>
          </div>
        </div>

        {/* Top actions */}
        <div className="sb-top">
          <button id="btn-new-thread" className="sb-action primary" onClick={newThread} disabled={!activeProject}>
            <span className="sb-action-icon">✎</span> New Thread
          </button>
          <button id="btn-matrix" className={`sb-action ${activePanel === 'matrix' ? 'active' : ''}`}
            onClick={() => togglePanel('matrix')}>
            <span className="sb-action-icon">⬡</span> Agent Matrix
            <span className="sb-badge">{slmAgents.length}</span>
          </button>
          <button id="btn-phases" className={`sb-action ${activePanel === 'phases' ? 'active' : ''}`}
            onClick={() => togglePanel('phases')}>
            <span className="sb-action-icon">◈</span> Phase Launcher
          </button>
          <button id="btn-health" className={`sb-action ${activePanel === 'health' ? 'active' : ''}`}
            onClick={() => togglePanel('health')}>
            <span className="sb-action-icon">◉</span> Provider Health
          </button>
          <button id="btn-mcp" className={`sb-action ${activePanel === 'mcp' ? 'active' : ''}`}
            onClick={() => togglePanel('mcp')}>
            <span className="sb-action-icon">⊕</span> MCP Hub
            {mcpTotalTools > 0 && <span className="sb-badge mcp-badge">{mcpTotalTools}</span>}
          </button>
          <button id="btn-yoo" className={`sb-action ${activePanel === 'yoo' ? 'active' : ''}`}
            onClick={() => togglePanel('yoo')}>
            <span className="sb-action-icon">🏗</span> YOO Builder
          </button>
        </div>

        {/* Thread list */}
        {activeProject && threads.length > 0 && (
          <div className="sb-threads">
            <div className="sb-section-label">RECENT THREADS</div>
            {threads.map(t => (
              <button key={t.id} id={`thread-${t.id}`}
                className={`sb-thread ${t.id === activeThreadId ? 'active' : ''}`}
                onClick={() => setActiveThreadId(t.id)}>
                <div className="sb-thread-row">
                  <span className="sb-thread-title">{t.title}</span>
                  <div className="sb-thread-meta">
                    {t.stats && (t.stats.added > 0 || t.stats.removed > 0) && (
                      <span className="diff-mini">
                        {t.stats.added > 0 && <span className="diff-add">+{t.stats.added}</span>}
                        {t.stats.removed > 0 && <span className="diff-rem">-{t.stats.removed}</span>}
                      </span>
                    )}
                    <span className="sb-thread-age">{timeAgo(t.ts)}</span>
                    <span className="sb-thread-del" onClick={e => { e.stopPropagation(); deleteThread(t.id) }}>×</span>
                  </div>
                </div>
              </button>
            ))}
          </div>
        )}

        <div className="sb-spacer" />

        {/* Projects */}
        <div className="sb-projects-header">
          <span>PROJECTS</span>
          <button id="btn-add-project" className="sb-add-btn" onClick={() => setShowAddProject(s => !s)} title="Add project">+</button>
        </div>

        {showAddProject && (
          <div className="sb-add-project">
            <input className="sb-path-input" placeholder="/path/to/project"
              value={addProjectInput} onChange={e => setAddProjectInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && addProject()} />
            <div className="sb-add-row">
              <button id="btn-browse" className="sb-pick-btn" onClick={pickProjectDialog}>Browse</button>
              <button id="btn-open-project" className="sb-confirm-btn" onClick={addProject}>Open</button>
            </div>
          </div>
        )}

        <div className="sb-project-list">
          {projects.map(p => (
            <button key={p.id} id={`project-${p.id}`}
              className={`sb-project ${activeProject?.id === p.id ? 'active' : ''}`}
              onClick={() => setActiveProject(p)}>
              <span className="sb-project-icon">{p.git ? '⎇' : '📁'}</span>
              <span className="sb-project-name">{p.name}</span>
              <span className="sb-project-del" onClick={e => { e.stopPropagation(); removeProject(p.id) }}>×</span>
            </button>
          ))}
          {projects.length === 0 && (
            <div className="sb-no-projects">
              No projects yet.<br />
              Click <strong>+</strong> to add a folder.
            </div>
          )}
        </div>

        {/* Settings */}
        <div className="sb-bottom">
          <button id="btn-settings" className="sb-settings-toggle" onClick={() => { setShowSettings(s => !s); setActivePanel(null) }}>
            <span>⚙</span>
            <span>{AGENT_LABELS[agentType]}</span>
            {model && <span className="sb-model-tag">{model.split(':')[0]}</span>}
          </button>
          {showSettings && (
            <div className="sb-settings">
              <div className="sb-set-label">MODEL SOURCE</div>
              {(['lmstudio', 'ollama', 'ollama_cloud', 'gemini'] as AgentType[]).map(a => (
                <button key={a} id={`agent-${a}`}
                  className={`sb-set-radio ${agentType === a ? 'active' : ''}`}
                  onClick={() => { setAgentType(a); setModel('') }}>
                  {AGENT_LABELS[a]}
                </button>
              ))}
              <div className="sb-set-label" style={{ marginTop: 8 }}>MODEL</div>
              <div className="sb-model-row">
                <select id="model-select" className="sb-model-select" value={model} onChange={e => setModel(e.target.value)}
                  disabled={TERMINAL_AGENT_IDS.includes(agentType)}>
                  <option value="">{TERMINAL_AGENT_IDS.includes(agentType) ? 'Managed by CLI' : 'Auto'}</option>
                  {models.map(m => <option key={m} value={m}>{m}</option>)}
                </select>
                <button id="btn-refresh-models" className="sb-refresh" onClick={fetchModels}
                  disabled={modelsLoading || TERMINAL_AGENT_IDS.includes(agentType)}>↻</button>
              </div>
              {(agentType === 'lmstudio' || agentType === 'ollama') && (
                <>
                  <div className="sb-set-label" style={{ marginTop: 8 }}>HOST</div>
                  <input className="sb-set-input"
                    value={agentType === 'lmstudio' ? lmHost : ollamaHost}
                    onChange={e => agentType === 'lmstudio' ? setLmHost(e.target.value) : setOllamaHost(e.target.value)} />
                </>
              )}
              {agentType === 'ollama_cloud' && (
                <>
                  <div className="sb-set-label" style={{ marginTop: 8 }}>API KEY</div>
                  <input type="password" className="sb-set-input" value={apiKey} onChange={e => setApiKey(e.target.value)} />
                </>
              )}
              {agentType === 'gemini' && (
                <>
                  <div className="sb-set-label" style={{ marginTop: 8 }}>GEMINI API KEY</div>
                  <input type="password" className="sb-set-input" placeholder="AIza..." value={geminiApiKey} onChange={e => setGeminiApiKey(e.target.value)} />
                </>
              )}

              {/* ── Terminal AI Agents ──────────────────────────────────── */}
              {terminalAgents.length > 0 && (
                <>
                  <div className="sb-set-label" style={{ marginTop: 12 }}>TERMINAL AGENTS</div>
                  {terminalAgents.map(ta => {
                    const isActive = agentType === ta.id
                    const statusDot = ta.available
                      ? (ta.authenticated ? '●' : '◐')
                      : '○'
                    const statusColor = ta.available
                      ? (ta.authenticated ? '#4ade80' : '#facc15')
                      : '#6b7280'
                    const title = ta.available
                      ? (ta.authenticated
                          ? `${ta.label} — ready (${ta.version ?? ''})`
                          : `${ta.label} installed but not authenticated. ${ta.auth_hint}`)
                      : `${ta.label} not installed`
                    return (
                      <button key={ta.id}
                        id={`agent-${ta.id}`}
                        className={`sb-set-radio ta-radio ${isActive ? 'active' : ''} ${!ta.available ? 'ta-unavailable' : ''}`}
                        title={title}
                        onClick={() => { if (ta.available) { setAgentType(ta.id as AgentType); setModel('') } }}>
                        <span style={{ color: statusColor, marginRight: 4, fontSize: 10 }}>{statusDot}</span>
                        <span>{ta.icon} {ta.label}</span>
                        {!ta.available && <span className="ta-badge">not installed</span>}
                        {ta.available && !ta.authenticated && <span className="ta-badge ta-badge-warn">auth needed</span>}
                      </button>
                    )
                  })}
                  {TERMINAL_AGENT_IDS.includes(agentType) && (
                    <div className="ta-hint">
                      {(() => {
                        const info = terminalAgents.find(t => t.id === agentType)
                        return info
                          ? (info.authenticated
                              ? `Running via ${info.path ?? info.label}`
                              : info.auth_hint)
                          : null
                      })()}
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </aside>

      {/* ── Agent Matrix Panel ────────────────────────────────────── */}
      {activePanel === 'matrix' && (
        <aside className="slm-panel">
          <div className="slm-panel-header">
            <div className="slm-panel-title">
              <span className="slm-panel-icon">⬡</span>
              <span>Sovereign Liquid Matrix</span>
              <span className="slm-count">{slmAgents.length} agents</span>
            </div>
            <button id="btn-close-matrix" className="panel-close" onClick={() => setActivePanel(null)}>✕</button>
          </div>
          <div className="slm-search-wrap">
            <input id="slm-search" className="slm-search" placeholder="Search agents, clusters, brilliance..."
              value={slmSearch} onChange={e => setSlmSearch(e.target.value)} autoFocus />
            {slmSearch && <button className="slm-search-clear" onClick={() => setSlmSearch('')}>✕</button>}
          </div>
          <div className="slm-clusters">
            {Object.entries(filteredClusters).map(([cluster, agents]) => {
              const h = CLUSTER_HUE[cluster] ?? 262
              const isExpanded = expandedCluster === cluster || !!slmSearch
              return (
                <div key={cluster} className="slm-cluster">
                  <button
                    id={`cluster-${cluster.replace(/[^a-z]/gi, '-').toLowerCase()}`}
                    className="slm-cluster-header"
                    style={{ '--cluster-hue': h } as React.CSSProperties}
                    onClick={() => setExpandedCluster(isExpanded && !slmSearch ? null : cluster)}>
                    <span className="slm-cluster-dot" style={{ background: clusterColor(cluster) }} />
                    <span className="slm-cluster-name">{cluster}</span>
                    <span className="slm-cluster-count">{agents.length}</span>
                    <span className="slm-cluster-caret">{isExpanded ? '▾' : '▸'}</span>
                  </button>
                  {isExpanded && (
                    <div className="slm-cells">
                      {agents.map(agent => (
                        <button
                          key={agent.coord}
                          id={`agent-${agent.coord}`}
                          className={`slm-cell ${selectedAgent?.coord === agent.coord ? 'active' : ''}`}
                          style={{
                            '--cell-hue': h,
                            background: clusterBg(cluster),
                            borderColor: clusterBorder(cluster),
                          } as React.CSSProperties}
                          onClick={() => activateAgent(agent)}>
                          <div className="slm-cell-coord" style={{ color: clusterColor(cluster) }}>{agent.coord}</div>
                          <div className="slm-cell-name">{agent.name}</div>
                          <div className="slm-cell-brilliance">{agent.brilliance}</div>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}
            {Object.keys(filteredClusters).length === 0 && (
              <div className="slm-empty">No agents match "{slmSearch}"</div>
            )}
          </div>
        </aside>
      )}

      {/* ── Phase Launcher Panel ──────────────────────────────────── */}
      {activePanel === 'phases' && (
        <aside className="slm-panel phases-panel">
          <div className="slm-panel-header">
            <div className="slm-panel-title">
              <span className="slm-panel-icon">◈</span>
              <span>Phase Launcher</span>
              <span className="slm-count">SLM-v3 Sequences</span>
            </div>
            <button id="btn-close-phases" className="panel-close" onClick={() => setActivePanel(null)}>✕</button>
          </div>
          <div className="phases-list">
            {slmPhases.map(phase => (
              <div key={phase.id} className="phase-card">
                <div className="phase-header">
                  <span className="phase-num">Phase {phase.phase_num}</span>
                  <span className="phase-name">{phase.name}</span>
                </div>
                <div className="phase-desc">{phase.description}</div>
                <div className="phase-chain">
                  {phase.chain.map(c => (
                    <span key={c} className="phase-chip">{c}</span>
                  ))}
                </div>
                <button
                  id={`launch-phase-${phase.phase_num}`}
                  className="phase-launch-btn"
                  onClick={() => launchPhase(phase)}
                  disabled={!activeProject}>
                  {activeProject ? `▶ Launch Phase ${phase.phase_num}` : 'Select a project first'}
                </button>
              </div>
            ))}
          </div>
        </aside>
      )}

      {/* ── Provider Health Panel ─────────────────────────────────── */}
      {activePanel === 'health' && (
        <aside className="slm-panel health-panel">
          <div className="slm-panel-header">
            <div className="slm-panel-title">
              <span className="slm-panel-icon">◉</span>
              <span>Provider Health</span>
            </div>
            <button id="btn-close-health" className="panel-close" onClick={() => setActivePanel(null)}>✕</button>
          </div>
          <div className="health-list">
            {(['lmstudio', 'ollama', 'ollama_cloud', 'gemini'] as AgentType[]).map(provider => {
              const h = health[provider]
              const loading = healthLoading[provider]
              return (
                <div key={provider} className={`health-card ${h?.ok ? 'ok' : h ? 'fail' : 'unknown'}`}>
                  <div className="health-card-header">
                    <div className="health-pill">
                      {loading ? <span className="health-spinner" /> : h?.ok ? '✓' : h ? '✗' : '?'}
                    </div>
                    <span className="health-provider">{AGENT_LABELS[provider]}</span>
                    <button id={`btn-check-${provider}`} className="health-refresh" onClick={() => checkHealth(provider)}>↻</button>
                  </div>
                  {h?.hint && <div className="health-hint">{h.hint}</div>}
                  {h?.ok && h.models && h.models.length > 0 && (
                    <div className="health-models">
                      {h.models.slice(0, 5).map(m => <span key={m} className="health-model-tag">{m}</span>)}
                      {h.models.length > 5 && <span className="health-model-more">+{h.models.length - 5} more</span>}
                    </div>
                  )}
                  {h?.ok && (!h.models || h.models.length === 0) && (
                    <div className="health-hint ok">Ready — loads on first use</div>
                  )}
                </div>
              )
            })}
          </div>
        </aside>
      )}

      {/* ── MCP Hub Panel ────────────────────────────────────────── */}
      {activePanel === 'mcp' && (
        <aside className="slm-panel mcp-panel">
          <div className="slm-panel-header">
            <div className="slm-panel-title">
              <span className="slm-panel-icon">⊕</span>
              <span>MCP Hub</span>
              <span className="mcp-total-badge">{mcpTotalTools} tools</span>
            </div>
            <button id="btn-close-mcp" className="panel-close" onClick={() => setActivePanel(null)}>✕</button>
          </div>

          {/* Config drawer */}
          {mcpConfigServer && (
            <div className="mcp-config-drawer">
              <div className="mcp-config-header">
                <span>{mcpConfigServer.icon} {mcpConfigServer.name} — Configuration</span>
                <button className="mcp-config-close" onClick={() => { setMcpConfigServer(null); setMcpConfigValues({}) }}>✕</button>
              </div>
              <div className="mcp-config-body">
                {mcpConfigServer.config_keys.map(k => (
                  <div key={k} className="mcp-config-row">
                    <label className="mcp-config-label">
                      {k}
                      {mcpConfigServer.config_set[k]
                        ? <span className="mcp-config-set">● set</span>
                        : <span className="mcp-config-unset">○ not set</span>}
                    </label>
                    <input
                      id={`mcp-cfg-${mcpConfigServer.id}-${k}`}
                      className="mcp-config-input"
                      type={k.toLowerCase().includes('token') || k.toLowerCase().includes('key') || k.toLowerCase().includes('secret') ? 'password' : 'text'}
                      placeholder={`Enter ${k}…`}
                      value={mcpConfigValues[k] ?? ''}
                      onChange={e => setMcpConfigValues(v => ({ ...v, [k]: e.target.value }))}
                    />
                  </div>
                ))}
                <button
                  id={`btn-save-mcp-config-${mcpConfigServer.id}`}
                  className="mcp-config-save"
                  disabled={mcpConfigSaving}
                  onClick={async () => {
                    setMcpConfigSaving(true)
                    try {
                      await fetch(`/api/mcp/servers/${mcpConfigServer.id}/config`, {
                        method: 'PATCH',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ config: mcpConfigValues }),
                      })
                      // re-fetch servers to update config_set indicators
                      const d = await fetch('/api/mcp/servers').then(r => r.json())
                      setMcpServers(d.servers ?? [])
                      setMcpTotalTools(d.total_tools ?? 0)
                      setMcpConfigServer(null)
                      setMcpConfigValues({})
                    } catch { /* ignore */ }
                    setMcpConfigSaving(false)
                  }}
                >
                  {mcpConfigSaving ? 'Saving…' : '✓ Save Configuration'}
                </button>
              </div>
            </div>
          )}

          {/* Server list → tool list */}
          <div className="mcp-body">
            {/* Server selector tabs */}
            <div className="mcp-server-tabs">
              {mcpServers.map(srv => (
                <button
                  key={srv.id}
                  id={`btn-mcp-srv-${srv.id}`}
                  className={`mcp-server-tab ${mcpActiveServer?.id === srv.id ? 'active' : ''}`}
                  onClick={() => { setMcpActiveServer(srv); setMcpExpandedTool(null); setMcpCallResult(null) }}
                >
                  <span className="mcp-srv-icon">{srv.icon}</span>
                  <span className="mcp-srv-name">{srv.name}</span>
                  <span className={`mcp-health-dot ${srv.healthy ? 'ok' : 'fail'}`} />
                </button>
              ))}
            </div>

            {/* Active server detail */}
            {mcpActiveServer && (
              <div className="mcp-server-detail">
                <div className="mcp-server-info">
                  <div className="mcp-server-info-left">
                    <span className="mcp-server-desc">{mcpActiveServer.description}</span>
                    <span className="mcp-server-count">{mcpActiveServer.tool_count} tools</span>
                  </div>
                  <div className="mcp-server-actions">
                    <button
                      id={`btn-mcp-health-${mcpActiveServer.id}`}
                      className="mcp-action-btn"
                      disabled={mcpHealthLoading === mcpActiveServer.id}
                      onClick={async () => {
                        setMcpHealthLoading(mcpActiveServer.id)
                        try {
                          const d = await fetch(`/api/mcp/servers/${mcpActiveServer.id}/health`).then(r => r.json())
                          setMcpServers(prev => prev.map(s => s.id === mcpActiveServer.id ? { ...s, healthy: d.healthy } : s))
                          setMcpActiveServer(prev => prev ? { ...prev, healthy: d.healthy } : prev)
                        } catch { /* ignore */ }
                        setMcpHealthLoading(null)
                      }}
                    >
                      {mcpHealthLoading === mcpActiveServer.id ? '◌' : '↻'} Ping
                    </button>
                    <button
                      id={`btn-mcp-config-${mcpActiveServer.id}`}
                      className="mcp-action-btn"
                      onClick={() => { setMcpConfigServer(mcpActiveServer); setMcpConfigValues({}) }}
                    >
                      ⚙ Config
                    </button>
                  </div>
                </div>

                {/* Tool list */}
                <div className="mcp-tool-list">
                  {mcpActiveServer.tools.map(tool => {
                    const isExpanded = mcpExpandedTool === `${mcpActiveServer.id}:${tool.name}`
                    const paramKeys = Object.keys(tool.parameters)
                    return (
                      <div key={tool.name} className={`mcp-tool-card ${isExpanded ? 'expanded' : ''}`}>
                        <button
                          id={`btn-mcp-tool-${mcpActiveServer.id}-${tool.name}`}
                          className="mcp-tool-header"
                          onClick={() => {
                            const key = `${mcpActiveServer.id}:${tool.name}`
                            if (isExpanded) {
                              setMcpExpandedTool(null)
                              setMcpCallResult(null)
                            } else {
                              setMcpExpandedTool(key)
                              setMcpCallParams({})
                              setMcpCallResult(null)
                            }
                          }}
                        >
                          <span className="mcp-tool-name">{tool.name}</span>
                          <span className="mcp-tool-desc">{tool.description}</span>
                          <span className="mcp-tool-chevron">{isExpanded ? '▲' : '▼'}</span>
                        </button>
                        {isExpanded && (
                          <div className="mcp-tool-body">
                            {paramKeys.length > 0 && (
                              <div className="mcp-tool-params">
                                {paramKeys.map(pk => {
                                  const pdef = tool.parameters[pk]
                                  return (
                                    <div key={pk} className="mcp-param-row">
                                      <label className="mcp-param-label">
                                        {pk}
                                        {pdef.required && <span className="mcp-param-req">*</span>}
                                        <span className="mcp-param-type">{pdef.type}</span>
                                      </label>
                                      <input
                                        id={`mcp-param-${mcpActiveServer.id}-${tool.name}-${pk}`}
                                        className="mcp-param-input"
                                        placeholder={pdef.description ?? pdef.type}
                                        value={mcpCallParams[pk] ?? ''}
                                        onChange={e => setMcpCallParams(p => ({ ...p, [pk]: e.target.value }))}
                                      />
                                    </div>
                                  )
                                })}
                              </div>
                            )}
                            <button
                              id={`btn-mcp-call-${mcpActiveServer.id}-${tool.name}`}
                              className="mcp-call-btn"
                              disabled={mcpCallLoading}
                              onClick={async () => {
                                setMcpCallLoading(true)
                                setMcpCallResult(null)
                                try {
                                  // Parse JSON values for non-string params
                                  const params: Record<string, unknown> = {}
                                  for (const [k, v] of Object.entries(mcpCallParams)) {
                                    const pdef = tool.parameters[k]
                                    if (pdef?.type === 'integer') params[k] = parseInt(v)
                                    else if (pdef?.type === 'boolean') params[k] = v === 'true'
                                    else if (pdef?.type === 'array' || pdef?.type === 'object') {
                                      try { params[k] = JSON.parse(v) } catch { params[k] = v }
                                    } else params[k] = v
                                  }
                                  const res = await fetch('/api/mcp/call', {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({
                                      server_id: mcpActiveServer.id,
                                      tool: tool.name,
                                      params,
                                      project_dir: activeProject?.path,
                                    }),
                                  })
                                  if (res.ok) {
                                    const data = await res.json()
                                    setMcpCallResult({ result: data.result, error: null, tool: tool.name, server: mcpActiveServer.id })
                                  } else {
                                    const err = await res.json()
                                    setMcpCallResult({ result: null, error: err.detail ?? 'Error', tool: tool.name, server: mcpActiveServer.id })
                                  }
                                } catch (e: unknown) {
                                  setMcpCallResult({ result: null, error: String(e), tool: tool.name, server: mcpActiveServer.id })
                                }
                                setMcpCallLoading(false)
                              }}
                            >
                              {mcpCallLoading ? '◌ Running…' : `▶ Call ${tool.name}`}
                            </button>
                            {mcpCallResult && mcpCallResult.tool === tool.name && (
                              <div className={`mcp-result-bubble ${mcpCallResult.error ? 'error' : 'ok'}`}>
                                <div className="mcp-result-label">{mcpCallResult.error ? '✗ Error' : '✓ Result'}</div>
                                <pre className="mcp-result-pre">{mcpCallResult.error ?? mcpCallResult.result}</pre>
                                <button className="mcp-result-inject" onClick={() => {
                                  const text = mcpCallResult.error ?? mcpCallResult.result ?? ''
                                  setInput(prev => prev + (prev ? '\n\n' : '') + `MCP Result (${tool.name}):\n${text}`)
                                  setActivePanel(null)
                                }}>
                                  ↑ Inject into chat
                                </button>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        </aside>
      )}

      {/* ── YOO Builder Panel ─────────────────────────────────────── */}
      {activePanel === 'yoo' && (
        <YooBuilderPanel onClose={() => setActivePanel(null)} />
      )}

      {/* ── Main ─────────────────────────────────────────────────── */}
      <main className="main">

        {/* Top bar */}
        <div className="topbar">
          <div className="topbar-left">
            <span className="topbar-title">
              {activeThread ? activeThread.title : 'New thread'}
            </span>
            <span className="topbar-version">v{version}</span>
            {selectedAgent && (
              <span className="topbar-agent-badge" style={{ '--hue': CLUSTER_HUE[selectedAgent.cluster] ?? 262 } as React.CSSProperties}>
                <span>{selectedAgent.coord}</span>
                <span>{selectedAgent.name}</span>
                <button id="btn-clear-agent" className="topbar-agent-clear" onClick={clearSelectedAgent}>×</button>
              </span>
            )}
          </div>
          <div className="topbar-right">
            {activeProject && (
              <button id="btn-files" className={`topbar-btn files-btn ${showFiles ? 'active' : ''}`}
                onClick={() => setShowFiles(s => !s)} title="File explorer">
                📁 Files
              </button>
            )}
            {activeProject?.git && gitStatus?.is_repo && (
              <>
                {hasChanges && (
                  <span className="diff-stats">
                    {gitStats!.added > 0 && <span className="diff-add">+{gitStats!.added}</span>}
                    {gitStats!.removed > 0 && <span className="diff-rem">-{gitStats!.removed}</span>}
                  </span>
                )}
                <div className="commit-wrap">
                  <button id="btn-commit" className="topbar-btn commit-btn" onClick={() => setShowCommit(s => !s)}>
                    ⎇ Commit
                  </button>
                  {showCommit && (
                    <div className="commit-popover">
                      <input id="commit-msg-input" className="commit-input" placeholder="Commit message..."
                        value={commitMsg} onChange={e => setCommitMsg(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && doCommit()} autoFocus />
                      <button id="btn-do-commit" className="commit-go" onClick={doCommit}
                        disabled={commitLoading || !commitMsg.trim()}>
                        {commitLoading ? '...' : 'Commit'}
                      </button>
                    </div>
                  )}
                </div>
              </>
            )}
            {activeProject && (
              <div className="project-selector">
                <span className="project-selector-icon">📁</span>
                <span className="project-selector-name">{activeProject.name}</span>
                <span className="project-selector-caret">⌄</span>
                <div className="project-dropdown">
                  {projects.map(p => (
                    <button key={p.id} id={`select-project-${p.id}`}
                      className={`pd-item ${activeProject.id === p.id ? 'active' : ''}`}
                      onClick={() => setActiveProject(p)}>
                      {p.name}
                    </button>
                  ))}
                  <div className="pd-divider" />
                  <button id="btn-add-project-dd" className="pd-item" onClick={() => setShowAddProject(true)}>+ Add project</button>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Conversation */}
        <div className="conversation">
          {!activeProject ? (
            <div className="empty-state">
              <div className="empty-orb">
                <div className="empty-orb-inner">⬡</div>
              </div>
              <div className="empty-title">Open Codex</div>
              <div className="empty-version">SLM-v3 · Sovereign Liquid Matrix · v{version}</div>
              <div className="empty-sub">Select or add a project folder to initiate agentic operations.</div>
              <button id="btn-empty-add" className="empty-add-btn" onClick={() => setShowAddProject(true)}>
                + Add a project
              </button>
            </div>
          ) : !activeThread || activeThread.messages.length === 0 ? (
            <div className="empty-state">
              <div className="empty-orb">
                <div className="empty-orb-inner">◉</div>
              </div>
              <div className="empty-title">Ready to build</div>
              <div className="empty-project-name">
                {activeProject.name}
                {gitStatus?.is_repo && gitStatus.branch && (
                  <span className="empty-branch"> ⎇ {gitStatus.branch}</span>
                )}
              </div>
              {selectedAgent && (
                <div className="empty-agent-active" style={{ '--hue': CLUSTER_HUE[selectedAgent.cluster] ?? 262 } as React.CSSProperties}>
                  <span className="eaa-coord">{selectedAgent.coord}</span>
                  <span className="eaa-name">{selectedAgent.name}</span>
                  <span className="eaa-tag">{selectedAgent.brilliance}</span>
                </div>
              )}
              <div className="suggestions">
                {SUGGESTIONS.map(s => (
                  <button key={s.label} id={`suggest-${s.label.replace(/\s/g, '-').toLowerCase()}`}
                    className="suggestion-chip"
                    onClick={() => { setInput(s.label); inputRef.current?.focus() }}>
                    <span className="suggestion-icon">{s.icon}</span>
                    {s.label}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <>
              {activeThread.messages.map(msg => (
                <div key={msg.id} className={`message ${msg.role}`}>
                  {msg.role === 'user' ? (
                    <div className="user-msg-row">
                      <button
                        className="msg-del-btn"
                        title="Delete message"
                        onClick={() => deleteMessage(activeThreadId!, msg.id)}
                      >
                        🗑
                      </button>
                      <div className="user-bubble">
                        {msg.slmRole && (
                          <div className="user-role-tag">via {msg.slmRole}</div>
                        )}
                        {msg.content}
                      </div>
                    </div>
                  ) : (
                    <div className="assistant-msg-row">
                      <div className="assistant-bubble">
                        {/* Agent events */}
                        {(msg.events.length > 0 || !msg.done) && (
                          <details className="steps-group">
                            <summary className="steps-summary">
                              {!msg.done ? (
                                <>
                                  <span className="thinking-spinner steps-spinner" />
                                  <span className="steps-label">Working…</span>
                                </>
                              ) : (
                                <>
                                  <span className="steps-chevron">▶</span>
                                  <span className="steps-label">
                                    {msg.events.filter(e => e.type === 'tool_call').length} steps
                                  </span>
                                  {msg.events.filter(e => e.type === 'file_changed').length > 0 && (
                                    <span className="steps-files">
                                      · {msg.events.filter(e => e.type === 'file_changed').length} file{msg.events.filter(e => e.type === 'file_changed').length !== 1 ? 's' : ''} changed
                                    </span>
                                  )}
                                </>
                              )}
                            </summary>
                            <div className="steps-content">
                              {msg.events.map((ev, i) => renderEvent(ev, i))}
                            </div>
                          </details>
                        )}
                        {/* Final message */}
                        {msg.content && (
                          <div className="assistant-text-wrap">
                            <div className="assistant-text">{msg.content}</div>
                            <button id={`copy-${msg.id}`} className="copy-btn-bubble"
                              onClick={() => navigator.clipboard.writeText(msg.content)}>Copy</button>
                          </div>
                        )}
                        {/* Done stats */}
                        {msg.done && msg.stats && msg.stats.files_changed.length > 0 && (
                          <div className="done-stats">
                            <span className="done-label">Changed</span>
                            {msg.stats.files_changed.map(f => (
                              <span key={f} className="done-file">{f}</span>
                            ))}
                            {(msg.stats.added ?? 0) + (msg.stats.removed ?? 0) > 0 && (
                              <span className="done-diff">
                                <span className="diff-add">+{msg.stats.added ?? 0}</span>
                                <span className="diff-rem">-{msg.stats.removed ?? 0}</span>
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                      <button
                        className={`msg-del-btn${!msg.done ? ' kill' : ''}`}
                        title={!msg.done ? 'Kill & remove' : 'Delete message'}
                        onClick={() => deleteMessage(activeThreadId!, msg.id)}
                      >
                        {!msg.done ? '⏹' : '🗑'}
                      </button>
                    </div>
                  )}
                </div>
              ))}
              <div ref={bottomRef} />
            </>
          )}
        </div>

        {/* Input bar */}
        {activeProject && (
          <div className="input-bar">
            {selectedAgent && (
              <div className="input-role-banner" style={{ '--hue': CLUSTER_HUE[selectedAgent.cluster] ?? 262 } as React.CSSProperties}>
                <span className="irb-icon">⬡</span>
                <span className="irb-coord">{selectedAgent.coord}</span>
                <span className="irb-name">{selectedAgent.name}</span>
                <span className="irb-tag">{selectedAgent.brilliance}</span>
                <button id="btn-clear-role" className="irb-clear" onClick={clearSelectedAgent}>✕</button>
              </div>
            )}
            <div className="input-wrap">
              <textarea
                ref={inputRef}
                id="chat-input"
                className="input-ta"
                placeholder={selectedAgent
                  ? `Ask ${selectedAgent.name} about ${activeProject.name}…`
                  : `Ask Codex about ${activeProject.name} — / for commands, ⬡ for agent matrix`}
                value={input}
                onChange={onInputChange}
                onKeyDown={onKey}
                rows={1}
                disabled={streaming}
                spellCheck={false}
              />
              <div className="input-actions">
                {streaming ? (
                  <button id="btn-abort" className="abort-btn" onClick={abortStream} title="Stop generation">
                    ⏹
                  </button>
                ) : (
                  <button id="btn-send"
                    className={`send-btn ${(!input.trim() || streaming) ? 'disabled' : ''}`}
                    onClick={() => sendMessage()}
                    disabled={!input.trim() || streaming}>
                    ↑
                  </button>
                )}
              </div>
            </div>

            <div className="input-footer">
              <div className="footer-left">
                <button id="btn-footer-model" className="footer-model" onClick={() => { setShowSettings(s => !s); setActivePanel(null) }}>
                  ◆ {AGENT_LABELS[agentType]}{model ? ` · ${model.split(':')[0]}` : ''}
                </button>
                <button id="btn-footer-matrix" className="footer-matrix-btn" onClick={() => togglePanel('matrix')}>
                  ⬡ Matrix
                </button>
              </div>
              <div className="footer-right">
                <div className="mode-tabs">
                  {(['local', 'worktree', 'cloud'] as Mode[]).map(m => (
                    <button key={m} id={`mode-${m}`} className={`mode-tab ${mode === m ? 'active' : ''}`}
                      onClick={() => setMode(m)}>
                      {m.charAt(0).toUpperCase() + m.slice(1)}
                    </button>
                  ))}
                </div>
                {gitStatus?.is_repo && gitStatus.branch && (
                  <span className="footer-branch">⎇ {gitStatus.branch}</span>
                )}
              </div>
            </div>
          </div>
        )}

      </main>

      {/* ── File Panel ──────────────────────────────────────────────── */}
      {showFiles && activeProject && (
        <aside className="file-panel">
          <div className="fp-header">
            <span className="fp-title">📁 {activeProject.name}</span>
            <button id="btn-close-files" className="fp-close" onClick={() => { setShowFiles(false); setOpenedFile(null) }}>✕</button>
          </div>

          <div className="fp-body">
            <div className="fp-tree">
              {fileTreeLoading ? (
                <div className="fp-loading">Loading…</div>
              ) : fileTree.length === 0 ? (
                <div className="fp-loading">No files found.</div>
              ) : (
                fileTree.map(n => renderFileNode(n))
              )}
            </div>

            {openedFile && (
              <div className="fp-viewer">
                <div className="fp-viewer-header">
                  <span className="fp-viewer-path">{openedFile.path.split('/').pop()}</span>
                  <button id="btn-copy-file" className="fp-viewer-copy"
                    onClick={() => navigator.clipboard.writeText(openedFile.content)}>Copy</button>
                  <button id="btn-close-file" className="fp-viewer-close" onClick={() => setOpenedFile(null)}>✕</button>
                </div>
                <pre className="fp-viewer-pre">{openedFile.content}</pre>
              </div>
            )}
          </div>
        </aside>
      )}

    </div>
  )
}

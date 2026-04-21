import { useState, useEffect, useRef, useCallback } from 'react'

// ── Panel resize hook ─────────────────────────────────────────────────────────
function usePanelResize(
  ref: React.RefObject<HTMLElement | null>,
  axis: 'x',
  min: number,
  max: number,
  initial: number,
) {
  const [size, setSize] = useState(initial)
  const dragging = useRef(false)
  const startX   = useRef(0)
  const startW   = useRef(initial)

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    dragging.current = true
    startX.current   = e.clientX
    startW.current   = ref.current ? ref.current.getBoundingClientRect().width : size
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }, [ref, size])

  useEffect(() => {
    function onMove(e: MouseEvent) {
      if (!dragging.current) return
      const delta = e.clientX - startX.current
      setSize(Math.min(max, Math.max(min, startW.current + delta)))
    }
    function onUp() {
      if (!dragging.current) return
      dragging.current = false
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [])

  return { size, onMouseDown }
}
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

type AgentType = 'lmstudio' | 'ollama' | 'ollama_cloud' | 'gemini' | 'huggingface'
  | 'claude_code' | 'gemini_cli' | 'codex' | 'openclaw' | 'gym_instructor'
type Mode = 'local' | 'worktree' | 'cloud'
type Panel = 'matrix' | 'phases' | 'health' | 'automations' | 'browser' | 'mcp' | 'yoo' | 'gym' | null

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
  removable: boolean
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
       | 'gym_agent_forged'
       | 'team_decomposing' | 'team_plan' | 'team_plan_extend' | 'team_start' | 'team_done'
       | 'team_collab' | 'team_finish'
  content?: string
  tool?: string
  args?: Record<string, unknown>
  result?: string
  path?: string
  stats?: { files_changed: string[]; added?: number; removed?: number; team_mode?: boolean }
  prompt?: string
  stream_id?: string
  agent?: Record<string, string>
  // team events
  agent_id?: string
  role?: string
  subtask?: string
  files_hint?: string[]
  tasks?: { id: string; subtask: string; files_hint?: string[] }[]
  collaborate?: { after: string[]; synthesizer: string; task: string }[]
  synthesizer?: string
  inputs?: string[]
  msg?: string
  summary?: string
  task?: string
  new_agents?: [string, string][]
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

interface SlashCmd {
  cmd: string
  desc: string
  hasArgs: boolean
}

const SLASH_COMMANDS: SlashCmd[] = [
  { cmd: '/help',   desc: 'Show available commands',                hasArgs: false },
  { cmd: '/status', desc: 'Show git status',                        hasArgs: false },
  { cmd: '/log',    desc: 'Show recent commits — /log [n]',         hasArgs: true  },
  { cmd: '/diff',   desc: 'Show unstaged diff',                     hasArgs: false },
  { cmd: '/commit', desc: 'Commit all changes — /commit <message>', hasArgs: true  },
  { cmd: '/push',   desc: 'Push branch to remote origin',           hasArgs: false },
  { cmd: '/pull',   desc: 'Pull latest from remote',                hasArgs: false },
  { cmd: '/clear',  desc: 'Clear current thread',                   hasArgs: false },
  { cmd: '/phase',  desc: 'Launch a phase — /phase <1-6 | all>',    hasArgs: true  },
  { cmd: '/agent',  desc: 'Activate an agent — /agent <name>',      hasArgs: true  },
  { cmd: '/auto',   desc: 'Run automation — /auto <name>',           hasArgs: true  },
]

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
  lmstudio:      'LM Studio',
  ollama:        'Ollama',
  ollama_cloud:  'Ollama Cloud',
  gemini:        'Gemini',
  huggingface:   'HuggingFace',
  claude_code:   'Claude Code',
  gemini_cli:    'Gemini CLI',
  codex:         'Codex',
  openclaw:      'OpenClaw',
  gym_instructor:'Gym Instructor',
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

// ── SwarmGrid — live per-agent team panel ─────────────────────────────────────

const AGENT_HUE: Record<string, number> = {
  ARC: 210, LNG: 160, QSP: 16, OPS: 44, AID: 285,
}

interface AgentCardState {
  id: string
  role: string
  subtask: string
  status: 'waiting' | 'active' | 'done' | 'error'
  activity: string
  lastTool: string | null
  filesChanged: string[]
  steps: number
}

function SwarmGrid({ events, running }: { events: AgentEvent[]; running: boolean }) {
  // Build initial agent roster from team_plan tasks if available,
  // otherwise fall back to team_start events (terminal agent path)
  const plan = events.find(e => e.type === 'team_plan')
  const hasAnyTeamEvent = events.some(e => e.type === 'team_start' || e.type === 'team_plan')
  if (!hasAnyTeamEvent) return null

  const agents: Record<string, AgentCardState> = {}
  if (plan?.tasks) {
    for (const t of plan.tasks) {
      agents[t.id] = {
        id: t.id, role: '', subtask: t.subtask,
        status: 'waiting', activity: '', lastTool: null,
        filesChanged: [], steps: 0,
      }
    }
  }

  for (const ev of events) {
    const aid = ev.agent_id
    if (!aid || aid.endsWith('_SYNTH')) continue
    const a = agents[aid]
    if (!a) continue
    if (ev.type === 'team_start') {
      // upsert — terminal agents announce agents via team_start without a prior plan
      if (!agents[aid]) {
        agents[aid] = { id: aid, role: ev.role ?? aid, subtask: ev.subtask ?? ev.role ?? '',
                        status: 'waiting', activity: '', lastTool: null, filesChanged: [], steps: 0 }
      }
      agents[aid].status = 'active'
      if (ev.role) agents[aid].role = ev.role
      if (ev.subtask) agents[aid].subtask = ev.subtask
    }
    if (ev.type === 'thinking_text' && ev.content) a.activity = ev.content.slice(0, 90)
    if (ev.type === 'tool_call')     { a.lastTool = ev.tool ?? null; a.steps++ }
    if (ev.type === 'file_changed' && ev.path && !a.filesChanged.includes(ev.path))
      a.filesChanged.push(ev.path)
    if (ev.type === 'team_done')     a.status = 'done'
    if (ev.type === 'error')         { a.status = 'error'; if (ev.content) a.activity = ev.content.slice(0, 90) }
  }

  const agentList = Object.values(agents)
  const collabs = events.filter(e => e.type === 'team_collab')
  const finished = events.some(e => e.type === 'team_finish')
  const totalFiles = agentList.reduce((s, a) => s + a.filesChanged.length, 0)

  return (
    <div className="swarm-grid">
      {/* Agent cards */}
      {agentList.map(a => {
        const hue = AGENT_HUE[a.id] ?? 262
        return (
          <div
            key={a.id}
            className={`swarm-card swarm-card--${a.status}`}
            style={{ '--card-hue': hue } as React.CSSProperties}
          >
            <div className="swarm-card-head">
              <span className="swarm-badge">{a.id}</span>
              <span className="swarm-role">{a.role || a.subtask.split(' ').slice(0, 4).join(' ') + '…'}</span>
              <span className="swarm-status-dot">
                {a.status === 'active'   && <span className="swarm-spinner" />}
                {a.status === 'done'     && <span className="swarm-check">✓</span>}
                {a.status === 'error'    && <span className="swarm-x">✗</span>}
                {a.status === 'waiting'  && <span className="swarm-idle">·</span>}
              </span>
            </div>
            <div className="swarm-subtask">{a.subtask}</div>
            <div className="swarm-activity">
              {a.activity
                ? a.activity
                : a.status === 'waiting' ? 'Queued…'
                : a.status === 'active'  ? 'Working…'
                : ''}
            </div>
            {a.lastTool && a.status === 'active' && (
              <div className="swarm-tool-line">⚙ {a.lastTool}</div>
            )}
            <div className="swarm-card-foot">
              {a.steps > 0 && <span className="swarm-steps">{a.steps} step{a.steps !== 1 ? 's' : ''}</span>}
              {a.filesChanged.length > 0 && (
                <span className="swarm-file-count">✏ {a.filesChanged.length}</span>
              )}
            </div>
          </div>
        )
      })}

      {/* Synthesis cards */}
      {collabs.map((e, i) => {
        const synthId = e.synthesizer + '_SYNTH'
        const synthActivity = events
          .filter(ev => ev.agent_id === synthId && ev.type === 'thinking_text')
          .slice(-1)[0]?.content ?? ''
        const synthDone = events.some(ev => ev.agent_id === synthId && ev.type === 'message')
        return (
          <div key={`synth-${i}`} className={`swarm-card swarm-card--synth${synthDone ? ' swarm-card--done' : ' swarm-card--active'}`}>
            <div className="swarm-card-head">
              <span className="swarm-badge swarm-badge--synth">{e.synthesizer}</span>
              <span className="swarm-role">Synthesis</span>
              {!synthDone && <span className="swarm-spinner" />}
              {synthDone && <span className="swarm-check">✓</span>}
            </div>
            <div className="swarm-subtask">{e.task}</div>
            {synthActivity && <div className="swarm-activity">{synthActivity.slice(0, 90)}</div>}
            <div className="swarm-synth-inputs">from: {e.inputs?.join(', ')}</div>
          </div>
        )
      })}

      {/* Finish banner */}
      {finished && (
        <div className="swarm-finish">
          <span className="swarm-finish-icon">⬡</span>
          <span className="swarm-finish-label">Swarm complete</span>
          {totalFiles > 0 && <span className="swarm-finish-stat">· {totalFiles} file{totalFiles !== 1 ? 's' : ''} changed</span>}
        </div>
      )}

      {/* Live decomposing state before plan arrives */}
      {running && !finished && agentList.every(a => a.status === 'waiting') && (
        <div className="swarm-decomposing">
          <span className="swarm-spinner" /> Distributing tasks across matrix nodes…
        </div>
      )}
    </div>
  )
}

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  // Projects
  const [projects, setProjects] = useState<Project[]>([])
  const [activeProject, setActiveProject] = useState<Project | null>(null)

  // Agent configuration
  const [maxSteps, setMaxSteps] = useState<number>(() => store('oc_max_steps', 25))

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
  const [teamMode, setTeamMode] = useState<boolean>(() => store('oc_team_mode', false))
  const [showSettings, setShowSettings] = useState(false)
  const [addProjectInput, setAddProjectInput] = useState('')
  const [showAddProject, setShowAddProject] = useState(false)

  // Active panel
  const [activePanel, setActivePanel] = useState<Panel>(null)

  // Theme
  type Theme = 'void' | 'slate' | 'ember' | 'light'
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem('ocdx-theme') as Theme) ?? 'void'
  )

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
  const [browserTaskInput, setBrowserTaskInput] = useState('')
  const [browserPriorContext, setBrowserPriorContext] = useState<string | null>(null)
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
  const [phaseRunStatus, setPhaseRunStatus] = useState<Record<string, 'idle' | 'running' | 'done'>>({})
  const [phaseAllRunning, setPhaseAllRunning] = useState(false)
  const phaseAllCancelRef = useRef(false)

  // Automations
  const [autoSearch, setAutoSearch] = useState('')

  // Provider Health
  const [health, setHealth] = useState<Record<string, ProviderHealth>>({})
  const [healthLoading, setHealthLoading] = useState<Record<string, boolean>>({})

  // Terminal agent detection (Claude Code, Gemini CLI, Codex, OpenClaw)
  const [terminalAgents, setTerminalAgents] = useState<TerminalAgentInfo[]>([])

  // Gym
  const [gymTab, setGymTab] = useState<'chat' | 'agents' | 'clusters' | 'scenarios' | 'secrets' | 'autopilot'>('chat')
  const [gymInput, setGymInput] = useState('')
  const [gymStreaming, setGymStreaming] = useState(false)
  const [gymStreamId, setGymStreamId] = useState<string | null>(null)
  const [gymMessages, setGymMessages] = useState<{ role: 'user' | 'assistant'; content: string; events: AgentEvent[]; done: boolean }[]>([])
  const [gymAgents, setGymAgents] = useState<SLMAgent[]>([])
  const [gymClusters, setGymClusters] = useState<{ name: string; description: string; agents: string[]; created_at: string }[]>([])
  const [gymScenarios, setGymScenarios] = useState<{ id: string; agent_keyword: string; name: string; prompt: string; expected: string; created_at: string }[]>([])
  const [gymForgedFlash, setGymForgedFlash] = useState<string | null>(null)
  const gymBottomRef = useRef<HTMLDivElement>(null)

  // CryptKeeper (.env manager)
  const [ckKeys,    setCkKeys]    = useState<string[]>([])
  const [ckReqs,    setCkReqs]    = useState<any[]>([])
  const [ckName,    setCkName]    = useState('')
  const [ckValue,   setCkValue]   = useState('')
  const [ckMasked,  setCkMasked]  = useState(true)
  const [ckLoading, setCkLoading] = useState(false)

  // Repos→MCP state
  const [repoList,    setRepoList]    = useState<any[]>([])
  const [repoUrl,     setRepoUrl]     = useState('')
  const [repoName,    setRepoName]    = useState('')
  const [repoToken,   setRepoToken]   = useState('')
  const [repoBranch,  setRepoBranch]  = useState('')
  const [repoLoading, setRepoLoading] = useState(false)
  const [repoError,   setRepoError]   = useState<string | null>(null)

  // Auto-MCPilot
  const [pilotEnabled,  setPilotEnabled]  = useState(false)
  const [pilotInterval, setPilotInterval] = useState(10)
  const [pilotStatus,   setPilotStatus]   = useState<any>(null)
  const [pilotLog,      setPilotLog]      = useState<any[]>([])
  const [pilotRunning,  setPilotRunning]  = useState(false)

  // Git
  const [gitStatus, setGitStatus] = useState<GitStatus | null>(null)
  const [gitStats, setGitStats] = useState<{ added: number; removed: number } | null>(null)
  const [showCommit, setShowCommit] = useState(false)
  const [commitMsg, setCommitMsg] = useState('')
  const [commitLoading, setCommitLoading] = useState(false)
  const [gitOpLoading, setGitOpLoading] = useState<'push' | 'pull' | null>(null)

  // Slash command menu
  const [slashMenuOpen, setSlashMenuOpen] = useState(false)
  const [slashMenuIdx, setSlashMenuIdx] = useState(0)

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
  useEffect(() => { storeSet('oc_team_mode', teamMode) }, [teamMode])
  useEffect(() => { storeSet('oc_model', model) }, [model])
  useEffect(() => { storeSet('oc_apikey', apiKey) }, [apiKey])
  useEffect(() => { storeSet('oc_geminikey', geminiApiKey) }, [geminiApiKey])
  useEffect(() => { storeSet('oc_lmhost', lmHost) }, [lmHost])
  useEffect(() => { storeSet('oc_ollamahost', ollamaHost) }, [ollamaHost])
  useEffect(() => { storeSet('oc_max_steps', maxSteps) }, [maxSteps])

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

    // Load Gym roster
    loadGymData()

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

  // Gym scroll
  useEffect(() => {
    if (gymBottomRef.current) {
      gymBottomRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [gymMessages.length])

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
      const host = agentType === 'lmstudio' ? lmHost
        : agentType === 'ollama_cloud' ? 'https://ollama.com'
        : ollamaHost
      const r = await fetch(`/api/models?source=${agentType}&host=${encodeURIComponent(host)}`)
      const d = await r.json()
      setModels(d.models ?? [])
    } catch { setModels([]) }
    finally { setModelsLoading(false) }
  }, [agentType, lmHost, ollamaHost])

  useEffect(() => { fetchModels() }, [fetchModels])

  // ── Browser log auto-scroll ───────────────────────────────────────────────
  useEffect(() => {
    if (browserLogRef.current) {
      browserLogRef.current.scrollTop = browserLogRef.current.scrollHeight
    }
  }, [browserLogs.length])

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
      ['lmstudio', 'ollama', 'ollama_cloud', 'gemini', 'huggingface'].forEach(p => checkHealth(p))
    }
  }, [activePanel])

  // Apply theme to <html> element ───────────────────────────────────────────
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('ocdx-theme', theme)
  }, [theme])

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
  async function launchPhase(phase: SLMPhase, opts: { closePanel?: boolean } = {}) {
    if (!activeProject) { alert('Select a project first'); return }
    if (opts.closePanel !== false) setActivePanel(null)
    setPhaseRunStatus(prev => ({ ...prev, [phase.id]: 'running' }))
    try {
      await sendMessage(phase.prompt)
    } finally {
      setPhaseRunStatus(prev => ({ ...prev, [phase.id]: 'done' }))
    }
  }

  async function launchAllPhases() {
    if (!activeProject) { alert('Select a project first'); return }
    if (phaseAllRunning) { phaseAllCancelRef.current = true; return }
    setPhaseAllRunning(true)
    setPhaseRunStatus({})
    phaseAllCancelRef.current = false
    for (const phase of slmPhases) {
      if (phaseAllCancelRef.current) break
      await launchPhase(phase, { closePanel: false })
    }
    setPhaseAllRunning(false)
    phaseAllCancelRef.current = false
  }

  // ── Slash menu computed values ────────────────────────────────────────────
  const slashMenuCommands = (() => {
    if (!slashMenuOpen) return []
    const typed = input.match(/^\/(\w*)$/)?.[1] ?? ''
    return SLASH_COMMANDS.filter(c => c.cmd.slice(1).startsWith(typed))
  })()

  function handleSlashSelect(sc: SlashCmd) {
    setSlashMenuOpen(false)
    if (sc.hasArgs) {
      setInput(sc.cmd + ' ')
      setTimeout(() => inputRef.current?.focus(), 0)
    } else {
      setInput(sc.cmd)
      setTimeout(() => sendMessage(sc.cmd), 0)
    }
  }

  // ── Send message ──────────────────────────────────────────────────────────
  async function sendMessage(overrideText?: string) {
    const text = (overrideText ?? input).trim()
    if (!text || streaming || !activeProject) return
    setSlashMenuOpen(false)

    // Intercept slash commands
    if (text.startsWith('/') && !text.startsWith('[/')) {
      const spaceIdx = text.indexOf(' ')
      const cmd = (spaceIdx === -1 ? text : text.slice(0, spaceIdx)).toLowerCase()
      const args = spaceIdx === -1 ? '' : text.slice(spaceIdx + 1)
      if (SLASH_COMMANDS.some(c => c.cmd === cmd)) {
        setInput('')
        await executeSlashCommand(cmd, args)
        return
      }
    }

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
          max_steps: maxSteps,
          host,
          api_key: agentType === 'ollama_cloud' ? apiKey || undefined
                 : agentType === 'gemini' ? geminiApiKey || undefined
                 : undefined,
          thread_id: tid,
          slm_context: slmContext,
          team_mode: teamMode,
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
              content: ev.type === 'message'
                ? ev.content ?? m.content
                : ev.type === 'team_finish'
                  ? (ev.summary ?? m.content)
                  : m.content,
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

  // ── Commit / Push / Pull ──────────────────────────────────────────────────
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

  async function doPush() {
    if (!activeProject) return
    setGitOpLoading('push')
    try {
      const r = await fetch('/api/git/push', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_dir: activeProject.path }),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail || d.output || 'Push failed')
      setShowCommit(false)
      refreshGit()
    } catch (e) { alert(String(e)) }
    finally { setGitOpLoading(null) }
  }

  async function doPull() {
    if (!activeProject) return
    setGitOpLoading('pull')
    try {
      const r = await fetch('/api/git/pull', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_dir: activeProject.path }),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail || d.output || 'Pull failed')
      setShowCommit(false)
      refreshGit()
    } catch (e) { alert(String(e)) }
    finally { setGitOpLoading(null) }
  }

  // ── Browser Agent ─────────────────────────────────────────────────────────
  async function runBrowserTask() {
    if (!browserTaskInput.trim() || browserRunning) return
    setBrowserRunning(true)
    setBrowserFrame(null)
    setBrowserLogs([])
    setBrowserDone(null)
    setBrowserStep(0)
    setBrowserTitle('')
    setBrowserSessionId(null)

    try {
      const TERMINAL_TYPES = new Set(['claude_code', 'gemini_cli', 'codex', 'openclaw', 'gym_instructor'])
      const host = agentType === 'lmstudio' ? lmHost
        : agentType === 'ollama' ? ollamaHost
        : agentType === 'ollama_cloud' ? undefined
        : TERMINAL_TYPES.has(agentType) ? ollamaHost   // fallback host for terminal types
        : undefined
      const api_key = agentType === 'ollama_cloud' ? apiKey || undefined
        : agentType === 'gemini' ? geminiApiKey || undefined
        : agentType === 'gemini_cli' ? geminiApiKey || undefined  // gemini_cli uses Gemini key
        : undefined
      const res = await fetch('/api/browser/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task: browserTaskInput,
          agent_type: agentType,
          model: model || null,
          host,
          api_key,
          start_url: browserUrl || null,
          headless: false,
          project_dir: activeProject?.path || null,
          prior_context: browserPriorContext || null,
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
          let ev: BrowserEvent
          try { ev = JSON.parse(part.slice(6)) } catch { continue }

          if (ev.type === 'session_id' && ev.session_id) {
            setBrowserSessionId(ev.session_id)
          } else if (ev.type === 'frame') {
            if (ev.png) setBrowserFrame(ev.png)
            if (ev.mime) setBrowserFrameMime(ev.mime)
            if (ev.url) setBrowserUrl(ev.url)
            if (ev.title) setBrowserTitle(ev.title)
            if (ev.step !== undefined) setBrowserStep(ev.step ?? 0)
            setBrowserLogs(prev => [...prev, ev])
          } else if (ev.type === 'log') {
            setBrowserLogs(prev => [...prev, ev])
          } else if (ev.type === 'done') {
            const summary = ev.summary ?? ev.content ?? 'Task completed.'
            setBrowserDone(summary)
            setBrowserPriorContext(summary)
          } else if (ev.type === 'error') {
            setBrowserLogs(prev => [...prev, ev])
          }
        }
      }
    } catch (e) {
      setBrowserLogs(prev => [...prev, { type: 'error', message: String(e) }])
    } finally {
      setBrowserRunning(false)
    }
  }

  async function abortBrowser() {
    if (!browserSessionId) { setBrowserRunning(false); return }
    try { await fetch(`/api/browser/abort/${browserSessionId}`, { method: 'POST' }) } catch {}
    setBrowserRunning(false)
  }

  // ── Gym helpers ───────────────────────────────────────────────────────────
  async function loadGymData() {
    try {
      const [ag, cl, sc] = await Promise.all([
        fetch('/api/gym/agents').then(r => r.json()),
        fetch('/api/gym/clusters').then(r => r.json()),
        fetch('/api/gym/scenarios').then(r => r.json()),
      ])
      setGymAgents(ag.agents ?? [])
      setGymClusters(cl.clusters ?? [])
      setGymScenarios(sc.scenarios ?? [])
    } catch {}
  }

  async function loadCryptKeeper() {
    try {
      const [ek, er] = await Promise.all([
        fetch('/api/cryptkeeper/env').then(r => r.json()),
        fetch('/api/cryptkeeper/requests').then(r => r.json()),
      ])
      setCkKeys(ek.keys ?? [])
      setCkReqs(er.requests ?? [])
    } catch {}
  }

  async function ckStore() {
    if (!ckName.trim() || !ckValue.trim()) return
    setCkLoading(true)
    try {
      await fetch('/api/cryptkeeper/env', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: ckName.trim(), value: ckValue.trim() }),
      })
      setCkName(''); setCkValue('')
      await loadCryptKeeper()
    } finally { setCkLoading(false) }
  }

  async function ckDelete(name: string) {
    await fetch(`/api/cryptkeeper/env/${encodeURIComponent(name)}`, { method: 'DELETE' })
    await loadCryptKeeper()
  }

  async function ckDismiss(name: string) {
    await fetch(`/api/cryptkeeper/dismiss/${encodeURIComponent(name)}`, { method: 'POST' })
    await loadCryptKeeper()
  }

  async function ckDeny(name: string) {
    await fetch('/api/cryptkeeper/deny', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, reason: 'Use browser automation path instead' }),
    })
    await loadCryptKeeper()
  }

  async function ckApproveInline(name: string, value: string) {
    if (!value.trim()) return
    await fetch('/api/cryptkeeper/env', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, value: value.trim() }),
    })
    await loadCryptKeeper()
  }

  async function loadRepos() {
    try {
      const d = await fetch('/api/repos').then(r => r.json())
      setRepoList(d.repos ?? [])
    } catch {}
  }

  async function repoAdd() {
    const url = repoUrl.trim()
    if (!url) return
    setRepoLoading(true)
    setRepoError(null)
    try {
      const res = await fetch('/api/repos', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url,
          name:       repoName.trim() || undefined,
          auth_token: repoToken.trim() || undefined,
          branch:     repoBranch.trim() || undefined,
        }),
      })
      const d = await res.json()
      if (!res.ok) { setRepoError(d.detail ?? 'Failed'); return }
      setRepoUrl(''); setRepoName(''); setRepoToken(''); setRepoBranch('')
      await loadRepos()
      // Refresh MCP server list so new tools appear
      const ms = await fetch('/api/mcp/servers').then(r => r.json())
      setMcpServers(ms.servers ?? [])
      setMcpTotalTools(ms.total_tools ?? 0)
    } catch (e: unknown) {
      setRepoError(String(e))
    } finally {
      setRepoLoading(false)
    }
  }

  async function repoRemove(name: string) {
    await fetch(`/api/repos/${encodeURIComponent(name)}`, { method: 'DELETE' })
    await loadRepos()
    const ms = await fetch('/api/mcp/servers').then(r => r.json())
    setMcpServers(ms.servers ?? [])
    setMcpTotalTools(ms.total_tools ?? 0)
  }


  async function gymSendMessage() {
    const text = gymInput.trim()
    if (!text || gymStreaming || !activeProject) return
    setGymInput('')
    setGymMessages(prev => [
      ...prev,
      { role: 'user', content: text, events: [], done: true },
      { role: 'assistant', content: '', events: [], done: false },
    ])
    setGymStreaming(true)

    const msgIdx = gymMessages.length + 1 // index of assistant message

    try {
      const host = agentType === 'lmstudio' ? lmHost
        : agentType === 'ollama' ? ollamaHost
        : agentType === 'ollama_cloud' ? 'https://ollama.com'
        : undefined

      const res = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          project_dir: activeProject.path,
          agent_type: 'gym_instructor',
          model: model || null,
          host,
          api_key: agentType === 'ollama_cloud' ? apiKey || undefined
                 : agentType === 'gemini' ? geminiApiKey || undefined
                 : undefined,
          max_steps: maxSteps,
          // slm_context carries the underlying provider type for the Gym backend
          slm_context: ['lmstudio','ollama','ollama_cloud','gemini'].includes(agentType)
            ? agentType
            : 'ollama',
        }),
      })

      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const reader = res.body!.getReader()
      const decoder = new TextDecoder()
      let buf = ''
      let forged = false

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

          if (ev.type === 'stream_id' && ev.stream_id) { setGymStreamId(ev.stream_id); continue }
          if (ev.type === 'aborted') break

          // Live graduation flash
          if (ev.type === 'gym_agent_forged' && ev.agent) {
            forged = true
            setGymForgedFlash(`🎓 ${ev.agent.coord} — ${ev.agent.name}`)
            setTimeout(() => setGymForgedFlash(null), 4000)
          }

          setGymMessages(prev => {
            const msgs = [...prev]
            const last = msgs[msgs.length - 1]
            if (!last || last.role !== 'assistant') return prev
            const updated = { ...last, events: [...last.events, ev] }
            if (ev.type === 'message') updated.content = ev.content ?? last.content
            if (ev.type === 'done') updated.done = true
            msgs[msgs.length - 1] = updated
            return msgs
          })
        }
      }

      // If any agent was forged, refresh gym data + SLM matrix
      if (forged) {
        await loadGymData()
        const d = await fetch('/api/slm/agents').then(r => r.json())
        setSlmAgents(d.agents ?? [])
        setSlmClusters(d.clusters ?? {})
      }
    } catch (e) {
      setGymMessages(prev => {
        const msgs = [...prev]
        const last = msgs[msgs.length - 1]
        if (last && last.role === 'assistant') msgs[msgs.length - 1] = { ...last, content: `Error: ${String(e)}`, done: true }
        return msgs
      })
    } finally {
      setGymStreaming(false)
      setGymStreamId(null)
      void msgIdx // suppress unused var warning
    }
  }

  async function gymAbort() {
    if (!gymStreamId) return
    try { await fetch(`/api/chat/abort/${gymStreamId}`, { method: 'POST' }) } catch {}
    setGymStreaming(false)
    setGymStreamId(null)
  }

  // ── Local message injection (for slash command responses) ─────────────────
  function addLocalMessage(userText: string, assistantText: string) {
    let tid = activeThreadId
    let isNew = false
    if (!tid) {
      const newThread: Thread = { id: uid(), title: userText.slice(0, 50), messages: [], ts: Date.now() }
      setThreads(prev => [newThread, ...prev])
      setActiveThreadId(newThread.id)
      tid = newThread.id
      isNew = true
    }
    const userMsg: Message = { id: uid(), role: 'user', content: userText, events: [], done: true, ts: Date.now() }
    const asstMsg: Message = { id: uid(), role: 'assistant', content: assistantText, events: [], done: true, ts: Date.now() }
    setThreads(prev => prev.map(t => t.id === tid ? {
      ...t,
      title: isNew ? userText.slice(0, 50) : t.title,
      messages: [...t.messages, userMsg, asstMsg],
    } : t))
    setInput('')
  }

  // ── Slash command executor ────────────────────────────────────────────────
  async function executeSlashCommand(cmd: string, args: string): Promise<boolean> {
    if (!activeProject) return false
    const enc = encodeURIComponent(activeProject.path)

    switch (cmd) {
      case '/help': {
        const helpText = SLASH_COMMANDS.map(c => `**${c.cmd}** — ${c.desc}`).join('\n')
        addLocalMessage('/help', `Available slash commands:\n\n${helpText}`)
        return true
      }
      case '/status': {
        try {
          const d = await fetch(`/api/git/status?project=${enc}`).then(r => r.json())
          if (!d.is_repo) { addLocalMessage('/status', 'Not a git repository.'); return true }
          const lines = d.files.length === 0
            ? 'Working tree clean.'
            : d.files.map((f: { status: string; path: string }) => `  ${f.status}  ${f.path}`).join('\n')
          addLocalMessage('/status', `Branch: **${d.branch}**\n\`\`\`\n${lines}\n\`\`\``)
        } catch (e) { addLocalMessage('/status', `Error: ${String(e)}`) }
        return true
      }
      case '/log': {
        const n = parseInt(args) || 10
        try {
          const d = await fetch(`/api/git/log?project=${enc}&n=${n}`).then(r => r.json())
          const lines = (d.commits ?? []).map((c: { hash: string; subject: string; author: string; relative: string }) =>
            `\`${c.hash}\` ${c.subject} — ${c.author} (${c.relative})`
          ).join('\n')
          addLocalMessage(`/log${args ? ' ' + args : ''}`, lines || 'No commits found.')
        } catch (e) { addLocalMessage('/log', `Error: ${String(e)}`) }
        return true
      }
      case '/diff': {
        try {
          const d = await fetch(`/api/git/diff?project=${enc}`).then(r => r.json())
          addLocalMessage('/diff', `\`\`\`diff\n${d.diff}\n\`\`\``)
        } catch (e) { addLocalMessage('/diff', `Error: ${String(e)}`) }
        return true
      }
      case '/commit': {
        if (!args.trim()) { addLocalMessage('/commit', 'Usage: `/commit <message>`'); return true }
        try {
          const r = await fetch('/api/git/commit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_dir: activeProject.path, message: args }),
          })
          const d = await r.json()
          if (!r.ok) throw new Error(d.detail)
          addLocalMessage(`/commit ${args}`, `✓ Committed \`${d.hash}\`\n\n${d.output}`)
          refreshGit()
        } catch (e) { addLocalMessage(`/commit ${args}`, `✗ ${String(e)}`) }
        return true
      }
      case '/push': {
        try {
          const r = await fetch('/api/git/push', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_dir: activeProject.path }),
          })
          const d = await r.json()
          if (!r.ok) throw new Error(d.detail || d.output)
          addLocalMessage('/push', `✓ ${d.output || 'Push successful'}`)
          refreshGit()
        } catch (e) { addLocalMessage('/push', `✗ ${String(e)}`) }
        return true
      }
      case '/pull': {
        try {
          const r = await fetch('/api/git/pull', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ project_dir: activeProject.path }),
          })
          const d = await r.json()
          if (!r.ok) throw new Error(d.detail || d.output)
          addLocalMessage('/pull', `✓ ${d.output || 'Pull successful'}`)
          refreshGit()
        } catch (e) { addLocalMessage('/pull', `✗ ${String(e)}`) }
        return true
      }
      case '/clear': {
        if (!activeThread) return true
        const cleared = { ...activeThread, messages: [] }
        setThreads(prev => prev.map(t => t.id === cleared.id ? cleared : t))
        persistThread(cleared)
        setInput('')
        return true
      }
      case '/phase': {
        if (args.trim().toLowerCase() === 'all') {
          launchAllPhases()
          return true
        }
        const n = parseInt(args)
        const phase = slmPhases.find(p => p.phase_num === n)
        if (!phase) {
          addLocalMessage(`/phase ${args}`, `Phase "${args}" not found. Available: ${slmPhases.map(p => p.phase_num).join(', ')}, all`)
          return true
        }
        launchPhase(phase)
        return true
      }
      case '/auto': {
        const q = args.toLowerCase().trim()
        if (!q) {
          addLocalMessage('/auto', `Usage: \`/auto <name>\`\n\nAvailable: ${automations.slice(0,6).map(a=>a.name).join(', ')}…`)
          return true
        }
        const auto = automations.find(a =>
          a.name.toLowerCase().includes(q) || a.id.toLowerCase().includes(q)
        )
        if (!auto) {
          addLocalMessage(`/auto ${args}`, `No automation found matching "${args}". Try: ${automations.slice(0,5).map(a=>a.name).join(', ')}`)
          return true
        }
        if (auto.browser) {
          setBrowserTaskInput(auto.task_template ?? auto.description)
          if (auto.default_url) setBrowserUrl(auto.default_url)
          setActivePanel('browser')
        } else {
          setActivePanel(null)
          sendMessage(auto.task_template ?? auto.description)
        }
        return true
      }
      case '/agent': {
        if (!args.trim()) {
          addLocalMessage('/agent', `Usage: \`/agent <name or keyword>\`\n\nExample keywords: architect, security, frontend, backend`)
          return true
        }
        const q = args.toLowerCase()
        const found = slmAgents.find(a =>
          a.keyword.toLowerCase().includes(q) || a.name.toLowerCase().includes(q) || a.coord.toLowerCase() === q
        )
        if (!found) {
          addLocalMessage(`/agent ${args}`, `No agent found matching "${args}". Try a keyword like "architect", "security", "frontend", or "backend".`)
          return true
        }
        activateAgent(found)
        addLocalMessage(`/agent ${args}`, `✓ Activated **${found.name}** (${found.coord}) — ${found.brilliance}`)
        return true
      }
    }
    return false
  }

  // ── Key handler ───────────────────────────────────────────────────────────
  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (slashMenuOpen && slashMenuCommands.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setSlashMenuIdx(i => Math.min(i + 1, slashMenuCommands.length - 1))
        return
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setSlashMenuIdx(i => Math.max(i - 1, 0))
        return
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault()
        handleSlashSelect(slashMenuCommands[slashMenuIdx] ?? slashMenuCommands[0])
        return
      }
      if (e.key === 'Escape') {
        e.preventDefault()
        setSlashMenuOpen(false)
        return
      }
    }
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); sendMessage() }
    if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey) { e.preventDefault(); sendMessage() }
    if (e.key === 'Escape') { clearSelectedAgent(); setSlashMenuOpen(false) }
  }

  function onInputChange(e: ChangeEvent<HTMLTextAreaElement>) {
    const val = e.target.value
    setInput(val)
    e.target.style.height = 'auto'
    e.target.style.height = Math.min(e.target.scrollHeight, 200) + 'px'
    // Show slash menu only when user types exactly /word (no space yet)
    const isSlash = /^\/\w*$/.test(val)
    setSlashMenuOpen(isSlash)
    if (isSlash) setSlashMenuIdx(0)
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
      case 'tool_call': {
        const argStr = ev.args ? JSON.stringify(ev.args, null, 2) : null
        const argPreview = renderArgs(ev.tool, ev.args)
        return (
          <details key={i} className="ev-tool" open>
            <summary>
              <span className="ev-tool-icon">{toolIcon(ev.tool)}</span>
              <span className="ev-tool-name">{ev.tool}</span>
              {argPreview && <span className="ev-tool-args">{argPreview}</span>}
            </summary>
            {argStr && (
              <pre className="ev-tool-body">{argStr}</pre>
            )}
          </details>
        )
      }
      case 'tool_result':
        return (
          <details key={i} className="ev-result" open={!!ev.result && ev.result.length < 500}>
            <summary>
              <span className="ev-result-icon">◀</span>
              <span>Result{ev.tool ? ` · ${ev.tool}` : ''}</span>
              {ev.result && <span className="ev-result-len">{ev.result.length} chars</span>}
            </summary>
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
      case 'team_decomposing':
        return <div key={i} className="ev-team-decomposing">⬡ {ev.msg ?? 'Decomposing task across specialist agents…'}</div>
      case 'team_plan':
        return (
          <details key={i} className="ev-team-plan" open>
            <summary><span className="ev-team-icon">⬡</span> Swarm Plan — {ev.tasks?.length ?? 0} agents{(ev.collaborate?.length ?? 0) > 0 ? ` + ${ev.collaborate!.length} synthesis` : ''}</summary>
            <div className="ev-team-plan-tasks">
              {ev.tasks?.map(t => (
                <div key={t.id} className="ev-team-task-row">
                  <span className="ev-team-badge">{t.id}</span>
                  <span className="ev-team-subtask">{t.subtask}</span>
                  {t.files_hint && t.files_hint.length > 0 && <span className="ev-team-hint">{t.files_hint.join(', ')}</span>}
                </div>
              ))}
            </div>
          </details>
        )
      case 'team_start':
        return (
          <div key={i} className="ev-team-start">
            <span className="ev-team-badge ev-team-badge--active">{ev.agent_id}</span>
            <span className="ev-team-role">{ev.role}</span>
            <span className="ev-team-arrow">→</span>
            <span className="ev-team-subtask">{ev.subtask}</span>
          </div>
        )
      case 'team_done':
        return (
          <div key={i} className="ev-team-done">
            <span className="ev-team-badge ev-team-badge--done">{ev.agent_id}</span>
            <span className="ev-team-done-label">✓ done</span>
          </div>
        )
      case 'team_collab':
        return (
          <div key={i} className="ev-team-collab">
            <span className="ev-team-badge ev-team-badge--synth">{ev.synthesizer}</span>
            <span className="ev-team-synth-label">synthesis</span>
            <span className="ev-team-inputs">[{ev.inputs?.join(' + ')}]</span>
            <span className="ev-team-collab-task">{ev.task}</span>
          </div>
        )
      case 'team_finish':
        return (
          <div key={i} className="ev-team-finish">
            <span className="ev-team-finish-icon">⬡</span>
            <span className="ev-team-finish-label">Swarm complete</span>
            {ev.summary && <span className="ev-team-finish-summary">{ev.summary}</span>}
          </div>
        )
      case 'team_plan_extend':
        return (
          <div key={i} className="ev-team-extend">
            <span className="ev-team-icon">⬡</span>
            <span className="ev-team-extend-label">Activating {ev.new_agents?.length ?? 0} additional agent{(ev.new_agents?.length ?? 0) !== 1 ? 's' : ''}:</span>
            {ev.new_agents?.map(([coord]) => (
              <span key={coord} className="ev-team-badge ev-team-badge--active">{coord}</span>
            ))}
          </div>
        )
      default: return null
    }
  }

  function toolIcon(tool?: string) {
    const map: Record<string, string> = {
      // file ops
      list_directory: '📂', read_file: '📄', write_file: '✏️', create_file: '🆕',
      edit_file: '✏️', delete_file: '🗑️', move_file: '📦', copy_file: '📋',
      // search
      search_files: '🔍', grep: '🔍', find_files: '🔍', glob: '🔍',
      // execution
      run_command: '⚡', bash: '⚡', shell: '⚡', execute: '⚡',
      // web / network
      web_search: '🌐', web_fetch: '🌐', fetch: '🌐', http: '🌐',
      browser: '🌐', navigate: '🌐',
      // code / analysis
      analyze: '🔬', lint: '🔬', typecheck: '🔬',
      // git
      git: '⚛️', git_diff: '⚛️', git_log: '⚛️', git_commit: '⚛️',
      // data / AI
      think: '💭', plan: '📐', summarize: '📝',
      // agents
      dispatch_agent: '⬡', spawn: '⬡', delegate: '⬡',
      // claude code specific
      Read: '📄', Write: '✏️', Edit: '✏️', Bash: '⚡', Glob: '📂',
      Grep: '🔍', WebFetch: '🌐', WebSearch: '🌐', Agent: '⬡',
      Task: '📐', TodoWrite: '📝', TodoRead: '📝',
    }
    return tool ? (map[tool] ?? '🔧') : '🔧'
  }

  function renderArgs(tool?: string, args?: Record<string, unknown>): string {
    if (!args) return ''
    const t = tool?.toLowerCase() ?? ''
    if (t === 'write_file' || t === 'create_file' || t === 'edit_file'
        || t === 'read_file' || t === 'delete_file' || t === 'write' || t === 'read' || t === 'edit')
      return String(args.path ?? args.file_path ?? '')
    if (t === 'run_command' || t === 'bash' || t === 'shell' || t === 'execute')
      return String(args.command ?? args.cmd ?? '').slice(0, 120)
    if (t === 'search_files' || t === 'grep')
      return String(args.pattern ?? args.query ?? args.search ?? '').slice(0, 80)
    if (t === 'web_search' || t === 'websearch')
      return String(args.query ?? args.q ?? '').slice(0, 80)
    if (t === 'web_fetch' || t === 'webfetch' || t === 'fetch')
      return String(args.url ?? '').slice(0, 80)
    if (t === 'glob' || t === 'list_directory' || t === 'find_files')
      return String(args.pattern ?? args.path ?? '').slice(0, 80)
    if (t === 'agent' || t === 'dispatch_agent')
      return String(args.prompt ?? args.task ?? '').slice(0, 80)
    const first = Object.values(args)[0]
    return first ? String(first).slice(0, 80) : ''
  }

  const hasChanges = (gitStats?.added ?? 0) + (gitStats?.removed ?? 0) > 0

  // ── Panel toggles ─────────────────────────────────────────────────────────
  function togglePanel(p: Panel) {
    setActivePanel(prev => prev === p ? null : p)
    setShowSettings(false)
  }

  // ── Panel resizers ────────────────────────────────────────────────────────
  const sidebarRef = useRef<HTMLElement>(null)
  const panelRef   = useRef<HTMLElement>(null)
  const sidebar  = usePanelResize(sidebarRef, 'x', 180, 380, 256)
  const sidePanel = usePanelResize(panelRef,  'x', 280, 640, 380)

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="app">

      {/* ── Sidebar ───────────────────────────────────────────────── */}
      <aside className="sidebar" ref={sidebarRef as React.RefObject<HTMLElement>} style={{ width: sidebar.size, minWidth: sidebar.size }}>
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
          <button id="btn-automations" className={`sb-action ${activePanel === 'automations' ? 'active' : ''}`}
            onClick={() => togglePanel('automations')}>
            <span className="sb-action-icon">⚡</span> Automations
            {automations.length > 0 && <span className="sb-badge">{automations.length}</span>}
          </button>
          <button id="btn-browser" className={`sb-action ${activePanel === 'browser' ? 'active' : ''}`}
            onClick={() => togglePanel('browser')}>
            <span className="sb-action-icon">🌐</span> AI Browser
            {browserRunning && <span className="sb-badge browser-running-badge">●</span>}
          </button>
          <button id="btn-gym" className={`sb-action ${activePanel === 'gym' ? 'active' : ''}`}
            onClick={() => { togglePanel('gym'); loadGymData() }}>
            <span className="sb-action-icon">🏋️</span> SLM Gym
            {gymAgents.length > 0 && <span className="sb-badge gym-badge">{gymAgents.length}</span>}
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

        {/* Settings + Theme picker */}
        <div className="sb-bottom">
          {/* Theme picker */}
          <div className="sb-theme-row">
            <span className="sb-theme-label">THEME</span>
            <div className="sb-theme-swatches">
              {([
                { id: 'void',  dot: '#8b5cf6', label: 'Void'  },
                { id: 'slate', dot: '#3b95dc', label: 'Slate' },
                { id: 'ember', dot: '#e89426', label: 'Ember' },
                { id: 'light', dot: '#0ea5a0', label: 'Light' },
              ] as { id: Theme; dot: string; label: string }[]).map(t => (
                <button
                  key={t.id}
                  id={`theme-${t.id}`}
                  className={`sb-theme-swatch ${theme === t.id ? 'active' : ''}`}
                  style={{ '--swatch': t.dot } as React.CSSProperties}
                  title={t.label}
                  onClick={() => setTheme(t.id)}
                />
              ))}
            </div>
          </div>
          <button id="btn-settings" className="sb-settings-toggle" onClick={() => { setShowSettings(s => !s); setActivePanel(null) }}>
            <span>⚙</span>
            <span>{AGENT_LABELS[agentType]}</span>
            {model && <span className="sb-model-tag">{model.split(':')[0]}</span>}
          </button>
          {showSettings && (
            <div className="sb-settings">
              <div className="sb-set-label">MODEL SOURCE</div>
              {(['lmstudio', 'ollama', 'ollama_cloud', 'gemini', 'huggingface'] as AgentType[]).map(a => (
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
              <div className="sb-set-label" style={{ marginTop: 12 }}>
                MAX STEPS: {maxSteps === 0 ? 'Unlimited' : maxSteps}
              </div>
              <div className="sb-model-row">
                <input
                  id="max-steps-slider"
                  type="range"
                  min="0"
                  max="100"
                  step="1"
                  className="sb-set-input"
                  style={{ height: 'auto', padding: '4px 0' }}
                  value={maxSteps}
                  onChange={e => setMaxSteps(parseInt(e.target.value))}
                />
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

      {/* Sidebar drag handle */}
      <div className="panel-drag-handle" onMouseDown={sidebar.onMouseDown} title="Drag to resize sidebar" />

      {/* ── Agent Matrix Panel ────────────────────────────────────── */}
      {activePanel === 'matrix' && (
        <aside className="slm-panel" ref={panelRef as React.RefObject<HTMLElement>} style={{ width: sidePanel.size, minWidth: sidePanel.size }}>
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
        <aside className="slm-panel phases-panel" ref={panelRef as React.RefObject<HTMLElement>} style={{ width: sidePanel.size, minWidth: sidePanel.size }}>
          <div className="slm-panel-header">
            <div className="slm-panel-title">
              <span className="slm-panel-icon">◈</span>
              <span>Phase Launcher</span>
              <span className="slm-count">SLM-v3 · {slmPhases.length} phases</span>
            </div>
            <button id="btn-close-phases" className="panel-close" onClick={() => setActivePanel(null)}>✕</button>
          </div>

          {/* Run All / Cancel strip */}
          <div className="phase-run-all-strip">
            {phaseAllRunning ? (
              <>
                <div className="phase-seq-progress">
                  <div
                    className="phase-seq-bar"
                    style={{
                      width: `${Math.round(
                        (slmPhases.filter(p => phaseRunStatus[p.id] === 'done').length / slmPhases.length) * 100
                      )}%`
                    }}
                  />
                </div>
                <button
                  id="btn-cancel-all-phases"
                  className="phase-cancel-btn"
                  onClick={() => { phaseAllCancelRef.current = true }}
                >
                  ⏹ Cancel Run
                </button>
              </>
            ) : (
              <button
                id="btn-run-all-phases"
                className="phase-run-all-btn"
                disabled={!activeProject}
                onClick={() => launchAllPhases()}
              >
                ▶▶ Run All Phases Sequentially
              </button>
            )}
          </div>

          <div className="phases-list">
            {slmPhases.map(phase => {
              const status = phaseRunStatus[phase.id] ?? 'idle'
              return (
                <div key={phase.id} className={`phase-card phase-card-${status}`}>
                  <div className="phase-header">
                    <span className="phase-num">Phase {phase.phase_num}</span>
                    <span className="phase-name">{phase.name}</span>
                    <span className="phase-status-dot">
                      {status === 'running' && <span className="phase-spinner" />}
                      {status === 'done'    && <span className="phase-done-check">✓</span>}
                    </span>
                  </div>
                  <div className="phase-desc">{phase.description}</div>
                  <div className="phase-chain">
                    {phase.chain.map(c => (
                      <span key={c} className={`phase-chip ${status === 'running' ? 'phase-chip-active' : ''}`}>{c}</span>
                    ))}
                  </div>
                  <button
                    id={`launch-phase-${phase.phase_num}`}
                    className={`phase-launch-btn ${status === 'running' ? 'running' : ''} ${status === 'done' ? 'done' : ''}`}
                    onClick={() => launchPhase(phase)}
                    disabled={!activeProject || status === 'running' || phaseAllRunning}>
                    {status === 'running' ? '⟳ Running…'
                      : status === 'done' ? '✓ Completed — Re-run'
                      : activeProject ? `▶ Launch Phase ${phase.phase_num}`
                      : 'Select a project first'}
                  </button>
                </div>
              )
            })}
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
        <aside className="slm-panel mcp-panel" ref={panelRef as React.RefObject<HTMLElement>} style={{ width: sidePanel.size, minWidth: sidePanel.size }}>
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
                <div key={srv.id} className="mcp-server-tab-wrap">
                  <button
                    id={`btn-mcp-srv-${srv.id}`}
                    className={`mcp-server-tab ${mcpActiveServer?.id === srv.id ? 'active' : ''}`}
                    onClick={() => { setMcpActiveServer(srv); setMcpExpandedTool(null); setMcpCallResult(null) }}
                  >
                    <span className="mcp-srv-icon">{srv.icon}</span>
                    <span className="mcp-srv-name">{srv.name}</span>
                    <span className={`mcp-health-dot ${srv.healthy ? 'ok' : 'fail'}`} />
                  </button>
                  {srv.removable && (
                    <button
                      id={`btn-mcp-remove-${srv.id}`}
                      className="mcp-srv-remove-btn"
                      title={`Remove ${srv.name}`}
                      onClick={async (e) => {
                        e.stopPropagation()
                        if (!confirm(`Remove "${srv.name}" and all its tools?`)) return
                        try {
                          await fetch(`/api/mcp/servers/${srv.id}`, { method: 'DELETE' })
                          if (mcpActiveServer?.id === srv.id) setMcpActiveServer(null)
                          const d = await fetch('/api/mcp/servers').then(r => r.json())
                          setMcpServers(d.servers ?? [])
                          setMcpTotalTools(d.total_tools ?? 0)
                          // Also refresh repo list if it was a repo
                          if (srv.id.startsWith('repo_')) {
                            const rd = await fetch('/api/repos').then(r => r.json())
                            setRepoList(rd.repos ?? [])
                          }
                        } catch (err) { alert(`Remove failed: ${err}`) }
                      }}
                    >✕</button>
                  )}
                </div>
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

          {/* ── 🛸 Repos→MCP Section ── */}
          <div className="repo-mcp-section">
            <div className="repo-mcp-header" onClick={loadRepos}>
              <span className="repo-mcp-icon">🛸</span>
              <span className="repo-mcp-title">Repos → MCP Tools</span>
              <span className="repo-mcp-count">{repoList.length} connected</span>
              <span className="repo-mcp-refresh" title="Refresh">↻</span>
            </div>

            <div className="repo-add-form">
              <input
                className="repo-input repo-input-url"
                placeholder="https://github.com/owner/repo"
                value={repoUrl}
                onChange={e => setRepoUrl(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && repoAdd()}
              />
              <div className="repo-add-extras">
                <input className="repo-input repo-input-sm" placeholder="Tool name (optional)"
                  value={repoName} onChange={e => setRepoName(e.target.value)} />
                <input className="repo-input repo-input-sm" placeholder="Branch (optional)"
                  value={repoBranch} onChange={e => setRepoBranch(e.target.value)} />
                <input className="repo-input repo-input-sm" type="password" placeholder="PAT (private repos)"
                  value={repoToken} onChange={e => setRepoToken(e.target.value)} />
              </div>
              {repoError && <div className="repo-error">⚠ {repoError}</div>}
              <button className="repo-btn-add" onClick={repoAdd}
                disabled={repoLoading || !repoUrl.trim()}>
                {repoLoading ? '◌ Cloning…' : '🛸 Add Repo as MCP Tool'}
              </button>
            </div>

            {repoList.length > 0 && (
              <div className="repo-list">
                {repoList.map(r => (
                  <div key={r.slug} className="repo-card">
                    <div className="repo-card-header">
                      <div className="repo-card-info">
                        <span className="repo-card-name">{r.name}</span>
                        <span className="repo-card-langs">{(r.languages ?? []).join(' · ')}</span>
                      </div>
                      <div className="repo-card-actions">
                        <button className="repo-card-btn" title="Pull latest"
                          onClick={async () => { await fetch(`/api/repos/${r.name}/pull`, { method: 'POST' }) }}>↻</button>
                        <button className="repo-card-btn repo-card-btn-del" title="Remove"
                          onClick={() => repoRemove(r.name)}>✕</button>
                      </div>
                    </div>
                    <a className="repo-card-url" href={r.url} target="_blank" rel="noreferrer">{r.url}</a>
                    {r.readme_excerpt && (
                      <div className="repo-card-readme">{r.readme_excerpt.slice(0, 130)}…</div>
                    )}
                    <div className="repo-card-tools">
                      {['info','tree','read','query','run','pull'].map(t => (
                        <span key={t} className="repo-tool-badge">repo_{r.slug}_{t}</span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </aside>
      )}

      {/* ── SLM Gym Panel ─────────────────────────────────────────── */}
      {activePanel === 'gym' && (
        <aside className="slm-panel gym-panel" ref={panelRef as React.RefObject<HTMLElement>} style={{ width: sidePanel.size, minWidth: sidePanel.size }}>
          <div className="slm-panel-header">
            <div className="slm-panel-title">
              <span className="slm-panel-icon">🏋️</span>
              <span>SLM Gym</span>
              <span className="slm-count">Agent Forge &amp; Trainer</span>
            </div>
            <button id="btn-close-gym" className="panel-close" onClick={() => setActivePanel(null)}>✕</button>
          </div>

          {/* Graduation flash */}
          {gymForgedFlash && (
            <div className="gym-flash">
              <span className="gym-flash-icon">🎓</span>
              <span>{gymForgedFlash}</span>
            </div>
          )}

          {/* Tabs */}
          <div className="gym-tabs">
            {(['chat', 'agents', 'clusters', 'scenarios', 'secrets', 'autopilot'] as const).map(t => (
              <button key={t} id={`gym-tab-${t}`}
                className={`gym-tab ${gymTab === t ? 'active' : ''} ${t === 'autopilot' && pilotEnabled ? 'pilot-active' : ''}`}
                onClick={() => {
                  setGymTab(t)
                  if (t === 'secrets') loadCryptKeeper()
                  if (t === 'autopilot') {
                    fetch('/api/autopilot/status').then(r => r.json()).then(d => {
                      setPilotStatus(d); setPilotEnabled(d.enabled); setPilotInterval(d.interval_min || 10)
                    })
                    fetch('/api/autopilot/log?n=80').then(r => r.json()).then(d => setPilotLog(d.events ?? []))
                  }
                }}>
                {t === 'chat'      ? '💬 Instructor'
                 : t === 'agents'    ? `🤖 Agents (${gymAgents.length})`
                 : t === 'clusters'  ? `🔗 Clusters (${gymClusters.length})`
                 : t === 'scenarios' ? `📋 Scenarios (${gymScenarios.length})`
                 : t === 'autopilot' ? `✈ MCPilot${pilotEnabled ? ' ●' : ''}`
                 : `🔐 Secrets${ckReqs.filter(r=>r.status==='pending').length ? ` (${ckReqs.filter(r=>r.status==='pending').length})` : ''}`}
              </button>
            ))}
          </div>

          {/* ── Instructor Chat Tab ── */}
          {gymTab === 'chat' && (
            <div className="gym-chat-area">
              <div className="gym-chat-messages">
                {gymMessages.length === 0 && (
                  <div className="gym-empty-state">
                    <div className="gym-empty-icon">🏋️</div>
                    <div className="gym-empty-title">SLM Gym Instructor</div>
                    <div className="gym-empty-desc">The Instructor forges, trains, and graduates new SLM agents with surgical precision. Tell me what kind of agent you need.</div>
                    <div className="gym-prompts">
                      {[
                        'Forge me a Zero-Trust WASM security auditor',
                        'Create a DeFi MEV arbitrage cluster (5 agents)',
                        'Build a real-time analytics pipeline cluster',
                        'Forge an AI safety red-teaming specialist',
                      ].map(p => (
                        <button key={p} className="gym-prompt-chip" onClick={() => { setGymInput(p) }}>
                          {p}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {gymMessages.map((msg, i) => (
                  <div key={i} className={`gym-msg gym-msg-${msg.role}`}>
                    <div className="gym-msg-header">
                      <span className="gym-msg-avatar">{msg.role === 'user' ? '👤' : '🏋️'}</span>
                      <span className="gym-msg-label">{msg.role === 'user' ? 'You' : 'Instructor'}</span>
                    </div>
                    <div className="gym-msg-body">
                      {/* Show thinking/tool events */}
                      {msg.role === 'assistant' && msg.events.filter(e => e.type === 'thinking_text' || e.type === 'tool_call' || e.type === 'gym_agent_forged').map((ev, j) => {
                        if (ev.type === 'thinking_text') return <div key={j} className="gym-thinking">💭 {ev.content}</div>
                        if (ev.type === 'gym_agent_forged' && ev.agent) return (
                          <div key={j} className="gym-forged-event">
                            🎓 <strong>{ev.agent.coord}</strong> — {ev.agent.name}
                            <span className="gym-forged-brilliance">{ev.agent.brilliance}</span>
                          </div>
                        )
                        if (ev.type === 'tool_call') return (
                          <div key={j} className="gym-tool-call">
                            🔧 {ev.tool}{ev.tool === 'mcp_call' && ev.args ? ` → ${(ev.args as { tool?: string }).tool ?? ''}` : ''}
                          </div>
                        )
                        return null
                      })}
                      {msg.content ? (
                        <div className="gym-msg-text">{msg.content}</div>
                      ) : (
                        !msg.done && <div className="gym-spinner">⟳ Instructor is forging…</div>
                      )}
                    </div>
                  </div>
                ))}
                <div ref={gymBottomRef} />
              </div>

              <div className="gym-input-area">
                <textarea
                  id="gym-input"
                  className="gym-textarea"
                  placeholder={activeProject ? 'Ask the Instructor to forge an agent, create a cluster, or install MCP tools…' : 'Select a project first'}
                  value={gymInput}
                  disabled={!activeProject || gymStreaming}
                  onChange={e => setGymInput(e.target.value)}
                  onKeyDown={e => {
                    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); gymSendMessage() }
                  }}
                  rows={3}
                />
                <div className="gym-input-actions">
                  <span className="gym-hint">Ctrl+Enter to send</span>
                  {gymStreaming ? (
                    <button id="btn-gym-abort" className="gym-abort-btn" onClick={gymAbort}>⏹ Abort</button>
                  ) : (
                    <button id="btn-gym-send" className="gym-send-btn" onClick={gymSendMessage} disabled={!gymInput.trim() || !activeProject}>
                      🏋️ Forge
                    </button>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* ── Agents Tab ── */}
          {gymTab === 'agents' && (
            <div className="gym-roster">
              {gymAgents.length === 0 ? (
                <div className="gym-empty-state">
                  <div className="gym-empty-icon">🤖</div>
                  <div className="gym-empty-title">No custom agents yet</div>
                  <div className="gym-empty-desc">Use the Instructor chat to forge your first agent.</div>
                </div>
              ) : (
                gymAgents.map(agent => {
                  const h = CLUSTER_HUE[agent.cluster] ?? 42
                  return (
                    <div key={agent.coord} className="gym-agent-card"
                      style={{ background: `hsla(${h},55%,45%,0.08)`, borderColor: `hsla(${h},55%,55%,0.25)` }}>
                      <div className="gym-agent-coord" style={{ color: `hsl(${h},70%,65%)` }}>{agent.coord}</div>
                      <div className="gym-agent-name">{agent.name}</div>
                      <div className="gym-agent-brilliance">{agent.brilliance}</div>
                      <div className="gym-agent-cluster">{agent.cluster}</div>
                      <button className="gym-agent-activate" onClick={() => { activateAgent(agent); setActivePanel(null) }}>
                        ▶ Activate
                      </button>
                    </div>
                  )
                })
              )}
            </div>
          )}

          {/* ── Clusters Tab ── */}
          {gymTab === 'clusters' && (
            <div className="gym-roster">
              {gymClusters.length === 0 && gymScenarios.length === 0 ? (
                <div className="gym-empty-state">
                  <div className="gym-empty-icon">🔗</div>
                  <div className="gym-empty-title">No clusters or scenarios yet</div>
                  <div className="gym-empty-desc">Ask the Instructor to forge a cluster or record training scenarios.</div>
                </div>
              ) : (
                <>
                  {gymClusters.length > 0 && (
                    <>
                      <div className="gym-section-label">CLUSTERS</div>
                      {gymClusters.map(cl => (
                        <div key={cl.name} className="gym-cluster-card">
                          <div className="gym-cluster-name">🔗 {cl.name}</div>
                          <div className="gym-cluster-desc">{cl.description}</div>
                          <div className="gym-cluster-agents">
                            {cl.agents.map(coord => <span key={coord} className="gym-coord-chip">{coord}</span>)}
                          </div>
                        </div>
                      ))}
                    </>
                  )}
                  {gymScenarios.length > 0 && (
                    <>
                      <div className="gym-section-label" style={{ marginTop: 16 }}>TRAINING SCENARIOS</div>
                      {gymScenarios.map(sc => (
                        <div key={sc.id} className="gym-scenario-card">
                          <div className="gym-scenario-header">
                            <span className="gym-scenario-name">{sc.name}</span>
                            <span className="gym-scenario-keyword">{sc.agent_keyword}</span>
                          </div>
                          <div className="gym-scenario-prompt">{sc.prompt}</div>
                          {sc.expected && <div className="gym-scenario-expected">Expected: {sc.expected}</div>}
                        </div>
                      ))}
                    </>
                  )}
                </>
              )}
            </div>
          )}

          {/* Scenarios tab mirrors clusters tab */}
          {gymTab === 'scenarios' && (
            <div className="gym-roster">
              {gymScenarios.length === 0 ? (
                <div className="gym-empty-state">
                  <div className="gym-empty-icon">📋</div>
                  <div className="gym-empty-title">No training scenarios yet</div>
                  <div className="gym-empty-desc">The Instructor records 2+ evaluation scenarios per forged agent.</div>
                </div>
              ) : (
                gymScenarios.map(sc => (
                  <div key={sc.id} className="gym-scenario-card">
                    <div className="gym-scenario-header">
                      <span className="gym-scenario-name">{sc.name}</span>
                      <span className="gym-scenario-keyword">{sc.agent_keyword}</span>
                    </div>
                    <div className="gym-scenario-prompt">{sc.prompt}</div>
                    {sc.expected && <div className="gym-scenario-expected">Expected: {sc.expected}</div>}
                  </div>
                ))
              )}
            </div>
          )}

          {/* ── 🔐 CryptKeeper Secrets Tab ── */}
          {gymTab === 'secrets' && (
            <div className="ck-panel">

              {/* Pending requests from Forge agents */}
              {ckReqs.filter(r => r.status === 'pending').length > 0 && (
                <div className="ck-section">
                  <div className="ck-section-title">🔔 Agent Key Requests</div>
                  {ckReqs.filter(r => r.status === 'pending').map(req => {
                    let inlineVal = ''
                    return (
                      <div key={req.name} className="ck-request-card">
                        <div className="ck-req-header">
                          <code className="ck-req-name">{req.name}</code>
                          {req.has_browser_path
                            ? <span className="ck-badge ck-badge-browser">🌐 Browser path available</span>
                            : <span className="ck-badge ck-badge-key">🔑 API key required</span>}
                        </div>
                        <div className="ck-req-reason">{req.reason}</div>
                        {req.browser_alternative && (
                          <div className="ck-req-browser-alt">
                            <span className="ck-req-browser-label">Browser alt:</span> {req.browser_alternative}
                          </div>
                        )}
                        {req.service_url && (
                          <a className="ck-req-url" href={req.service_url} target="_blank" rel="noreferrer">
                            🔗 Get key →
                          </a>
                        )}
                        <div className="ck-req-actions">
                          <input
                            className="ck-inline-input"
                            type="password"
                            placeholder={`Paste ${req.name}…`}
                            onChange={e => { inlineVal = e.target.value }}
                            onKeyDown={async e => {
                              if (e.key === 'Enter') {
                                const v = (e.target as HTMLInputElement).value.trim()
                                if (v) await ckApproveInline(req.name, v)
                              }
                            }}
                          />
                          {req.has_browser_path && (
                            <button className="ck-btn ck-btn-browser" onClick={() => ckDeny(req.name)}
                              title="Tell agent to use browser path">
                              🌐 Use Browser
                            </button>
                          )}
                          <button className="ck-btn ck-btn-dismiss" onClick={() => ckDismiss(req.name)}
                            title="Dismiss">✕</button>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}

              {/* Add / update a key */}
              <div className="ck-section">
                <div className="ck-section-title">➕ Add / Update Key</div>
                <div className="ck-add-row">
                  <input
                    className="ck-input ck-input-name"
                    placeholder="KEY_NAME"
                    value={ckName}
                    onChange={e => setCkName(e.target.value.toUpperCase().replace(/\s/g, '_'))}
                    spellCheck={false}
                  />
                  <div className="ck-value-wrap">
                    <input
                      className="ck-input ck-input-value"
                      type={ckMasked ? 'password' : 'text'}
                      placeholder="value…"
                      value={ckValue}
                      onChange={e => setCkValue(e.target.value)}
                      onKeyDown={e => e.key === 'Enter' && ckStore()}
                    />
                    <button className="ck-eye" title="Toggle visibility"
                      onClick={() => setCkMasked(m => !m)}>
                      {ckMasked ? '👁' : '🙈'}
                    </button>
                  </div>
                  <button className="ck-btn ck-btn-save" onClick={ckStore}
                    disabled={ckLoading || !ckName.trim() || !ckValue.trim()}>
                    {ckLoading ? '…' : 'Save'}
                  </button>
                </div>
                <div className="ck-hint">Saved to <code>~/.open_codex/.env</code> — all MCP servers source this file.</div>
              </div>

              {/* Stored keys list */}
              <div className="ck-section">
                <div className="ck-section-title">🗝 Stored Keys ({ckKeys.length})</div>
                {ckKeys.length === 0
                  ? <div className="ck-empty">No keys stored yet. Add one above or wait for an agent request.</div>
                  : (
                    <div className="ck-keys-list">
                      {ckKeys.map(k => (
                        <div key={k} className="ck-key-row">
                          <code className="ck-key-name">{k}</code>
                          <span className="ck-key-dots">••••••••</span>
                          <button className="ck-btn ck-btn-del" title="Remove" onClick={() => ckDelete(k)}>✕</button>
                        </div>
                      ))}
                    </div>
                  )}
              </div>

            </div>
          )}

          {/* ── ✈ Auto-MCPilot Tab ── */}
          {gymTab === 'autopilot' && (
            <div className="pilot-panel">
              {/* Hero toggle */}
              <div className="pilot-hero">
                <div className="pilot-hero-left">
                  <span className="pilot-icon">✈</span>
                  <div>
                    <div className="pilot-title">Auto-MCPilot</div>
                    <div className="pilot-subtitle">
                      Autonomously discovers, clones, and registers new tools + agent clusters while you work
                    </div>
                  </div>
                </div>
                <button
                  id="btn-pilot-toggle"
                  className={`pilot-toggle ${pilotEnabled ? 'on' : 'off'}`}
                  onClick={async () => {
                    setPilotRunning(true)
                    try {
                      const res = await fetch('/api/autopilot/toggle', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ enabled: !pilotEnabled, interval_min: pilotInterval }),
                      })
                      const d = await res.json()
                      setPilotEnabled(d.enabled)
                      setPilotStatus(d)
                    } finally { setPilotRunning(false) }
                  }}
                  disabled={pilotRunning}
                >
                  <span className="pilot-toggle-knob" />
                  <span className="pilot-toggle-label">{pilotEnabled ? 'ON' : 'OFF'}</span>
                </button>
              </div>

              {/* Config */}
              <div className="pilot-config">
                <label className="pilot-config-label">
                  Run every
                  <input
                    type="range" min={1} max={60} value={pilotInterval}
                    className="pilot-slider"
                    onChange={e => setPilotInterval(Number(e.target.value))}
                    onMouseUp={async () => {
                      if (!pilotEnabled) return
                      await fetch('/api/autopilot/toggle', {
                        method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ enabled: true, interval_min: pilotInterval }),
                      })
                    }}
                  />
                  <strong>{pilotInterval} min</strong>
                </label>
                <button
                  id="btn-pilot-run-now"
                  className="pilot-run-now"
                  title="Trigger one cycle immediately"
                  onClick={async () => {
                    await fetch('/api/autopilot/run', { method: 'POST' })
                    // Start subscribing to SSE for live updates
                    const es = new EventSource('/api/autopilot/stream')
                    es.onmessage = e => {
                      try {
                        const ev = JSON.parse(e.data)
                        setPilotLog(prev => [ev, ...prev].slice(0, 200))
                      } catch {}
                    }
                    setTimeout(() => es.close(), 120_000)
                  }}
                >⚡ Run Now</button>
              </div>

              {/* Stats */}
              {pilotStatus && (
                <div className="pilot-stats">
                  <div className="pilot-stat">
                    <span className="pilot-stat-val">{pilotStatus.runs ?? 0}</span>
                    <span className="pilot-stat-key">runs</span>
                  </div>
                  <div className="pilot-stat">
                    <span className="pilot-stat-val">{pilotStatus.total_built ?? 0}</span>
                    <span className="pilot-stat-key">built</span>
                  </div>
                  <div className="pilot-stat">
                    <span className="pilot-stat-val">{pilotStatus.last_run ? new Date(pilotStatus.last_run).toLocaleTimeString() : '—'}</span>
                    <span className="pilot-stat-key">last run</span>
                  </div>
                </div>
              )}

              {/* Live log */}
              <div className="pilot-log-header">
                <span>Activity Log</span>
                <button className="pilot-log-refresh"
                  onClick={() => fetch('/api/autopilot/log?n=80').then(r=>r.json()).then(d=>setPilotLog(d.events??[]))}>
                  ↻ Refresh
                </button>
              </div>
              <div className="pilot-log">
                {pilotLog.length === 0 && (
                  <div className="pilot-log-empty">
                    No activity yet — toggle MCPilot ON or hit ⚡ Run Now
                  </div>
                )}
                {pilotLog.map(ev => (
                  <div key={ev.id} className={`pilot-log-entry pilot-log-${ev.level}`}>
                    <span className="pilot-log-ts">{new Date(ev.ts).toLocaleTimeString()}</span>
                    <span className="pilot-log-msg">{ev.msg}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </aside>
      )}

      {/* ── YOO Builder Panel ─────────────────────────────────────── */}
      {activePanel === 'yoo' && (
        <YooBuilderPanel onClose={() => setActivePanel(null)} />
      )}

      {/* ── Automations Panel ─────────────────────────────────────── */}
      {activePanel === 'automations' && (
        <aside className="slm-panel automations-panel" ref={panelRef as React.RefObject<HTMLElement>} style={{ width: sidePanel.size, minWidth: sidePanel.size }}>
          <div className="slm-panel-header">
            <div className="slm-panel-title">
              <span className="slm-panel-icon">⚡</span>
              <span>Automations</span>
              <span className="slm-count">{automations.length} tasks</span>
            </div>
            <button className="panel-close" onClick={() => setActivePanel(null)}>✕</button>
          </div>

          {/* Search */}
          <div className="auto-search-wrap">
            <input
              className="auto-search-input"
              placeholder="Search automations…"
              value={autoSearch}
              onChange={e => setAutoSearch(e.target.value)}
            />
            {autoSearch && <button className="auto-search-clear" onClick={() => setAutoSearch('')}>✕</button>}
          </div>

          <div className="auto-category-bar">
            {['All', ...Array.from(new Set(automations.map(a => a.category)))].map(cat => (
              <button key={cat}
                className={`auto-cat-btn ${automationCategory === cat ? 'active' : ''}`}
                onClick={() => setAutomationCategory(cat)}>
                {cat}
              </button>
            ))}
          </div>
          <div className="auto-list">
            {automations
              .filter(a => automationCategory === 'All' || a.category === automationCategory)
              .filter(a => !autoSearch || a.name.toLowerCase().includes(autoSearch.toLowerCase()) || a.description.toLowerCase().includes(autoSearch.toLowerCase()))
              .map(auto => {
                const isExpanded = selectedAutomation?.id === auto.id
                return (
                  <div key={auto.id} className={`auto-card ${isExpanded ? 'expanded' : ''}`}>
                    <div className="auto-card-header">
                      <span className="auto-icon">{auto.icon}</span>
                      <div className="auto-info">
                        <span className="auto-name">{auto.name}</span>
                        <span className="auto-cat">{auto.category}</span>
                      </div>
                      {auto.browser ? (
                        <button
                          id={`run-auto-${auto.id}`}
                          className="auto-run-btn browser"
                          disabled={!activeProject}
                          onClick={() => {
                            if (isExpanded) {
                              setSelectedAutomation(null)
                              setAutomationTaskInput('')
                              setAutomationUrlInput('')
                            } else {
                              setSelectedAutomation(auto)
                              setAutomationTaskInput('')
                              setAutomationUrlInput(auto.default_url ?? '')
                            }
                          }}>
                          {isExpanded ? '▲ Collapse' : '🌐 Configure'}
                        </button>
                      ) : (
                        <button
                          id={`run-auto-${auto.id}`}
                          className="auto-run-btn"
                          disabled={!activeProject}
                          onClick={() => {
                            setActivePanel(null)
                            sendMessage(auto.task_template ?? auto.description)
                          }}>
                          ▶ Run
                        </button>
                      )}
                    </div>
                    <div className="auto-desc">{auto.description}</div>

                    {/* Inline browser task configurator */}
                    {isExpanded && (
                      <div className="auto-expand">
                        <textarea
                          className="auto-expand-ta"
                          placeholder="Describe your specific target, topic, or URL…"
                          rows={3}
                          value={automationTaskInput}
                          onChange={e => setAutomationTaskInput(e.target.value)}
                        />
                        <input
                          className="auto-expand-url"
                          placeholder={auto.default_url ?? 'Starting URL (optional)'}
                          value={automationUrlInput}
                          onChange={e => setAutomationUrlInput(e.target.value)}
                        />
                        <button
                          className="auto-launch-btn"
                          disabled={!activeProject}
                          onClick={() => {
                            const fullTask = automationTaskInput.trim()
                              ? (auto.task_template ?? '') + automationTaskInput.trim()
                              : (auto.task_template ?? auto.description)
                            setBrowserTaskInput(fullTask)
                            setBrowserUrl(automationUrlInput || auto.default_url || '')
                            setSelectedAutomation(null)
                            setAutomationTaskInput('')
                            setAutomationUrlInput('')
                            setActivePanel('browser')
                          }}>
                          ▶ Launch Browser Agent
                        </button>
                      </div>
                    )}
                  </div>
                )
              })}
          </div>
        </aside>
      )}

      {/* ── Browser Agent Panel ───────────────────────────────────── */}
      {activePanel === 'browser' && (
        <aside className="slm-panel browser-panel" ref={panelRef as React.RefObject<HTMLElement>} style={{ width: sidePanel.size, minWidth: sidePanel.size }}>
          <div className="slm-panel-header">
            <div className="slm-panel-title">
              <span className="slm-panel-icon">🌐</span>
              <span>AI Browser</span>
              <span className="slm-count">AIO-NUI</span>
            </div>
            <button className="panel-close" onClick={() => setActivePanel(null)}>✕</button>
          </div>

          {/* Prior context carry-over indicator */}
          {browserPriorContext && !browserRunning && (
            <div className="browser-prior-ctx">
              <span className="browser-prior-icon">↺</span>
              <span className="browser-prior-label">Continuing session:</span>
              <span className="browser-prior-summary">{browserPriorContext.slice(0, 120)}{browserPriorContext.length > 120 ? '…' : ''}</span>
              <button className="browser-prior-clear" onClick={() => setBrowserPriorContext(null)} title="Clear session context">✕</button>
            </div>
          )}

          <div className="browser-config">
            <textarea
              id="browser-task-input"
              className="browser-task-ta"
              placeholder="Describe the task for the AI browser agent…"
              value={browserTaskInput}
              onChange={e => setBrowserTaskInput(e.target.value)}
              disabled={browserRunning}
              rows={3}
            />
            <input
              id="browser-url-input"
              className="browser-url-input"
              placeholder="Starting URL (optional)"
              value={browserUrl}
              onChange={e => setBrowserUrl(e.target.value)}
              disabled={browserRunning}
            />
            <div className="browser-controls">
              {browserRunning ? (
                <button id="btn-browser-abort" className="browser-abort-btn" onClick={abortBrowser}>
                  ⏹ Abort
                </button>
              ) : (
                <button id="btn-browser-run" className="browser-run-btn"
                  onClick={runBrowserTask} disabled={!browserTaskInput.trim()}>
                  {browserPriorContext ? '↺ Continue Session' : '▶ Launch Browser Agent'}
                </button>
              )}
              {browserRunning && (
                <span className="browser-status-badge">
                  <span className="browser-pulse" /> Step {browserStep}
                </span>
              )}
            </div>
          </div>

          {browserFrame && (
            <div className="browser-frame-wrap">
              <div className="browser-frame-bar">
                <span className="browser-frame-url" title={browserUrl}>{browserTitle || browserUrl || 'Navigating…'}</span>
                <span className="browser-frame-step">Step {browserStep}</span>
              </div>
              <img
                className="browser-frame-img"
                src={`data:${browserFrameMime};base64,${browserFrame}`}
                alt="Live browser view"
              />
            </div>
          )}

          {browserDone && (
            <div className="browser-done-banner">
              <span className="browser-done-icon">✓</span>
              <span className="browser-done-text">{browserDone}</span>
            </div>
          )}

          {browserLogs.length > 0 && (
            <div className="browser-logs" ref={browserLogRef}>
              {browserLogs.filter(ev => ev.type === 'log' || ev.type === 'error').map((ev, i) => (
                <div key={i} className={`browser-log-line ${ev.type}`}>
                  {ev.type === 'error' ? '⚠ ' : '› '}{ev.message ?? ev.content}
                </div>
              ))}
            </div>
          )}
        </aside>
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
                      <div className="commit-row">
                        <button id="btn-do-commit" className="commit-go" onClick={doCommit}
                          disabled={commitLoading || !commitMsg.trim()}>
                          {commitLoading ? '…' : '⎇ Commit'}
                        </button>
                        <button id="btn-do-pull" className="commit-pull-btn" onClick={doPull}
                          disabled={!!gitOpLoading} title="Pull from remote">
                          {gitOpLoading === 'pull' ? '…' : '↓ Pull'}
                        </button>
                        <button id="btn-do-push" className="commit-push-btn" onClick={doPush}
                          disabled={!!gitOpLoading} title="Push to remote">
                          {gitOpLoading === 'push' ? '…' : '↑ Push'}
                        </button>
                      </div>
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
                        {(msg.events.length > 0 || !msg.done) && (() => {
                          const isTeam = msg.events.some(e => e.type === 'team_plan' || e.type === 'team_decomposing' || e.type === 'team_start')
                          if (isTeam) {
                            return (
                              <div className="swarm-wrap">
                                <div className="swarm-header">
                                  {!msg.done
                                    ? <><span className="thinking-spinner swarm-hdr-spin" /><span className="swarm-hdr-label">Swarm running — {msg.events.filter(e => e.type === 'team_start').length} agent{msg.events.filter(e => e.type === 'team_start').length !== 1 ? 's' : ''} active</span></>
                                    : <><span className="swarm-hdr-done">⬡</span><span className="swarm-hdr-label">{msg.events.filter(e => e.type === 'team_start').length} agents · {msg.events.filter(e => e.type === 'file_changed').length} files changed</span></>
                                  }
                                </div>
                                <SwarmGrid events={msg.events} running={!msg.done} />
                                {/* Non-team events (errors, pre-plan steps) still shown below */}
                                {msg.events.filter(e =>
                                  e.type === 'error' && !e.agent_id
                                ).map((ev, i) => renderEvent(ev, i))}
                              </div>
                            )
                          }
                          return (
                            <details className="steps-group" open={!msg.done}>
                              <summary className="steps-summary">
                                {!msg.done ? (
                                  <><span className="thinking-spinner steps-spinner" /><span className="steps-label">Working…</span></>
                                ) : (
                                  <>
                                    <span className="steps-chevron">▶</span>
                                    <span className="steps-label">{msg.events.filter(e => e.type === 'tool_call').length} step{msg.events.filter(e => e.type === 'tool_call').length !== 1 ? 's' : ''}</span>
                                    {msg.events.filter(e => e.type === 'file_changed').length > 0 && (
                                      <span className="steps-files">· {msg.events.filter(e => e.type === 'file_changed').length} file{msg.events.filter(e => e.type === 'file_changed').length !== 1 ? 's' : ''} changed</span>
                                    )}
                                  </>
                                )}
                              </summary>
                              <div className="steps-content">
                                {msg.events.map((ev, i) => renderEvent(ev, i))}
                              </div>
                            </details>
                          )
                        })()}
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
            {/* Slash command menu */}
            {slashMenuOpen && slashMenuCommands.length > 0 && (
              <div className="slash-menu">
                {slashMenuCommands.map((sc, i) => (
                  <button
                    key={sc.cmd}
                    className={`slash-item${i === slashMenuIdx ? ' active' : ''}`}
                    onMouseDown={e => { e.preventDefault(); handleSlashSelect(sc) }}
                  >
                    <span className="slash-cmd">{sc.cmd}</span>
                    <span className="slash-desc">{sc.desc}</span>
                  </button>
                ))}
              </div>
            )}
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
                <button
                  id="btn-footer-team"
                  className={`footer-team-btn ${teamMode ? 'active' : ''}`}
                  onClick={() => setTeamMode(v => !v)}
                  title={teamMode ? 'Team Mode ON — click to disable' : 'Enable multi-agent swarm'}
                >
                  ⬡⬡ Team{teamMode ? ' ON' : ''}
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
